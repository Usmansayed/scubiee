"""Universal MCP host connect / disconnect lifecycle (any IDE, any OS).

Contract (MCP spec + transport — not Cursor-specific):

**Open** — warm before any tools/call:
  - MCP worker process start / FastMCP lifespan setup
  - Every locate client build re-checks embedder ready (engine may have restarted)
  - Attach does **not** block Cursor on embedder warm — warm runs in background

**Close** — unload by stopping the engine process (ORT does not free RSS in-process):
  - stdin EOF → FastMCP lifespan cleanup (portable primary signal)
  - atexit + SIGTERM/SIGINT/SIGBREAK(Windows)/SIGHUP(Unix)
  - daemon stamps ``last_client_left_at``; after ``CTX_DISCONNECT_DEBOUNCE_S`` (120s)
    idle sweeper ``enter_standby(stop_engine=True)`` exits the engine process

Hosts (Cursor, Claude Code, Codex, Kiro, Copilot, Zed, Continue, …) all speak
stdio MCP the same way. Do not special-case Cursor.
"""

from __future__ import annotations

import atexit
import os
import signal
import threading
import time
from pathlib import Path
from typing import Any

_CLIENT_ID: str | None = None
_REPO: Path | None = None
_ENSURE_READY_UNTIL = 0.0
_ENSURE_TTL_S = float(os.environ.get("CTX_MCP_ENSURE_TTL_S") or "20")
_LEAVE_ONCE = threading.Lock()
_LEFT = False
_HEARTBEAT_STOP: threading.Event | None = None
_HEARTBEAT_THREAD: threading.Thread | None = None
_TRACE_PRELOAD_THREAD: threading.Thread | None = None


def current_client_id() -> str | None:
    return _CLIENT_ID


def mcp_auto_warm_on_connect() -> bool:
    """True when MCP stdio start should spawn engine/watchdog/embedder.

    Default is off: Cursor/Claude/Codex reconnects must not WMI-spawn the
    engine. The agent warms on the first gate/status/map call instead.
    Set CTX_MCP_AUTO_WARM=1 to restore connect-time auto warm.
    """
    raw = (os.environ.get("CTX_MCP_AUTO_WARM") or "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


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
    blocking: bool = True,
) -> dict[str, Any]:
    """Ensure daemon + repo open + FastEmbed loaded.

    ``blocking=False`` (MCP attach): start/ensure + register only — never wait on
    embedder prewarm. Cursor must advertise tools immediately; map/pack warm on demand.

    Ensure is coalesced for ``CTX_MCP_ENSURE_TTL_S`` (default 20s) while the
    engine stays healthy so every tool call does not re-enter spawn.

    Agent warm uses ``spawn_owner=direct`` so the first gate/status/map call
    starts the engine immediately. Watchdog does not cold-start it.
    Disconnect unload (leave → unregister → idle sweeper) is unchanged.
    """
    global _ENSURE_READY_UNTIL
    from pipeline.client import EngineClient
    from pipeline.daemon import ensure_daemon, is_running
    from pipeline.session_isolation import effective_session_id, mcp_client_name

    root = Path(repo).resolve()
    out: dict[str, Any] = {"ok": False, "repo": str(root), "blocking": bool(blocking)}
    now = time.time()
    skip_ensure = now < _ENSURE_READY_UNTIL
    try:
        skip_ensure = skip_ensure and is_running()
    except Exception:  # noqa: BLE001
        skip_ensure = False
    if skip_ensure:
        out["ensure_skipped"] = "ttl"
    else:
        try:
            ensure_daemon(root, force_if_hung=False, spawn_owner="direct")
            try:
                if is_running():
                    _ENSURE_READY_UNTIL = time.time() + max(1.0, _ENSURE_TTL_S)
            except Exception:  # noqa: BLE001
                pass
        except Exception as exc:  # noqa: BLE001
            out["ensure_daemon_error"] = str(exc)
            return out

    host = mcp_client_name()
    sid = effective_session_id(None)
    # Attach path uses a short timeout so Cursor is not stuck in "loading".
    timeout = 8.0 if not blocking else 180.0
    if wait_s is not None:
        timeout = max(1.0, float(wait_s))
    client = EngineClient(
        workspace_path=str(root),
        timeout=timeout,
        client=host,
        session_id=sid,
    )
    try:
        opened = client.open_repo(str(root), wait=bool(blocking))
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

    if not blocking:
        # Fire-and-forget embedder warm — tools are already callable.
        try:
            client.post(
                "/v1/embed/prewarm",
                {"path": str(root), "wait": False, "sync": False},
            )
        except Exception as exc:  # noqa: BLE001
            out["prewarm_async_error"] = str(exc)
        out["ok"] = True
        out["embedder_loaded"] = False
        out["deferred"] = True
        return out

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


