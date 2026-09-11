"""Universal MCP host connect / disconnect lifecycle (any IDE, any OS).

Contract (MCP spec + transport — not Cursor-specific):

**Open** — warm before any tools/call:
  - MCP worker process start / FastMCP lifespan setup
  - ``notifications/initialized`` path still served only after warm gate
  - Every locate client build re-checks embedder ready (engine may have restarted)

**Close** — unload by stopping the engine process (ORT does not free RSS in-process):
  - stdin EOF → FastMCP lifespan cleanup (portable primary signal)
  - atexit + SIGTERM/SIGINT/SIGBREAK(Windows)/SIGHUP(Unix)
  - daemon stamps ``last_client_left_at``; after ``CTX_DISCONNECT_DEBOUNCE_S`` (10s)
    idle sweeper ``enter_standby(stop_engine=True)`` exits the engine process

Hosts (Cursor, Claude Code, Codex, Kiro, Copilot, Zed, Continue, …) all speak
stdio MCP the same way. Do not special-case Cursor.
"""

from __future__ import annotations

import atexit
import os
import signal
import threading
from pathlib import Path
from typing import Any

_CLIENT_ID: str | None = None
_REPO: Path | None = None
_LEAVE_ONCE = threading.Lock()
_LEFT = False
_HEARTBEAT_STOP: threading.Event | None = None
_HEARTBEAT_THREAD: threading.Thread | None = None
_TRACE_PRELOAD_THREAD: threading.Thread | None = None


def current_client_id() -> str | None:
    return _CLIENT_ID


def _stderr(msg: str) -> None:
    print(msg, file=__import__("sys").stderr, flush=True)


def _heartbeat_interval_s() -> float:
    try:
        from pipeline.lifecycle_runtime import disconnect_debounce_seconds

        idle = float(disconnect_debounce_seconds())
    except Exception:  # noqa: BLE001
        idle = 10.0
    if idle <= 0:
        return 5.0
    return max(5.0, min(20.0, idle / 3.0))


def _stop_heartbeat() -> None:
    global _HEARTBEAT_STOP, _HEARTBEAT_THREAD
    if _HEARTBEAT_STOP is not None:
        _HEARTBEAT_STOP.set()
    _HEARTBEAT_STOP = None
    _HEARTBEAT_THREAD = None


def _start_heartbeat(repo: Path, client_id: str) -> None:
    global _HEARTBEAT_STOP, _HEARTBEAT_THREAD
    _stop_heartbeat()
    stop = threading.Event()
    _HEARTBEAT_STOP = stop

    def _loop() -> None:
        while not stop.wait(_heartbeat_interval_s()):
            try:
                from pipeline.client import EngineClient

                EngineClient(workspace_path=str(repo), timeout=1.5).post(
                    "/v1/client/touch",
                    {"client_id": client_id, "pid": os.getpid(), "kind": "mcp"},
                )
            except Exception:  # noqa: BLE001
                try:
                    from pipeline.lifecycle_runtime import note_activity, touch_client

                    if touch_client(client_id):
                        note_activity()
                except Exception:  # noqa: BLE001
                    pass

    t = threading.Thread(target=_loop, name="scubiee-mcp-heartbeat", daemon=True)
    _HEARTBEAT_THREAD = t
    t.start()


def warm_engine_for_mcp(
    repo: Path | str,
    *,
    client_id: str | None = None,
    wait_s: float | None = None,
) -> dict[str, Any]:
    """Ensure daemon + repo open + FastEmbed loaded before tools/call (blocking).

    Safe to call repeatedly (engine restart under a live MCP worker).
    """
    from pipeline.client import EngineClient
    from pipeline.daemon import ensure_daemon
    from pipeline.session_isolation import effective_session_id, mcp_client_name

    root = Path(repo).resolve()
    out: dict[str, Any] = {"ok": False, "repo": str(root)}
    try:
        ensure_daemon(root, force_if_hung=True)
    except Exception as exc:  # noqa: BLE001
        out["ensure_daemon_error"] = str(exc)
        return out

    host = mcp_client_name()
    sid = effective_session_id(None)
    client = EngineClient(
        workspace_path=str(root),
        timeout=180.0,
        client=host,
        session_id=sid,
    )
    try:
        opened = client.open_repo(str(root), wait=True)
        out["open_repo"] = {
            "ok": bool(opened.get("ok", True)),
            "status": opened.get("status") or opened.get("warm_state"),
            "warm_state": opened.get("warm_state"),
        }
    except Exception as exc:  # noqa: BLE001
        out["open_repo_error"] = str(exc)

    # Register (or refresh) so disconnect debounce anchors on this MCP process.
    cid = (client_id or _CLIENT_ID or "").strip()
    if cid:
        try:
            reg = client.post(
                "/v1/client/register",
                {
                    "client_id": cid,
                    "pid": os.getpid(),
                    "kind": "mcp",
                    "client": host,
                    "session_id": sid,
                },
            )
            out["register"] = reg
            out["prewarm"] = reg.get("prewarm") if isinstance(reg, dict) else None
        except Exception as exc:  # noqa: BLE001
            out["register_error"] = str(exc)

    # Explicit wait — covers engine restart when register already ran earlier.
    try:
        prewarm = client.post(
            "/v1/embed/prewarm",
            {"path": str(root), "wait": True, "sync": True},
        )
        out["prewarm_wait"] = prewarm
        loaded = bool(
            (prewarm or {}).get("embedder_loaded")
            or (prewarm or {}).get("already_warm")
            or (prewarm or {}).get("ok")
        )
        out["ok"] = loaded
        out["embedder_loaded"] = loaded
    except Exception as exc:  # noqa: BLE001
        out["prewarm_error"] = str(exc)
        out["ok"] = False
    return out


