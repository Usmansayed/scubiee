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
from pathlib import Path
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


_UV_CONSOLE_SHIMS = {
    "scubiee",
    "scubiee.exe",
    "scubiee-mcp",
    "scubiee-mcp.exe",
    "scubiee-mcp-bridge",
    "scubiee-mcp-bridge.exe",
}


def _is_uv_console_shim(cmd: str) -> bool:
    return Path(cmd).name.lower() in _UV_CONSOLE_SHIMS


def _windows_mcp_worker_command() -> tuple[str, list[str]]:
    """Always pythonw -m — never the uv console shim (visible conhost blink)."""
    from pipeline.process_job import background_python

    return background_python(), ["-u", "-m", "pipeline.mcp_locate"]


def _prefer_pythonw(cmd: str) -> str:
    if os.name != "nt":
        return cmd
    path = Path(cmd)
    if path.name.lower() != "python.exe":
        return cmd
    pyw = path.with_name("pythonw.exe")
    if pyw.is_file():
        return str(pyw)
    # Sibling missing (stale pin / half install) — never keep console python.exe;
    # that is a common source of rare conhost blinks on worker respawn.
    try:
        from pipeline.process_job import background_python

        return background_python()
    except Exception:  # noqa: BLE001
        return cmd


def resolve_child_command() -> tuple[str, list[str]]:
    """Return executable + args for the real MCP worker (not the bridge)."""
    spawn_json = (os.environ.get("CTX_MCP_BRIDGE_SPAWN_JSON") or "").strip()
    if spawn_json:
        try:
            parts = json.loads(spawn_json)
            if isinstance(parts, list) and parts:
                cmd = str(parts[0])
                args = [str(x) for x in parts[1:]]
                if os.name == "nt" and (
                    _is_uv_console_shim(cmd)
                    or Path(cmd).name.lower() in {"python.exe", "py.exe"}
                ):
                    # Avoid console-subsystem flash. Keep SPAWN_JSON args so tests
                    # (and pins of python -u fake.py) still run the intended script.
                    if args:
                        return _prefer_pythonw(cmd), args
                    return _windows_mcp_worker_command()
                return _prefer_pythonw(cmd), args
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    override = (os.environ.get("CTX_MCP_BRIDGE_SPAWN") or "").strip()
    if override:
        space = override.find(" ")
        cmd = override if space == -1 else override[:space]
        args = [] if space == -1 else [override[space + 1 :].strip()]
        if os.name == "nt" and (
            _is_uv_console_shim(cmd)
            or Path(cmd).name.lower() in {"python.exe", "py.exe"}
        ):
            if args:
                return _prefer_pythonw(cmd), args
            return _windows_mcp_worker_command()
        return _prefer_pythonw(cmd), args

    if os.name == "nt":
        return _windows_mcp_worker_command()

    mcp_exe = shutil.which("scubiee-mcp")
    if mcp_exe:
        return mcp_exe, []

    return sys.executable, ["-u", "-m", "pipeline.mcp_locate"]


def spawn_child_process(env: dict[str, str]) -> subprocess.Popen[str]:
    """Spawn one mcp_locate worker under this bridge (expected tree: Cursor→bridge→locate).

    Nested bridge→bridge / locate→locate rows in Windows process explorers are usually
    parentage display quirks of ``pythonw -m``, not a second tool server (R5/R10).
    """
    cmd, args = resolve_child_command()
    kwargs: dict[str, Any] = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "bufsize": 1,
        "env": env,
    }
    # Windows console shims (scubiee-mcp.exe) flash a terminal on every
    # respawn unless CREATE_NO_WINDOW + SW_HIDE. Never DETACHED_PROCESS.
    if os.name == "nt":
        from pipeline.process_job import windows_stdio_hidden_kwargs

        kwargs.update(windows_stdio_hidden_kwargs())
    try:
        return subprocess.Popen([cmd, *args], **kwargs)  # noqa: S603
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
        # Only notify list_changed when the worker actually respawned.
        # Emitting on every tools/call made Cursor spawn a second MCP bridge
        # (duplicate process groups) while the first was still alive — worst
        # during long expand_context / AST work.
        gen_before = worker.spawn_gen
        worker.ensure_ready(for_method=for_method)
        if (
            for_method in ("tools/call", "tools/list")
            and worker.spawn_gen != gen_before
        ):
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
                        "error": {
                            "code": -32603,
                            "message": f"{type(exc).__name__}: {str(exc) or repr(exc)}",
                        },
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
            _stderr("[scubiee-bridge] stdin EOF / host disconnected — shutting down workers")
            self._executor.shutdown(wait=True)
            self._registry.shutdown()
            # Child atexit/lifespan may not run if the host killed us hard.
            # Reconcile drops dead MCP PIDs and arms disconnect debounce.
            try:
                from pipeline.client import EngineClient

                EngineClient(timeout=2.0).post("/v1/client/reconcile", {})
                _stderr("[scubiee-bridge] posted /v1/client/reconcile after stdin EOF")
            except Exception as exc:  # noqa: BLE001
                _stderr(f"[scubiee-bridge] reconcile after EOF failed: {exc}")


