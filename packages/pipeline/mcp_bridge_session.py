"""Session pool + multiplexed child workers for ``scubiee-mcp-bridge``.

Industry patterns:
- mcp-stdio: per-session backend child for isolation (Streamable HTTP)
- mcp-mux: shared / isolated / session-aware routing modes
- avelino/mcp: writer + reader tasks, pending-id map for concurrent in-flight RPC
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from collections import OrderedDict
from typing import Any, Callable

_INTERNAL_ID_PREFIX = "__bridge_"


def bridge_mode() -> str:
    raw = (os.environ.get("CTX_MCP_BRIDGE_MODE") or "auto").strip().lower()
    if raw in {"shared", "isolated", "auto"}:
        return raw
    return "auto"


def max_bridge_sessions() -> int:
    raw = (os.environ.get("CTX_MCP_BRIDGE_MAX_SESSIONS") or "8").strip()
    try:
        return max(1, min(int(raw), 32))
    except ValueError:
        return 8


def extract_session_key(msg: dict[str, Any]) -> str | None:
    """Best-effort session key from a client JSON-RPC message (all hosts)."""
    from pipeline.session_isolation import bridge_routing_session_key

    key, _source = bridge_routing_session_key(msg)
    return key


class ChildWorker:
    """One ``scubiee-mcp`` subprocess with multiplexed stdin/stdout JSON-RPC."""

    def __init__(
        self,
        *,
        session_key: str,
        spawn_fn: Callable[[dict[str, str]], subprocess.Popen[str]],
        stderr_log: Callable[[str], None],
    ) -> None:
        self.session_key = session_key
        self._spawn_fn = spawn_fn
        self._stderr_log = stderr_log
        self._child: subprocess.Popen[str] | None = None
        self._spawn_gen = 0
        self._loaded_build_id: str | None = None
        self._cached_initialize: dict[str, Any] | None = None
        self._client_initialized = False
        self._pending_notice = False
        self._last_exit: dict[str, Any] | None = None
        self._spawn_lock = threading.RLock()
        self._pending: dict[Any, queue.Queue[dict[str, Any]]] = {}
        self._internal_wait: dict[str, queue.Queue[dict[str, Any]]] = {}
        self._write_queue: queue.Queue[str | None] = queue.Queue()
        self._reader_stop = threading.Event()
        self._stderr_stop = threading.Event()
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._writer_thread: threading.Thread | None = None
        self._next_internal_id = 0
        self.last_used = time.time()

    def touch(self) -> None:
        self.last_used = time.time()

    def needs_respawn(self) -> bool:
        if self._child is None:
            return True
        if self._child.poll() is not None:
            return True
        from pipeline.mcp_hot_reload import current_build_id

        active = current_build_id()
        if active and self._loaded_build_id and active != self._loaded_build_id:
            return True
        return False

    def set_handshake(self, init_msg: dict[str, Any] | None, *, client_initialized: bool) -> None:
        if init_msg:
            self._cached_initialize = dict(init_msg)
        self._client_initialized = client_initialized

    def _child_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["CTX_MCP_BRIDGE_CHILD"] = "1"
        env.pop("CTX_MCP_BRIDGE_SPAWN", None)
        env.pop("CTX_MCP_BRIDGE_SPAWN_JSON", None)
        if self.session_key and self.session_key != "__shared__":
            env["CTX_MCP_SESSION_ID"] = self.session_key
        return env

    def _alloc_internal_id(self) -> str:
        self._next_internal_id += 1
        return f"{_INTERNAL_ID_PREFIX}{self._next_internal_id}"

    def _start_writer(self) -> None:
        if self._writer_thread and self._writer_thread.is_alive():
            return

        def _loop() -> None:
            while True:
                item = self._write_queue.get()
                if item is None:
                    break
                child = self._child
                if child is None or child.stdin is None:
                    continue
                try:
                    child.stdin.write(item)
                    child.stdin.flush()
                except OSError as exc:
                    self._stderr_log(f"[scubiee-bridge worker {self.session_key}] write failed: {exc}")

        self._writer_thread = threading.Thread(
            target=_loop,
            name=f"mcp-bridge-writer-{self.session_key}",
            daemon=True,
        )
        self._writer_thread.start()

    def _enqueue_write(self, msg: dict[str, Any]) -> None:
        payload = json.dumps(msg, separators=(",", ":")) + "\n"
        self._write_queue.put(payload)

    def _start_reader(self) -> None:
        def _loop() -> None:
            child = self._child
            if child is None or child.stdout is None:
                return
            for raw in child.stdout:
                if self._reader_stop.is_set():
                    break
                line = raw.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    self._stderr_log(f"[scubiee-bridge worker {self.session_key}] bad json: {line[:120]}")
                    continue
                if not isinstance(msg, dict):
                    continue
                self._route_child_message(msg)

        self._reader_stop.clear()
        self._reader_thread = threading.Thread(
            target=_loop,
            name=f"mcp-bridge-reader-{self.session_key}",
            daemon=True,
        )
        self._reader_thread.start()

    def _start_stderr_drain(self) -> None:
        def _loop() -> None:
            child = self._child
            if child is None or child.stderr is None:
                return
            for raw in child.stderr:
                if self._stderr_stop.is_set():
                    break
                line = raw.rstrip("\r\n")
                if line:
                    self._stderr_log(f"[scubiee-bridge child {self.session_key}] {line}")

        self._stderr_stop.clear()
        self._stderr_thread = threading.Thread(
            target=_loop,
            name=f"mcp-bridge-stderr-{self.session_key}",
            daemon=True,
        )
        self._stderr_thread.start()

    def _join_io_threads(self, *, timeout: float = 1.0) -> None:
        for thread in (self._reader_thread, self._stderr_thread):
            if thread is not None and thread.is_alive():
                thread.join(timeout=timeout)
        if self._writer_thread and self._writer_thread.is_alive():
            self._write_queue.put(None)
            self._writer_thread.join(timeout=timeout)

    def _route_child_message(self, msg: dict[str, Any]) -> None:
        msg_id = msg.get("id")
        if isinstance(msg_id, str) and str(msg_id).startswith(_INTERNAL_ID_PREFIX):
            waiter = self._internal_wait.get(msg_id)
            if waiter is not None:
                waiter.put(msg)
            return
        if msg_id is not None:
            waiter = self._pending.get(msg_id)
            if waiter is not None:
                waiter.put(msg)
                return

    def kill(self) -> None:
        with self._spawn_lock:
            child = self._child
            self._child = None
            if child is None:
                return
            self._reader_stop.set()
            self._stderr_stop.set()
            self._join_io_threads()
            rc = child.poll()
            if rc is None:
                try:
                    child.terminate()
                    child.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=2.0)
                except OSError as exc:
                    self._stderr_log(f"[scubiee-bridge worker {self.session_key}] kill: {exc}")
            if rc is None:
                rc = child.poll()
            self._last_exit = {"code": rc, "gen": self._spawn_gen}

    def spawn(self) -> None:
        with self._spawn_lock:
            self.kill()
            self._spawn_gen += 1
            gen = self._spawn_gen
            try:
                self._child = self._spawn_fn(self._child_env())
            except OSError as exc:
                raise RuntimeError(f"spawn failed for {self.session_key}: {exc}") from exc
            self._stderr_log(
                f"[scubiee-bridge] spawned worker session={self.session_key} "
                f"gen={gen} pid={self._child.pid}"
            )
            self._start_writer()
            self._start_reader()
            self._start_stderr_drain()

    def _replay_handshake(self) -> None:
        if not self._cached_initialize:
            return
        init_resp = self._request_internal(dict(self._cached_initialize))
        if init_resp.get("error"):
            raise RuntimeError(f"initialize replay failed: {init_resp.get('error')}")
        if self._client_initialized:
            self._enqueue_write({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def ensure_ready(self, *, for_method: str | None = None) -> None:
        with self._spawn_lock:
            respawn = self.needs_respawn()
            if not respawn and self._child is not None:
                return
            had_child = self._child is not None or self._loaded_build_id is not None
            if for_method in ("tools/call", "tools/list") and had_child:
                self._pending_notice = True
            self.spawn()
            self._replay_handshake()
            from pipeline.mcp_hot_reload import current_build_id

            self._loaded_build_id = current_build_id()

    def _request_internal(self, msg: dict[str, Any], *, timeout: float = 120.0) -> dict[str, Any]:
        internal_id = self._alloc_internal_id()
        payload = {**msg, "id": internal_id}
        waiter: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        self._internal_wait[internal_id] = waiter
        try:
            self._enqueue_write(payload)
            return waiter.get(timeout=timeout)
        finally:
            self._internal_wait.pop(internal_id, None)

    def request(self, msg: dict[str, Any], *, timeout: float = 120.0) -> dict[str, Any]:
        self.touch()
        msg_id = msg.get("id")
        if msg_id is None:
            self._enqueue_write(msg)
            return {}
        waiter: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        self._pending[msg_id] = waiter
        try:
            self._enqueue_write(msg)
            return waiter.get(timeout=timeout)
        finally:
            self._pending.pop(msg_id, None)

    def consume_pending_notice(self) -> bool:
        if self._pending_notice:
            self._pending_notice = False
            return True
        return False

    @property
    def spawn_gen(self) -> int:
        return self._spawn_gen

    @property
    def last_exit(self) -> dict[str, Any] | None:
        return self._last_exit

    @property
    def loaded_build_id(self) -> str | None:
        return self._loaded_build_id


class SessionRegistry:
    """Route client messages to shared or per-session child workers."""

    def __init__(
        self,
        *,
        spawn_fn: Callable[[dict[str, str]], subprocess.Popen[str]],
        stderr_log: Callable[[str], None],
    ) -> None:
        self._spawn_fn = spawn_fn
        self._stderr_log = stderr_log
        self._lock = threading.RLock()
        self._workers: OrderedDict[str, ChildWorker] = OrderedDict()
        self._cached_initialize: dict[str, Any] | None = None
        self._client_initialized = False

    def set_handshake(self, init_msg: dict[str, Any] | None, *, client_initialized: bool) -> None:
        with self._lock:
            if init_msg:
                self._cached_initialize = dict(init_msg)
            self._client_initialized = client_initialized
            for worker in self._workers.values():
                worker.set_handshake(self._cached_initialize, client_initialized=client_initialized)

    def _evict_if_needed(self) -> None:
        cap = max_bridge_sessions()
        while len(self._workers) > cap:
            key, worker = self._workers.popitem(last=False)
            worker.kill()
            self._stderr_log(f"[scubiee-bridge] evicted idle session worker {key}")

    def _get_or_create(self, session_key: str) -> ChildWorker:
        with self._lock:
            worker = self._workers.get(session_key)
            if worker is None:
                worker = ChildWorker(
                    session_key=session_key,
                    spawn_fn=self._spawn_fn,
                    stderr_log=self._stderr_log,
                )
                worker.set_handshake(self._cached_initialize, client_initialized=self._client_initialized)
                self._workers[session_key] = worker
                self._workers.move_to_end(session_key)
                self._evict_if_needed()
            else:
                self._workers.move_to_end(session_key)
            return worker

    def shared_worker(self) -> ChildWorker:
        return self._get_or_create("__shared__")

    def worker_for_message(self, msg: dict[str, Any]) -> ChildWorker:
        from pipeline.session_isolation import bridge_routing_session_key

        mode = bridge_mode()
        session_key, source = bridge_routing_session_key(msg)
        if mode == "shared":
            return self._get_or_create("__shared__")
        if mode == "isolated":
            key = session_key or "__shared__"
            return self._get_or_create(key)
        # auto: host env session (Claude Code, Codex, …) or explicit tool session_id
        if session_key:
            if source == "host_env":
                return self._get_or_create(session_key)
            if msg.get("method") in ("tools/call", "tools/list"):
                return self._get_or_create(session_key)
        return self._get_or_create("__shared__")

    def shutdown(self) -> None:
        with self._lock:
            for worker in self._workers.values():
                worker.kill()
            self._workers.clear()
