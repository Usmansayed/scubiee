"""Stable stdio MCP bridge — lazy-respawn ``scubiee-mcp`` after upgrade without IDE restart.

The IDE/agent connects to ``scubiee-mcp-bridge`` (stable shim from ``scubiee connect``). The bridge proxies JSON-RPC
to one or more ``scubiee-mcp`` child workers and respawns them when they die or
``~/.scubiee/active_build.json`` changes (written by ``scubiee upgrade``).

v2: multiplexed per-worker IO + session routing (shared / isolated / auto modes).
Patterns: mcp-mux session modes, mcp-sitter lazy respawn + initialize replay.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pipeline.mcp_bridge_session import (
    ChildWorker,
    SessionRegistry,
    bridge_mode,
    max_bridge_sessions,
)

_NOTICE_PREFIX = "[scubiee] MCP worker restarted"


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def resolve_child_command() -> tuple[str, list[str]]:
    """Return executable + args for the real MCP worker (not the bridge)."""
    spawn_json = (os.environ.get("CTX_MCP_BRIDGE_SPAWN_JSON") or "").strip()
    if spawn_json:
        try:
            parts = json.loads(spawn_json)
            if isinstance(parts, list) and parts:
                return str(parts[0]), [str(x) for x in parts[1:]]
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    override = (os.environ.get("CTX_MCP_BRIDGE_SPAWN") or "").strip()
    if override:
        space = override.find(" ")
        if space == -1:
            return override, []
        return override[:space], [override[space + 1 :].strip()]

    mcp_exe = shutil.which("scubiee-mcp")
    if mcp_exe:
        return mcp_exe, []

    return sys.executable, ["-u", "-m", "pipeline.mcp_locate"]


def spawn_child_process(env: dict[str, str]) -> subprocess.Popen[str]:
    cmd, args = resolve_child_command()
    try:
        return subprocess.Popen(
            [cmd, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
    except OSError as exc:
        raise RuntimeError(f"spawn failed: {cmd}: {exc}") from exc


class McpBridge:
    """stdio JSON-RPC proxy with session-aware child pool + concurrent client dispatch."""

    def __init__(self) -> None:
        self._stdout_lock = threading.Lock()
        self._registry = SessionRegistry(spawn_fn=spawn_child_process, stderr_log=_stderr)
        self._executor = ThreadPoolExecutor(
            max_workers=max(4, max_bridge_sessions() * 2),
            thread_name_prefix="mcp-bridge-client",
        )

    def _shared_worker(self) -> ChildWorker:
        return self._registry.shared_worker()

    @property
    def _child(self) -> subprocess.Popen[str] | None:
        return self._shared_worker()._child  # noqa: SLF001

    @_child.setter
    def _child(self, value: subprocess.Popen[str] | None) -> None:
        self._shared_worker()._child = value  # noqa: SLF001

    @property
    def _loaded_build_id(self) -> str | None:
        return self._shared_worker().loaded_build_id

    @_loaded_build_id.setter
    def _loaded_build_id(self, value: str | None) -> None:
        self._shared_worker()._loaded_build_id = value  # noqa: SLF001

    @property
    def _spawn_gen(self) -> int:
        return self._shared_worker().spawn_gen

    def needs_respawn(self) -> bool:
        return self._shared_worker().needs_respawn()

    def kill_child(self) -> None:
        self._registry.shutdown()

    def _emit_client(self, msg: dict[str, Any]) -> None:
        with self._stdout_lock:
            sys.stdout.write(json.dumps(msg, separators=(",", ":")) + "\n")
            sys.stdout.flush()

    def _emit_tools_list_changed(self) -> None:
        self._emit_client({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})

    def _maybe_inject_notice(self, worker: ChildWorker, response: dict[str, Any]) -> dict[str, Any]:
        if not worker.consume_pending_notice():
            return response
        from pipeline.mcp_hot_reload import read_active_build_stamp
        from pipeline.upgrade import installed_version

        stamp = read_active_build_stamp() or {}
        version = stamp.get("version") or installed_version()
        build_id = stamp.get("build_id") or worker.loaded_build_id or "unknown"
        exit_bit = ""
        if worker.last_exit:
            exit_bit = f" prev_exit={worker.last_exit.get('code')}"
        notice = (
            f"{_NOTICE_PREFIX}: gen={worker.spawn_gen} version={version} "
            f"build={build_id}{exit_bit}. Tool schema may have changed."
        )
        result = response.get("result")
        if isinstance(result, dict):
            content = result.get("content")
            if isinstance(content, list):
                result = dict(result)
                result["content"] = [{"type": "text", "text": notice}, *content]
                response = {**response, "result": result}
        return response

    def _ensure_worker(self, worker: ChildWorker, *, for_method: str | None = None) -> None:
        had_child = worker._child is not None or worker.loaded_build_id is not None  # noqa: SLF001
        worker.ensure_ready(for_method=for_method)
        if had_child and for_method in ("tools/call", "tools/list"):
            self._emit_tools_list_changed()

    def handle_client_message(self, msg: dict[str, Any]) -> None:
        method = msg.get("method")

        if method == "initialize":
            self._registry.set_handshake(msg, client_initialized=False)
            worker = self._registry.worker_for_message(msg)
            self._ensure_worker(worker)
            resp = worker.request(dict(msg))
            self._emit_client(resp)
            return

        if method == "notifications/initialized":
            self._registry.set_handshake(None, client_initialized=True)
            worker = self._registry.worker_for_message(msg)
            self._ensure_worker(worker)
            worker.request(dict(msg))
            return

        worker = self._registry.worker_for_message(msg)

        if method in ("tools/call", "tools/list"):
            self._ensure_worker(worker, for_method=method)
            resp = worker.request(dict(msg))
            resp = self._maybe_inject_notice(worker, resp)
            self._emit_client(resp)
            return

        self._ensure_worker(worker)
        if msg.get("id") is not None:
            resp = worker.request(dict(msg))
            self._emit_client(resp)
        else:
            worker.request(dict(msg))

    def _dispatch_client_message(self, msg: dict[str, Any]) -> None:
        try:
            self.handle_client_message(msg)
        except Exception as exc:  # noqa: BLE001
            req_id = msg.get("id")
            _stderr(f"[scubiee-bridge] error handling {msg.get('method')}: {exc}")
            if req_id is not None:
                self._emit_client(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32603, "message": str(exc)},
                    }
                )

    def run(self) -> None:
        _stderr(f"[scubiee-bridge] ready (mode={bridge_mode()}, sessions<={max_bridge_sessions()})")
        try:
            for raw in sys.stdin:
                line = raw.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    _stderr(f"[scubiee-bridge] bad client json: {line[:200]}")
                    continue
                if not isinstance(parsed, dict):
                    continue
                self._executor.submit(self._dispatch_client_message, parsed)
        finally:
            self._executor.shutdown(wait=True)
            self._registry.shutdown()


def warn_ctx_home_pollution() -> None:
    from pipeline.ctx_home_guard import warn_ctx_home_pollution as _warn

    _warn(stream=sys.stderr)


def main() -> None:
    from pipeline.ctx_home_guard import enforce_ctx_home_or_exit

    os.environ.setdefault("CTX_MCP_BRIDGE", "1")
    enforce_ctx_home_or_exit()
    McpBridge().run()


if __name__ == "__main__":
    main()