def warn_ctx_home_pollution() -> None:
    from pipeline.ctx_home_guard import warn_ctx_home_pollution as _warn

    _warn(stream=sys.stderr)


def _bridge_host() -> str:
    return (os.environ.get("CTX_MCP_CLIENT") or "cursor").strip().lower() or "cursor"


def _bridge_client_id() -> str:
    return f"mcp:{_bridge_host()}@bridge-{os.getpid()}"


def _register_bridge_anchor() -> None:
    """Keep embedder/engine warm while Cursor holds the bridge process open.

    Register via engine HTTP only — never call ``register_client`` in-process
    here (that used to load FastEmbed into the bridge and waste hundreds of MB).
    """
    cid = _bridge_client_id()
    host = _bridge_host()
    try:
        from pipeline.client import EngineClient

        reg = EngineClient(timeout=3.0).post(
            "/v1/client/register",
            {
                "client_id": cid,
                "pid": os.getpid(),
                "kind": "bridge",
                "client": host,
            },
        )
        _stderr(
            f"[scubiee-bridge] warm-anchor client_id={cid} "
            f"active={(reg or {}).get('active_clients')}"
        )
    except Exception as exc:  # noqa: BLE001
        # Engine may still be down at bridge attach — local registry only (no embed).
        _stderr(f"[scubiee-bridge] warm-anchor HTTP register deferred: {exc}")
        try:
            from pipeline.lifecycle_runtime import register_client

            register_client(cid, pid=os.getpid(), kind="bridge", host=host)
        except Exception as exc2:  # noqa: BLE001
            _stderr(f"[scubiee-bridge] warm-anchor local register failed: {exc2}")


def _unregister_bridge_anchor() -> None:
    cid = _bridge_client_id()
    try:
        from pipeline.client import EngineClient

        EngineClient(timeout=2.0).post("/v1/client/unregister", {"client_id": cid})
    except Exception:  # noqa: BLE001
        pass
    try:
        from pipeline.lifecycle_runtime import unregister_client

        unregister_client(cid)
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    from pipeline.ctx_home_guard import enforce_ctx_home_or_exit

    os.environ.setdefault("CTX_MCP_BRIDGE", "1")
    enforce_ctx_home_or_exit()
    try:
        from pipeline.process_job import soften_background_priority

        soften_background_priority()
    except Exception:  # noqa: BLE001
        pass
    try:
        from pipeline.process_job import attach_mcp_kill_job

        attach_mcp_kill_job()
    except Exception as exc:  # noqa: BLE001
        _stderr(f"[scubiee-bridge] mcp kill-job skipped: {exc}")
    try:
        from pipeline.process_control import reap_orphaned_mcp_processes

        reap = reap_orphaned_mcp_processes()
        if reap.get("killed"):
            _stderr(f"[scubiee-bridge] reaped leftover MCP pids={reap.get('killed')}")
    except Exception as exc:  # noqa: BLE001
        _stderr(f"[scubiee-bridge] orphan reap skipped: {exc}")
    _register_bridge_anchor()
    try:
        from pipeline.runtime_controller import RuntimeController
        from pipeline.session_isolation import detect_mcp_host

        repo = Path(os.environ.get("CTX_REPO") or Path.cwd()).resolve()
        os.environ.setdefault("CTX_REPO", str(repo))
        os.environ.setdefault("CTX_MCP_CLIENT", detect_mcp_host())
        snap = RuntimeController.get().ensure(repo, "attach")
        _stderr(
            f"[scubiee-bridge] runtime attach state={snap.state} "
            f"warm_ready={snap.warm_ready} deadline_ms={snap.as_status_fields().get('warm_deadline_ms')}"
        )
    except Exception as exc:  # noqa: BLE001
        _stderr(f"[scubiee-bridge] attach warm skipped: {exc}")
    try:
        McpBridge().run()
    finally:
        _unregister_bridge_anchor()
        try:
            from pipeline.runtime_controller import RuntimeController

            RuntimeController.get().ensure(
                Path(os.environ.get("CTX_REPO") or Path.cwd()), "leave"
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            from pipeline.client import EngineClient

            EngineClient(timeout=2.0).post("/v1/client/reconcile", {})
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    main()
