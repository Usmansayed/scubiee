"""Universal MCP host connect / disconnect lifecycle (any IDE, any OS).

Contract (MCP spec + transport — not Cursor-specific):

**Open** — warm before any tools/call:
  - MCP worker process start / FastMCP lifespan setup
  - Every locate client build re-checks embedder ready (engine may have restarted)
  - Attach does **not** block Cursor on embedder warm — warm runs in background

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
import time
from pathlib import Path
from typing import Any

_CLIENT_ID: str | None = None
_REPO: Path | None = None
_ENSURE_READY_UNTIL = 0.0
_ENSURE_TTL_S = float(os.environ.get("CTX_MCP_ENSURE_TTL_S") or "20")
# Soft TTL must outlive Cursor "open → wait → first map" (often 20–60s idle).
_SOFT_READY_TTL_S = float(os.environ.get("CTX_MCP_SOFT_READY_TTL_S") or "300")
_SOFT_READY_UNTIL = 0.0
_SOFT_LAST_CHECK = 0.0
_LAST_SEARCH_PROBE_OK_AT = 0.0
_LEAVE_ONCE = threading.Lock()
_LEFT = False
_HEARTBEAT_STOP: threading.Event | None = None
_HEARTBEAT_THREAD: threading.Thread | None = None
_TRACE_PRELOAD_THREAD: threading.Thread | None = None
_LOCATE_PREWARM_LOCK = threading.Lock()
_LOCATE_PREWARM_THREAD: threading.Thread | None = None
_LOCATE_PREWARM_DONE = threading.Event()
_LOCATE_PREWARM_RESULT: dict[str, Any] = {}


def mark_soft_ready(*, ttl_s: float | None = None) -> None:
    """Remember soft binder is ready — skip health/open/register on next ensure."""
    global _SOFT_READY_UNTIL, _ENSURE_READY_UNTIL, _SOFT_LAST_CHECK
    ttl = max(
        1.0,
        float(ttl_s if ttl_s is not None else _SOFT_READY_TTL_S),
    )
    until = time.time() + ttl
    _SOFT_READY_UNTIL = until
    _ENSURE_READY_UNTIL = max(_ENSURE_READY_UNTIL, until)
    _SOFT_LAST_CHECK = time.time()


def clear_soft_ready() -> None:
    """Drop sticky soft TTL (engine flap / soft_search_ready false)."""
    global _SOFT_READY_UNTIL, _SOFT_LAST_CHECK
    _SOFT_READY_UNTIL = 0.0
    _SOFT_LAST_CHECK = 0.0


def soft_ready_cached() -> bool:
    return time.time() < _SOFT_READY_UNTIL


def soft_ready_needs_revalidate(*, interval_s: float = 2.0) -> bool:
    """True when soft TTL is set but we have not confirmed /health recently."""
    if not soft_ready_cached():
        return False
    return (time.time() - float(_SOFT_LAST_CHECK or 0.0)) >= max(0.5, float(interval_s))


def note_search_probe_ok() -> None:
    """Mark that locate-worker search HTTP path was exercised successfully."""
    global _LAST_SEARCH_PROBE_OK_AT
    _LAST_SEARCH_PROBE_OK_AT = time.time()


def search_probe_fresh(*, max_age_s: float = 12.0) -> bool:
    """True if a successful soft search probe ran recently in this process."""
    at = float(_LAST_SEARCH_PROBE_OK_AT or 0.0)
    if at <= 0.0:
        return False
    return (time.time() - at) < max(1.0, float(max_age_s))


def locate_worker_prewarm_done() -> bool:
    return _LOCATE_PREWARM_DONE.is_set()


def reset_locate_worker_prewarm() -> None:
    """Allow another locate-worker prewarm after an engine soft flap."""
    global _LOCATE_PREWARM_THREAD, _LOCATE_PREWARM_RESULT
    with _LOCATE_PREWARM_LOCK:
        t = _LOCATE_PREWARM_THREAD
        if t is not None and t.is_alive():
            return
        _LOCATE_PREWARM_DONE.clear()
        _LOCATE_PREWARM_RESULT = {}
        _LOCATE_PREWARM_THREAD = None


_AST_HYDRATE_LOCK = threading.Lock()
_AST_HYDRATE_THREAD: threading.Thread | None = None


def start_ast_hydrate_bg(repo: Path | str) -> dict[str, Any]:
    """Singleflight background AST bundle hydrate (expand/collect need it).

    Never call on the map request path — 50MB pickle IO GIL-starves search.
    """
    global _AST_HYDRATE_THREAD
    root = Path(repo).resolve()
    try:
        from pipeline.context_trace import ast_cache_ready

        if ast_cache_ready(root):
            return {"ok": True, "already": True}
    except Exception:  # noqa: BLE001
        pass
    with _AST_HYDRATE_LOCK:
        t = _AST_HYDRATE_THREAD
        if t is not None and t.is_alive():
            return {"ok": True, "running": True}

        def _run() -> None:
            try:
                from pipeline.context_trace import hydrate_ast_bundle

                hydrate_ast_bundle(root, bake_on_miss=False)
            except Exception as exc:  # noqa: BLE001
                _stderr(f"[scubiee] ast hydrate bg failed: {exc}")

        t = threading.Thread(target=_run, name="scubiee-ast-hydrate-bg", daemon=True)
        _AST_HYDRATE_THREAD = t
        t.start()
    return {"ok": True, "started": True}


def join_locate_worker_prewarm(*, timeout_s: float = 0.0) -> dict[str, Any]:
    """Wait for locate-worker prewarm (imports + soft probe). Empty if still pending."""
    if _LOCATE_PREWARM_DONE.wait(timeout=max(0.0, float(timeout_s))):
        return dict(_LOCATE_PREWARM_RESULT)
    return {"ok": False, "pending": True}


def _is_bridge_process() -> bool:
    return (os.environ.get("CTX_MCP_BRIDGE") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _preload_locate_imports() -> dict[str, Any]:
    """Import map/search deps in *this* process (must be mcp_locate, not bridge)."""
    t0 = time.perf_counter()
    try:
        import pipeline.context_agent.tools  # noqa: F401
        import pipeline.locate  # noqa: F401
        from pipeline.context_trace import (  # noqa: F401
            finalize_suggested_seed,
            pick_suggested_seed,
            pick_suggested_seeds,
        )
        from pipeline.map_result_cache import get_map_cached, put_map_cached  # noqa: F401

        return {"ok": True, "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": str(exc),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
        }


def prewarm_locate_worker(repo: Path | str, *, deadline_s: float | None = None) -> dict[str, Any]:
    """Make first map/pack ≤1s in this mcp_locate process after engine soft is up.

    Bridge must not call this (no FastEmbed/AST/locate imports in bridge).
    """
    global _LOCATE_PREWARM_RESULT
    t0 = time.perf_counter()
    root = Path(repo).resolve()
    out: dict[str, Any] = {"ok": False, "repo": str(root)}
    if _is_bridge_process():
        out["skipped"] = "bridge"
        _LOCATE_PREWARM_RESULT = out
        _LOCATE_PREWARM_DONE.set()
        return out

    imports = _preload_locate_imports()
    out["imports"] = imports

    try:
        from pipeline.runtime_controller import warm_deadline_ms

        budget = float(deadline_s) if deadline_s is not None else warm_deadline_ms() / 1000.0
    except Exception:  # noqa: BLE001
        budget = float(deadline_s) if deadline_s is not None else 30.0
    deadline = time.time() + max(5.0, budget)

    # Kick engine open/register without blocking on ORT.
    try:
        warm = warm_engine_for_mcp(
            root,
            client_id=_CLIENT_ID,
            blocking=False,
        )
        out["warm"] = {
            "ok": bool(warm.get("ok")),
            "soft_search_ready": warm.get("soft_search_ready"),
            "skipped": warm.get("skipped") or warm.get("ensure_skipped"),
        }
        if warm.get("soft_search_ready") or warm.get("skipped") == "soft_ttl":
            mark_soft_ready()
    except Exception as exc:  # noqa: BLE001
        out["warm_error"] = str(exc)

    soft = soft_ready_cached()
    from pipeline.client import EngineClient

    while time.time() < deadline and not soft:
        try:
            h = EngineClient(workspace_path=str(root), timeout=1.0).health() or {}
            soft = bool(h.get("soft_search_ready") and (h.get("ok") or h.get("service")))
            if soft:
                mark_soft_ready()
                out["health"] = {"soft_search_ready": True}
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.25)

    # Soft search probe — warms HTTP + binder path used by map→search_impl.
    # Prefer locate._search_hits (same path as map) — raw EngineClient.search
    # alone left first map paying a multi-second cold tax inside _search_hits.
    probe: dict[str, Any] = {"ok": False}
    if soft or soft_ready_cached():
        try:
            from pipeline.locate import _search_hits

            t_probe = time.perf_counter()
            hits = _search_hits(root, "scubiee locate worker prewarm", top_k=3)
            probe = {
                "ok": bool(hits),
                "n": len(hits or []),
                "elapsed_ms": round((time.perf_counter() - t_probe) * 1000, 1),
            }
            mark_soft_ready()
        except Exception as exc:  # noqa: BLE001
            try:
                probe = (
                    EngineClient(workspace_path=str(root), timeout=8.0).search(
                        "scubiee locate worker prewarm",
                        top_k=3,
                        path=str(root),
                    )
                    or {"ok": False}
                )
                mark_soft_ready()
            except Exception as exc2:  # noqa: BLE001
                probe = {"ok": False, "error": f"{exc}; fallback:{exc2}"}
    out["probe"] = {
        "ok": bool(probe.get("ok") or probe.get("results") or probe.get("hits") or probe.get("n")),
        "error": probe.get("error"),
        "elapsed_ms": probe.get("elapsed_ms"),
    }
    if out["probe"]["ok"]:
        note_search_probe_ok()

    # Full-warm availability: hydrate AST once here so first expand is <1s and
    # mid-session expand does not re-pay pickle + GIL. Keep resident while MCP up.
    ast_out: dict[str, Any] = {"ok": False, "skipped": True}
    if soft_ready_cached() or out["probe"]["ok"]:
        try:
            from pipeline.context_trace import hydrate_ast_bundle

            t_ast = time.perf_counter()
            hyd = hydrate_ast_bundle(root, bake_on_miss=False) or {}
            ast_out = {
                "ok": bool(hyd.get("ok")),
                "source": hyd.get("source"),
                "elapsed_ms": round((time.perf_counter() - t_ast) * 1000, 1),
            }
        except Exception as exc:  # noqa: BLE001
            ast_out = {"ok": False, "error": str(exc)}
    out["ast"] = ast_out

    # Kick engine dense prewarm (non-blocking) so embedder stays ready without
    # parking this locate worker on ORT load.
    embed_kick: dict[str, Any] = {"ok": False, "skipped": True}
    try:
        embed_kick = (
            EngineClient(workspace_path=str(root), timeout=2.0).post(
                "/v1/embed/prewarm",
                {"path": str(root), "wait": False},
            )
            or {"ok": False}
        )
    except Exception as exc:  # noqa: BLE001
        embed_kick = {"ok": False, "error": str(exc)}
    out["embed_prewarm"] = {
        "ok": bool(embed_kick.get("ok") or embed_kick.get("started") or embed_kick.get("async")),
        "error": embed_kick.get("error"),
    }

    out["ok"] = bool(soft_ready_cached() and imports.get("ok"))
    out["soft_ready"] = soft_ready_cached()
    out["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    _LOCATE_PREWARM_RESULT = out
    _LOCATE_PREWARM_DONE.set()
    _stderr(
        f"[scubiee] locate-worker prewarm ok={int(out['ok'])} "
        f"soft={int(bool(out.get('soft_ready')))} "
        f"imports_ms={(imports or {}).get('elapsed_ms')} "
        f"probe_ok={int(bool((out.get('probe') or {}).get('ok')))} "
        f"ast_ok={int(bool((out.get('ast') or {}).get('ok')))} "
        f"total_ms={out['elapsed_ms']}"
    )
    return out


def start_locate_worker_prewarm(repo: Path | str) -> dict[str, Any]:
    """Singleflight background prewarm for the mcp_locate worker process."""
    global _LOCATE_PREWARM_THREAD
    if _is_bridge_process():
        return {"ok": True, "skipped": "bridge"}
    if _LOCATE_PREWARM_DONE.is_set():
        result = dict(_LOCATE_PREWARM_RESULT or {})
        # Successful prior prewarm: refresh soft TTL and never reset on TTL alone
        # (reset→rejoin made every subsequent map pay ~2s).
        if result.get("ok"):
            if not soft_ready_cached():
                mark_soft_ready()
            return {"ok": True, "already": True, **result}
        with _LOCATE_PREWARM_LOCK:
            t = _LOCATE_PREWARM_THREAD
            if t is not None and t.is_alive():
                return {"ok": True, "started": False, "running": True}
        reset_locate_worker_prewarm()
    with _LOCATE_PREWARM_LOCK:
        t = _LOCATE_PREWARM_THREAD
        if t is not None and t.is_alive():
            return {"ok": True, "started": False, "running": True}
        root = Path(repo).resolve()

        def _run() -> None:
            try:
                prewarm_locate_worker(root)
            except Exception as exc:  # noqa: BLE001
                global _LOCATE_PREWARM_RESULT
                _LOCATE_PREWARM_RESULT = {"ok": False, "error": str(exc)}
                _LOCATE_PREWARM_DONE.set()
                _stderr(f"[scubiee] locate-worker prewarm failed: {exc}")

        t = threading.Thread(target=_run, name="scubiee-locate-prewarm", daemon=True)
        _LOCATE_PREWARM_THREAD = t
        t.start()
    return {"ok": True, "started": True}


def current_client_id() -> str | None:
    return _CLIENT_ID


def mcp_auto_warm_on_connect() -> bool:
    """Legacy sync connect-warm (default off). Prefer ``attach_warm_enabled``.

    Kept for hosts that set ``CTX_MCP_AUTO_WARM=1``. Default attach warm is
    ``RuntimeController.ensure(attach)`` via ``CTX_MCP_ATTACH_WARM`` (default on).
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

                client = EngineClient(workspace_path=str(repo), timeout=1.5)
                # Soft flap detector: sticky soft TTL must not survive engine
                # soft_search_ready=false (settle sim health flap → 3s first map).
                try:
                    h = client.health() or {}
                    soft = bool(
                        h.get("soft_search_ready") and (h.get("ok") or h.get("service"))
                    )
                    if soft:
                        mark_soft_ready()
                    elif soft_ready_cached():
                        clear_soft_ready()
                        reset_locate_worker_prewarm()
                        start_locate_worker_prewarm(repo)
                except Exception:  # noqa: BLE001
                    if soft_ready_cached():
                        clear_soft_ready()
                client.post(
                    "/v1/client/touch",
                    {"client_id": client_id, "pid": os.getpid(), "kind": "mcp"},
                )
                # Ensure engine-side keepalive loop is running; do not encode here
                # (avoids concurrent DML with map/pack on ThreadingHTTPServer).
                client.post(
                    "/v1/embed/keepalive",
                    {"path": str(repo), "ensure_loop": True, "tick": 0},
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
    if not blocking and now < _SOFT_READY_UNTIL:
        # Soft TTL can outlive a settle soft flap — cheap revalidate before skip.
        if soft_ready_needs_revalidate(interval_s=2.0):
            try:
                h = EngineClient(workspace_path=str(root), timeout=0.35).health() or {}
                soft = bool(h.get("soft_search_ready") and (h.get("ok") or h.get("service")))
            except Exception:  # noqa: BLE001
                soft = False
            if soft:
                mark_soft_ready()
            else:
                clear_soft_ready()
        if soft_ready_cached():
            out.update(
                {
                    "ok": True,
                    "soft_search_ready": True,
                    "deferred": False,
                    "skipped": "soft_ttl",
                }
            )
            return out
    skip_ensure = now < _ENSURE_READY_UNTIL
    try:
        skip_ensure = skip_ensure and is_running()
    except Exception:  # noqa: BLE001
        skip_ensure = False
    if skip_ensure:
        out["ensure_skipped"] = "ttl"
    else:
        try:
            health_wait = 20.0 if blocking else 0.0
            ensure_daemon(
                root,
                force_if_hung=False,
                spawn_owner="direct",
                wait_s=health_wait,
                open_wait=False,
            )
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
    # Attach / first-call nonblocking: keep HTTP short so Cursor never sits on
    # open_repo while /health is still coming up (cold spawn ~3s listen).
    timeout = 1.5 if not blocking else 180.0
    if wait_s is not None:
        timeout = max(1.0, float(wait_s))
    client = EngineClient(
        workspace_path=str(root),
        timeout=timeout,
        client=host,
        session_id=sid,
    )
    if not blocking:
        soft_now = False
        healthy_now = False
        try:
            h = client.health() or {}
            healthy_now = bool(h.get("ok") or h.get("service") or h.get("warm"))
            soft_now = bool(h.get("soft_search_ready"))
        except Exception:  # noqa: BLE001
            healthy_now = False
            soft_now = False
        if not healthy_now:
            # Engine spawn kicked (or still binding). Do not POST /v1/open —
            # that raced cold listen and burned ~8s+ of the MCP budget (R1).
            # Still hold-warm locally so the 10s sweeper cannot retire_self
            # before HTTP register succeeds.
            cid = (client_id or _CLIENT_ID or "").strip()
            if cid:
                try:
                    from pipeline.lifecycle_runtime import DESIRED_RUN, register_client, set_desired_mode

                    set_desired_mode(DESIRED_RUN)
                    local = register_client(
                        cid,
                        pid=os.getpid(),
                        kind="mcp",
                        host=host,
                    )
                    out["register"] = {"ok": True, "local": True, **local}
                except Exception as exc:  # noqa: BLE001
                    out["register_error"] = str(exc)
            out["ok"] = True
            out["deferred"] = True
            out["embedder_loaded"] = False
            out["warm_state"] = "warming"
            out["open_repo"] = {"ok": False, "status": "health_pending"}
            return out
        if soft_now:
            # Binder already ready — skip open; refresh client registration only.
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
                except Exception as exc:  # noqa: BLE001
                    out["register_error"] = str(exc)
            out["ok"] = True
            out["deferred"] = False
            out["soft_search_ready"] = True
            out["open_repo"] = {"ok": True, "status": "soft_ready", "skipped": True}
            mark_soft_ready()
            return out
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
        # Do not kick ORT here — races soft first-map. Explicit prewarm later.
        out["ok"] = True
        out["embedder_loaded"] = False
        out["deferred"] = True
        if out.get("open_repo", {}).get("ok"):
            mark_soft_ready()
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


_BG_WARM_LOCK = threading.Lock()
_BG_WARM_THREAD: threading.Thread | None = None
_ATTACH_WARM_LOCK = threading.Lock()
_ATTACH_WARM_THREAD: threading.Thread | None = None


def engine_warming_payload(*, warm_state: str = "warming") -> dict[str, Any]:
    from pipeline.engine import warming_response

    return warming_response(warm_state=warm_state)


def _kick_embed_prewarm(root: Path) -> dict[str, Any]:
    """Ask the engine process to load FastEmbed + run dummy encode."""
    try:
        from pipeline.client import EngineClient

        client = EngineClient(workspace_path=str(root), timeout=30.0)
        return client.post(
            "/v1/embed/prewarm",
            {"path": str(root), "wait": True, "sync": True},
        ) or {"ok": False, "error": "empty_prewarm"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _kick_ast_bundle_hydrate(root: Path, *, bake_on_miss: bool = False) -> dict[str, Any]:
    """Hydrate AST in this process (mcp_locate). Bundle-only on attach warm."""
    try:
        from pipeline.context_trace import hydrate_ast_bundle

        return hydrate_ast_bundle(root, bake_on_miss=bake_on_miss)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "source": "error"}


def _probe_engine_ready(root: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"healthy": False, "embedder_loaded": False}
    try:
        from pipeline.client import EngineClient

        client = EngineClient(workspace_path=str(root), timeout=1.5)
        try:
            health = client.health() or {}
        except Exception:  # noqa: BLE001
            health = {}
        if isinstance(health, dict) and health:
            out["healthy"] = bool(health.get("ok") or health.get("warm") or health.get("service"))
            if "embedder_loaded" in health:
                out["embedder_loaded"] = bool(health.get("embedder_loaded"))
        if not out["healthy"]:
            out["healthy"] = bool(client.healthy())
        if out["embedder_loaded"]:
            return out
        try:
            st = client.get("/v1/status") or {}
        except Exception:  # noqa: BLE001
            st = {}
        if isinstance(st, dict):
            if "embedder_loaded" in st:
                out["embedder_loaded"] = bool(st.get("embedder_loaded"))
            mem = st.get("memory") if isinstance(st.get("memory"), dict) else {}
            if "embedder_loaded" in mem:
                out["embedder_loaded"] = bool(mem.get("embedder_loaded"))
            pre = st.get("prewarm") if isinstance(st.get("prewarm"), dict) else {}
            if pre.get("embedder_loaded") or pre.get("done") or pre.get("already_warm"):
                out["embedder_loaded"] = True
            eng = st.get("engine") if isinstance(st.get("engine"), dict) else {}
            if "embedder_loaded" in eng:
                out["embedder_loaded"] = bool(eng.get("embedder_loaded"))
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
    return out


def _attach_warm_coordinator(root: Path) -> None:
    """Wait for /health, then warm embedder; hydrate AST only in mcp_locate."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from pipeline.warm_contract import (
        set_ast_hydrated,
        set_warm_phase,
        warm_deadline_ms,
        warm_started_at,
    )

    is_bridge = (os.environ.get("CTX_MCP_BRIDGE") or "").strip() in {"1", "true", "yes", "on"}
    set_warm_phase("waiting_health")
    deadline = (warm_started_at() or time.time()) + warm_deadline_ms() / 1000.0
    healthy = False
    while time.time() < deadline:
        probe = _probe_engine_ready(root)
        if probe.get("healthy"):
            healthy = True
            break
        time.sleep(0.2)
    if not healthy:
        set_warm_phase("health_timeout", error="engine_health_timeout")
        _stderr("[scubiee] attach warm: engine /health not up before deadline")
        return

    # Re-register after health if earlier HTTP register deferred.
    try:
        from pipeline.client import EngineClient
        from pipeline.session_isolation import mcp_client_name

        cid = (_CLIENT_ID or "").strip()
        if cid:
            EngineClient(workspace_path=str(root), timeout=3.0).post(
                "/v1/client/register",
                {
                    "client_id": cid,
                    "pid": os.getpid(),
                    "kind": "bridge" if is_bridge else "mcp",
                    "client": mcp_client_name(),
                },
            )
    except Exception:  # noqa: BLE001
        pass

    set_warm_phase("parallel_warm")
    embed_out: dict[str, Any] = {}
    ast_out: dict[str, Any] = {"ok": True, "source": "skipped_bridge"} if is_bridge else {}

    if is_bridge:
        # Bridge must not load AST/FastEmbed locally — only kick engine embed.
        embed_out = _kick_embed_prewarm(root)
    else:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futs = {
                pool.submit(_kick_embed_prewarm, root): "embed",
                pool.submit(_kick_ast_bundle_hydrate, root, bake_on_miss=False): "ast",
            }
            for fut in as_completed(futs):
                kind = futs[fut]
                try:
                    result = fut.result() or {}
                except Exception as exc:  # noqa: BLE001
                    result = {"ok": False, "error": str(exc)}
                if kind == "embed":
                    embed_out = result
                else:
                    ast_out = result

        if ast_out.get("ok"):
            set_ast_hydrated(True, source=str(ast_out.get("source") or "bundle"))
        else:
            set_ast_hydrated(False, source=str(ast_out.get("source") or "miss"))
            try:
                threading.Thread(
                    target=lambda: _kick_ast_bundle_hydrate(root, bake_on_miss=True),
                    name="scubiee-ast-bake",
                    daemon=True,
                ).start()
            except Exception:  # noqa: BLE001
                pass

    emb_ok = bool(
        embed_out.get("ok")
        or embed_out.get("embedder_loaded")
        or embed_out.get("already_warm")
    )
    if emb_ok and healthy:
        set_warm_phase("ready")
    else:
        set_warm_phase(
            "partial",
            error=str(embed_out.get("error") or ast_out.get("error") or "partial_warm"),
        )
    _stderr(
        f"[scubiee] attach warm done bridge={int(is_bridge)} emb_ok={int(emb_ok)} "
        f"ast={ast_out.get('source')} emb_err={embed_out.get('error')}"
    )


def start_attach_warm_pipeline(repo: Path | str) -> dict[str, Any]:
    """Kick cold warm at MCP attach (any host/OS). Delegates to RuntimeController."""
    from pipeline.runtime_controller import RuntimeController, attach_warm_enabled, warm_deadline_ms

    root = Path(repo).resolve()
    if not attach_warm_enabled():
        return {"ok": True, "started": False, "skipped": "CTX_MCP_ATTACH_WARM=0"}
    snap = RuntimeController.get().ensure(root, "attach")
    return {
        "ok": True,
        "started": True,
        "deadline_ms": warm_deadline_ms(),
        "runtime_state": snap.state,
        "warm_ready": snap.warm_ready,
    }


def join_attach_warm_if_needed(
    repo: Path | str,
    *,
    need_ast: bool = False,
) -> dict[str, Any] | None:
    """Join remaining warm budget. None = ready; else warming payload."""
    from pipeline.runtime_controller import RuntimeController, attach_warm_enabled

    if not attach_warm_enabled():
        return None
    snap = RuntimeController.get().ensure(Path(repo), "serve", need_ast=need_ast)
    if snap.warm_ready and (not need_ast or snap.ast_ready):
        return None
    return engine_warming_payload()


def _spawn_background_warm(root: Path, client_id: str) -> None:
    """Singleflight soft open/register — never block on ORT prewarm."""
    global _BG_WARM_THREAD
    with _BG_WARM_LOCK:
        t = _BG_WARM_THREAD
        if t is not None and t.is_alive():
            return

        def _run() -> None:
            try:
                # blocking=False: open+register only; ORT deferred until after soft map.
                warm_engine_for_mcp(root, client_id=client_id, blocking=False)
            except Exception as exc:  # noqa: BLE001
                _stderr(f"[scubiee] background warm failed: {exc}")

        t = threading.Thread(target=_run, name="scubiee-mcp-warm", daemon=True)
        _BG_WARM_THREAD = t
        t.start()


def _heartbeat_alive() -> bool:
    t = _HEARTBEAT_THREAD
    return t is not None and t.is_alive()


def ensure_mcp_runtime(
    repo: Path | str,
    *,
    client_id: str | None = None,
    blocking: bool = False,
) -> dict[str, Any]:
    """Agent first-call warm: spawn engine, return immediately unless blocking.

    MCP stdio attach does not call this unless CTX_MCP_AUTO_WARM=1.
    Locate tools must use blocking=False so Cursor's ~60s MCP timeout never
    sits on open_repo/index/FastEmbed. Background thread finishes embedder.
    """
    root = Path(repo).resolve()
    if _CLIENT_ID is None:
        attach_mcp_session(root)
    cid = (client_id or _CLIENT_ID or "").strip()
    out = warm_engine_for_mcp(root, client_id=cid or None, blocking=blocking)
    if not blocking:
        _spawn_background_warm(root, cid)
    if cid and not _heartbeat_alive():
        _start_heartbeat(root, cid)
    # Do NOT kick AST hydrate here — it GIL-starves the first map/pack in this
    # process for several seconds. Pack/expand join_attach(need_ast=True) hydrates.
    try:
        raw = (os.environ.get("CTX_MCP_TRACE_PRELOAD") or "").strip().lower()
        if raw in {"1", "true", "yes", "on"}:
            spawn_trace_graph_preload(root)
    except Exception as exc:  # noqa: BLE001
        _stderr(f"[scubiee] trace hydrate kick: {exc}")
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
        # Engine may already be down — still clear local registry so orphans
        # do not keep a later engine warm forever.
        _stderr(f"[scubiee] mcp leave HTTP failed: {exc}; local unregister")
        try:
            from pipeline.lifecycle_runtime import (
                apply_idle_policy,
                unregister_client,
            )

            local = unregister_client(cid)
            idle = apply_idle_policy()
            return {"ok": True, "local": True, **local, "idle": idle}
        except Exception as exc2:  # noqa: BLE001
            _stderr(f"[scubiee] mcp leave local failed: {exc2}")
            return {"ok": False, "error": str(exc), "local_error": str(exc2)}


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
    # Prefer RuntimeController attach (default on) over legacy AUTO_WARM-only path.
    try:
        from pipeline.runtime_controller import RuntimeController, attach_warm_enabled

        if attach_warm_enabled():
            snap = RuntimeController.get().ensure(root, "attach", client_id=client_id)
            warm = {
                "ok": True,
                "deferred": not snap.warm_ready,
                "attach_warm": {
                    "started": True,
                    "runtime_state": snap.state,
                    "warm_ready": snap.warm_ready,
                },
            }
            started = True
            if client_id and not _heartbeat_alive():
                _start_heartbeat(root, client_id)
        elif auto:
            warm = warm_engine_for_mcp(root, client_id=client_id, blocking=False)
            _spawn_background_warm(root, client_id)
            _start_heartbeat(root, client_id)
            started = True
        else:
            warm = {"ok": True, "deferred": True, "skipped": "agent_warm"}
            started = False
    except Exception as exc:  # noqa: BLE001
        _stderr(f"[scubiee] attach warm kick failed: {exc}")
        warm = {"ok": True, "deferred": True, "skipped": "agent_warm", "error": str(exc)}
        started = False

    def _leave() -> None:
        leave_mcp_client(root, client_id)
        try:
            from pipeline.runtime_controller import RuntimeController

            RuntimeController.get().ensure(root, "leave")
        except Exception:  # noqa: BLE001
            pass


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