def _spawn_background_warm(root: Path, client_id: str) -> None:
    def _run() -> None:
        try:
            warm_engine_for_mcp(root, client_id=client_id, blocking=True)
        except Exception as exc:  # noqa: BLE001
            _stderr(f"[scubiee] background warm failed: {exc}")

    threading.Thread(target=_run, name="scubiee-mcp-warm", daemon=True).start()


def _heartbeat_alive() -> bool:
    t = _HEARTBEAT_THREAD
    return t is not None and t.is_alive()


def ensure_mcp_runtime(
    repo: Path | str,
    *,
    client_id: str | None = None,
    blocking: bool = True,
) -> dict[str, Any]:
    """Agent first-call warm: engine + register + embedder. Idempotent.

    MCP stdio attach does not call this unless CTX_MCP_AUTO_WARM=1.
    """
    root = Path(repo).resolve()
    if _CLIENT_ID is None:
        attach_mcp_session(root)
    cid = (client_id or _CLIENT_ID or "").strip()
    out = warm_engine_for_mcp(root, client_id=cid or None, blocking=blocking)
    if cid and not _heartbeat_alive():
        _start_heartbeat(root, cid)
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

    Default (CTX_MCP_AUTO_WARM unset/0): leave hooks only — no engine spawn.
    CTX_MCP_AUTO_WARM=1: ensure + register without blocking Cursor on embedder.
    """
    global _CLIENT_ID, _REPO, _LEFT
    from pipeline.session_isolation import default_process_session_id

    root = Path(repo).resolve()
    _REPO = root
    _LEFT = False
    client_id = f"mcp:{default_process_session_id()}"
    _CLIENT_ID = client_id

    auto = mcp_auto_warm_on_connect()
    if auto:
        # Fast path: ensure + register only (no embedder wait).
        warm = warm_engine_for_mcp(root, client_id=client_id, blocking=False)
        _spawn_background_warm(root, client_id)
        _start_heartbeat(root, client_id)
        started = True
    else:
        # Agent-warm: stdio only. No watchdog/engine/embedder until gate/map.
        warm = {"ok": True, "deferred": True, "skipped": "agent_warm"}
        started = False

    def _leave() -> None:
        leave_mcp_client(root, client_id)

    atexit.register(_leave)
    _install_process_signals(_leave)

    _stderr(
        f"[scubiee] mcp attached host-agnostic client_id={client_id} "
        f"warm_started={int(started)} deferred={warm.get('deferred')} "
        f"auto_warm={int(auto)} "
        f"open={((warm.get('open_repo') or {}).get('warm_state'))}"
    )
    return {
        "client_id": client_id,
        "warm": warm,
        "warm_started": started,
        "auto_warm": auto,
    }


def mcp_lifespan_factory(repo: Path | str):
    """FastMCP lifespan: stdin EOF / server stop → leave (universal close)."""
    from contextlib import asynccontextmanager

    root = Path(repo).resolve()

    @asynccontextmanager
    async def _lifespan(_server):  # noqa: ANN001
        # Do not block transport on warm — background thread is enough.
        # Lazy mode: do not spawn engine from lifespan (host reconnect storms).
        try:
            if _CLIENT_ID and mcp_auto_warm_on_connect():
                _spawn_background_warm(root, _CLIENT_ID)
        except Exception as exc:  # noqa: BLE001
            _stderr(f"[scubiee] lifespan warm kick: {exc}")
        try:
            yield {"repo": str(root), "client_id": _CLIENT_ID}
        finally:
            leave_mcp_client(root, _CLIENT_ID)

    return _lifespan