def _preload_trace_graph(root: Path) -> None:
    """Build the MCP-side AST graph off the first-map path (daemon thread)."""
    try:
        from pipeline.context_trace import _load_repo

        _load_repo(Path(root).resolve())
        _stderr(f"[scubiee] trace graph ready (background) root={root}")
    except Exception as exc:  # noqa: BLE001
        _stderr(f"[scubiee] trace graph preload skipped: {exc}")


def spawn_trace_graph_preload(root: Path | str) -> threading.Thread:
    """Start (or reuse) a daemon thread that warms ``_load_repo`` for later pack."""
    global _TRACE_PRELOAD_THREAD
    t = _TRACE_PRELOAD_THREAD
    if t is not None and t.is_alive():
        return t
    t = threading.Thread(
        target=_preload_trace_graph,
        args=(Path(root).resolve(),),
        name="scubiee-trace-preload",
        daemon=True,
    )
    _TRACE_PRELOAD_THREAD = t
    t.start()
    return t


def leave_mcp_client(
    repo: Path | str | None = None,
    client_id: str | None = None,
) -> dict[str, Any]:
    """Unregister this MCP process. Engine stops after disconnect debounce (sweeper)."""
    global _LEFT
    with _LEAVE_ONCE:
        if _LEFT:
            return {"ok": True, "already_left": True}
        _LEFT = True
    _stop_heartbeat()
    cid = (client_id or _CLIENT_ID or "").strip()
    root = Path(repo or _REPO or os.environ.get("CTX_REPO") or ".").resolve()
    if not cid:
        return {"ok": False, "error": "no_client_id"}
    try:
        from pipeline.client import EngineClient

        result = EngineClient(workspace_path=str(root), timeout=3.0).post(
            "/v1/client/unregister",
            {"client_id": cid},
        )
        _stderr(
            f"[scubiee] mcp leave client_id={cid} remaining={result.get('active_clients')} "
            f"idle={result.get('idle')}"
        )
        return {"ok": True, **(result if isinstance(result, dict) else {})}
    except Exception as exc:  # noqa: BLE001
        _stderr(f"[scubiee] mcp leave failed: {exc}")
        return {"ok": False, "error": str(exc)}


def _install_process_signals(leave) -> None:
    """POSIX + Windows terminate signals — no host-specific branches."""

    def _on_signal(signum: int, _frame: object) -> None:
        leave()
        try:
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)
        except Exception:  # noqa: BLE001
            raise SystemExit(128 + int(signum))

    for sig_name in ("SIGTERM", "SIGINT", "SIGBREAK", "SIGHUP"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _on_signal)
        except Exception:  # noqa: BLE001
            pass


def attach_mcp_session(repo: Path | str) -> dict[str, Any]:
    """Call once when the MCP worker process is ready to serve a host.

    Blocks until the embedder is warm. Installs universal leave hooks.
    """
    global _CLIENT_ID, _REPO, _LEFT
    from pipeline.session_isolation import default_process_session_id

    root = Path(repo).resolve()
    _REPO = root
    _LEFT = False
    client_id = f"mcp:{default_process_session_id()}"
    _CLIENT_ID = client_id

    warm = warm_engine_for_mcp(root, client_id=client_id)
    _start_heartbeat(root, client_id)
    spawn_trace_graph_preload(root)

    def _leave() -> None:
        leave_mcp_client(root, client_id)

    atexit.register(_leave)
    _install_process_signals(_leave)

    if warm.get("ok"):
        _stderr(
            f"[scubiee] mcp attached host-agnostic client_id={client_id} "
            f"embedder_ready=1 prewarm={warm.get('prewarm_wait', {}).get('ms')}"
        )
    else:
        _stderr(
            f"[scubiee] mcp attach WARN embedder not ready: {warm}"
        )
    return {"client_id": client_id, "warm": warm}


def mcp_lifespan_factory(repo: Path | str):
    """FastMCP lifespan: stdin EOF / server stop → leave (universal close)."""
    from contextlib import asynccontextmanager

    root = Path(repo).resolve()

    @asynccontextmanager
    async def _lifespan(_server):  # noqa: ANN001
        # Warm should already have run in attach_mcp_session; re-gate if engine died.
        try:
            warm_engine_for_mcp(root, client_id=_CLIENT_ID)
        except Exception as exc:  # noqa: BLE001
            _stderr(f"[scubiee] lifespan re-warm: {exc}")
        try:
            yield {"repo": str(root), "client_id": _CLIENT_ID}
        finally:
            leave_mcp_client(root, _CLIENT_ID)

    return _lifespan
