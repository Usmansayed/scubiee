"""Context Engine HTTP daemon — single backend for MCP, CLI, dashboard."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "packages") not in sys.path:
    sys.path.insert(0, str(ROOT / "packages"))

from pipeline.ce_service import get_context_engine

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def _note_user_activity() -> None:
    try:
        from pipeline.lifecycle_runtime import note_activity

        note_activity()
    except Exception:  # noqa: BLE001
        pass


# HTTP paths that must not refresh idle clocks (background polls / health).
_PASSIVE_GET_PATHS = frozenset({"/health", "/", "/dashboard"})
_PASSIVE_GET_PREFIXES = ("/api/settings", "/v1/settings", "/status", "/v1/status", "/v1/resources")
_PASSIVE_POST_PATHS = frozenset({"/v1/shutdown", "/shutdown", "/v1/status", "/status"})


def _is_passive_http_path(path: str, *, method: str) -> bool:
    if method == "GET":
        if path in _PASSIVE_GET_PATHS:
            return True
        return any(path.startswith(prefix) for prefix in _PASSIVE_GET_PREFIXES)
    if method == "POST":
        return path in _PASSIVE_POST_PATHS
    return False


def _json(handler: BaseHTTPRequestHandler, code: int, payload: dict) -> None:
    context = getattr(handler, "_request_context", None)
    if isinstance(context, dict):
        payload.setdefault("client", context.get("client"))
        payload.setdefault("session_id", context.get("session_id"))
        payload.setdefault("session_authored", bool(context.get("session_id")))
    body = json.dumps(payload, default=str).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length") or 0)
    raw = handler.rfile.read(length) if length else b"{}"
    try:
        data = json.loads(raw.decode("utf-8") or "{}")
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        ce = get_context_engine()

        if path in ("/health", "/"):
            _json(self, 200, ce.health())
            return
        if not _is_passive_http_path(path, method="GET"):
            _note_user_activity()
        if path == "/dashboard":
            from pipeline.dashboard import DASHBOARD_HTML

            body = DASHBOARD_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path in ("/api/settings", "/v1/settings"):
            _json(self, 200, ce.get_settings())
            return
        if path in ("/status", "/v1/status"):
            _json(self, 200, ce.status())
            return
        if path == "/v1/resources":
            try:
                from pipeline.resources import get_resource_manager

                _json(self, 200, get_resource_manager().status())
            except Exception as exc:  # noqa: BLE001
                _json(self, 500, {"ok": False, "error": str(exc)})
            return
        _json(self, 404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if not _is_passive_http_path(path, method="POST"):
            _note_user_activity()
        data = _read_json(self)
        ce = get_context_engine()

        def admit(root: str, *, intentional: bool = False) -> dict:
            """Admit a workspace for an HTTP request.

            ``intentional=True`` (map/search/sync and other agent ops) bypasses
            passive ``large_repo`` auto-pause. Engine restarts clear the in-memory
            hub; without this, enrolled repos falsely re-pause and force
            ``scubiee activate`` + cold re-warm between MCP calls.
            """
            admission = getattr(ce, "admit_request", None)
            if admission is None:
                return {
                    "ok": True,
                    "status": "activated",
                    "client": data.get("client"),
                    "session_id": data.get("session_id"),
                }
            return admission(
                root,
                client=data.get("client"),
                session_id=data.get("session_id"),
                metadata=(
                    data.get("metadata")
                    if isinstance(data.get("metadata"), dict)
                    else None
                ),
                explicit=bool(data.get("explicit") or data.get("wait") or intentional),
                wait=bool(data.get("wait")),
            )

        if path in ("/api/settings", "/v1/settings"):
            _json(self, 200, ce.update_settings(data))
            return

        if path == "/v1/open":
            root = data.get("path")
            if not root:
                _json(self, 400, {"ok": False, "error": "workspace path required"})
                return
            # Always intentional: enrolled MCP/IDE opens must not false-pause on
            # large_repo after engine hub restart (soft_search_ready stuck false).
            admission = admit(root, intentional=True)
            self._request_context = admission
            _json(self, 200 if admission.get("status") == "activated" else 409, admission)
            return

        if path == "/v1/register":
            _json(
                self,
                200,
                ce.register(
                    data.get("path") or None,
                    always_allow=bool(data.get("always_allow")),
                    index=data.get("index", True) is not False,
                ),
            )
            return

        if path == "/v1/client/register":
            from pipeline.lifecycle_runtime import register_client

            client_id = str(data.get("client_id") or "").strip()
            if not client_id:
                _json(self, 400, {"ok": False, "error": "client_id required"})
                return
            pid_raw = data.get("pid")
            try:
                pid = int(pid_raw) if pid_raw is not None else None
            except (TypeError, ValueError):
                pid = None
            _json(
                self,
                200,
                register_client(
                    client_id,
                    pid=pid,
                    kind=str(data.get("kind") or "mcp"),
                    host=str(data.get("client") or data.get("host") or "") or None,
                ),
            )
            return

        if path == "/v1/client/unregister":
            from pipeline.lifecycle_runtime import apply_idle_policy, unregister_client

            client_id = str(data.get("client_id") or "").strip()
            if not client_id:
                _json(self, 400, {"ok": False, "error": "client_id required"})
                return
            result = unregister_client(client_id)
            idle = apply_idle_policy()
            _json(self, 200, {**result, "idle": idle})
            return

        if path == "/v1/client/reconcile":
            from pipeline.lifecycle_runtime import apply_idle_policy, reconcile_clients

            remaining = reconcile_clients()
            idle = apply_idle_policy()
            _json(
                self,
                200,
                {
                    "ok": True,
                    "active_clients": len(remaining),
                    "idle": idle,
                },
            )
            return

        if path == "/v1/client/touch":
            from pipeline.lifecycle_runtime import note_activity, register_client, touch_client

            client_id = str(data.get("client_id") or "").strip()
            if not client_id:
                _json(self, 400, {"ok": False, "error": "client_id required"})
                return
            if touch_client(client_id):
                note_activity()
                # Re-arm keepalive — but do NOT re-kick ORT or spam ensure_loop
                # while dense prewarm holds the GIL (Cursor touch storms).
                try:
                    from pipeline.engine import (
                        embedder_is_loaded,
                        ensure_embed_keepalive_loop,
                        prewarm_busy_stamp_active,
                        prewarm_embedder_async,
                    )

                    root = data.get("path") or data.get("root") or None
                    if prewarm_busy_stamp_active(max_age_s=180.0):
                        pass  # quiet — stamp alone holds idle stop + watchdog
                    else:
                        ensure_embed_keepalive_loop(root)
                        if not embedder_is_loaded():
                            prewarm_embedder_async(root)
                except Exception:  # noqa: BLE001
                    pass
                _json(self, 200, {"ok": True, "client_id": client_id, "touched": True})
                return
            pid_raw = data.get("pid")
            try:
                pid = int(pid_raw) if pid_raw is not None else None
            except (TypeError, ValueError):
                pid = None
            _json(
                self,
                200,
                {
                    **register_client(
                        client_id,
                        pid=pid,
                        kind=str(data.get("kind") or "mcp"),
                    ),
                    "touched": False,
                    "reregistered": True,
                },
            )
            return

        if path in {"/v1/embed/prewarm", "/v1/prewarm"}:
            from pipeline.engine import (
                embedder_is_loaded,
                prewarm_embedder_async,
                prewarm_status,
            )

            root = data.get("path") or data.get("root") or None
            if embedder_is_loaded():
                st = prewarm_status()
                _json(
                    self,
                    200,
                    {"ok": True, "already_warm": True, **st},
                )
                return
            # Never run ORT on this HTTP worker and never poll /health-adjacent
            # status in a loop — that parked ThreadingHTTPServer behind GIL.
            kicked = prewarm_embedder_async(root)
            _json(
                self,
                200,
                {
                    "ok": True,
                    "warming": True,
                    "async": True,
                    "should_retry": True,
                    **prewarm_status(),
                    "kick": kicked,
                    "hint": "Embedder loading in background; retry map after dense.",
                },
            )
            return

        if path in {"/v1/embed/keepalive", "/v1/keepalive"}:
            from pipeline.engine import embed_keepalive, embed_keepalive_status, ensure_embed_keepalive_loop

            root = data.get("path") or data.get("root") or None
            raw_kick = data.get("ensure_loop", data.get("start_loop", True))
            if isinstance(raw_kick, bool):
                kick = raw_kick
            else:
                kick = str(raw_kick).strip().lower() not in {"0", "false", "no", "off", ""}
            if kick:
                ensure_embed_keepalive_loop(root)
            # Default tick=0: HTTP must not block on DML encode (ThreadingHTTPServer).
            # The background loop performs dummy encodes; pass tick=1 to force one now.
            tick_raw = data.get("tick", 0)
            if str(tick_raw).strip().lower() in {"0", "false", "no", "off", ""}:
                _json(self, 200, {"ok": True, "tick": False, "status": embed_keepalive_status()})
                return
            out = embed_keepalive(root)
            out["status"] = embed_keepalive_status()
            _json(self, 200, out)
            return

        if path == "/v1/lifecycle":
            from pipeline import repo_lifecycle as lifecycle

            action = str(data.get("action") or "").strip().lower()
            root = data.get("path")
            if action == "list":
                _json(
                    self,
                    200,
                    {"ok": True, "repositories": lifecycle.list_managed_repos()},
                )
                return
            if not root:
                _json(self, 400, {"ok": False, "error": "workspace path required"})
                return
            handlers = {
                "initialize": lambda: lifecycle.initialize_repo(
                    Path(root),
                    index=data.get("index", True) is not False,
                    always_allow=data.get("always_allow", True) is not False,
                    confirm=bool(data.get("confirm")),
                ),
                "activate": lambda: lifecycle.activate_repo(Path(root)),
                "pause": lambda: lifecycle.pause_repo(
                    Path(root), reason=data.get("reason")
                ),
                "resume": lambda: lifecycle.resume_repo(Path(root)),
                "sync-now": lambda: lifecycle.sync_now_repo(
                    Path(root), confirm=bool(data.get("confirm"))
                ),
                "sync_now": lambda: lifecycle.sync_now_repo(
                    Path(root), confirm=bool(data.get("confirm"))
                ),
                "rebuild": lambda: lifecycle.rebuild_repo(Path(root)),
                "remove": lambda: lifecycle.remove_repo(
                    Path(root), delete_store=bool(data.get("delete_store"))
                ),
                "never-index": lambda: lifecycle.never_index_repo(
                    Path(root), reason=data.get("reason")
                ),
                "never_index": lambda: lifecycle.never_index_repo(
                    Path(root), reason=data.get("reason")
                ),
            }
            handler = handlers.get(action)
            if handler is None:
                _json(
                    self,
                    400,
                    {
                        "ok": False,
                        "error": "valid lifecycle action required",
                        "actions": sorted(handlers),
                    },
                )
                return
            _json(self, 200, handler())
            return

        if path in ("/v1/status", "/status"):
            root = data.get("path")
            if not root:
                _json(self, 400, {"ok": False, "error": "workspace path required"})
                return
            status = ce.status(root)
            _json(self, 200, status)
            return

        if path == "/v1/session/end":
            root = data.get("path")
            session_id = str(data.get("session_id") or "")
            if not root or not session_id:
                _json(
                    self,
                    400,
                    {"ok": False, "error": "workspace path and session_id required"},
                )
                return
            self._request_context = {
                "client": data.get("client"),
                "session_id": session_id,
            }
            _json(self, 200, ce.end_session(root, session_id))
            return

        operational = {
            "/v1/dirty",
            "/v1/note_locate",
            "/v1/search",
            "/search",
            "/v1/locate",
            "/v1/sync",
            "/sync",
            "/v1/publish",
            "/v1/grep",
            "/v1/outline",
            "/v1/read_span",
            "/v1/follow_imports",
            "/v1/graph_neighbors",
            "/v1/query_graph",
            "/v1/grep_ident",
            "/v1/reopen_anchors",
            "/v1/session_anchors",
            "/reload",
        }
        if path in operational:
            root = data.get("repo") or data.get("root") or data.get("path")
            if not root:
                _json(self, 400, {"ok": False, "error": "workspace path required"})
                return
            admission = admit(root, intentional=True)
            self._request_context = admission
            if admission.get("status") != "activated":
                _json(self, 409, admission)
                return

        if path == "/v1/dirty":
            paths = data.get("paths")
            if not isinstance(paths, list) or not paths:
                _json(self, 400, {"ok": False, "error": "paths list required"})
                return
            _json(
                self,
                200,
                ce.mark_dirty([str(item) for item in paths], reason=str(data.get("reason") or "changed_file")),
            )
            return

        if path == "/v1/note_locate":
            _json(self, 200, ce.note_locate())
            return

        if path in ("/v1/search", "/search"):
            query = str(data.get("query") or "").strip()
            if not query:
                _json(self, 400, {"error": "query required"})
                return
            _json(
                self,
                200,
                ce.search(
                    query,
                    top_k=int(data.get("top_k") or 8),
                    root=data.get("path") or None,
                ),
            )
            return

        if path == "/v1/locate":
            query = str(data.get("query") or "").strip()
            if not query:
                _json(self, 400, {"error": "query required"})
                return
            _json(
                self,
                200,
                ce.locate(
                    query,
                    top_k=int(data.get("top_k") or 5),
                    root=data.get("path") or None,
                ),
            )
            return

        if path in ("/v1/sync", "/sync"):
            # Do not freshness-walk or embed on this thread. The keeper poll
            # marks indexed dirty files and drain_due publishes them after
            # the 1s debounce.
            loop = ce.sync_loop
            if loop is not None:
                loop.request_poll()
            _json(
                self,
                200,
                {
                    "ok": loop is not None,
                    "strategy": "deferred",
                    "refreshed": False,
                    "debounce_ms": 1000,
                    "error": None if loop is not None else "keeper not running",
                },
            )
            return

        if path == "/v1/publish":
            payload = data.get("payload")
            if payload is not None and not isinstance(payload, dict):
                payload = None
            _json(
                self,
                200,
                ce.publish(data.get("path") or None, payload=payload),
            )
            return

        if path == "/v1/grep":
            pattern = str(data.get("pattern") or "")
            if not pattern:
                _json(self, 400, {"error": "pattern required"})
                return
            _json(
                self,
                200,
                ce.grep(
                    pattern,
                    glob=str(data.get("glob") or "**/*"),
                    max_hits=int(data.get("max_hits") or 200),
                    root=data.get("path") or None,
                ),
            )
            return

        if path == "/v1/outline":
            file_path = str(data.get("file") or data.get("path") or "")
            if not file_path:
                _json(self, 400, {"error": "file required"})
                return
            # if "path" was repo root, prefer "file"
            repo = data.get("repo") or data.get("root")
            _json(self, 200, ce.outline(file_path, root=repo))
            return

        if path == "/v1/read_span":
            file_path = str(data.get("file") or data.get("path") or "")
            if not file_path:
                _json(self, 400, {"error": "file required"})
                return
            _json(
                self,
                200,
                ce.read_span(
                    file_path,
                    start_line=data.get("start_line"),
                    end_line=data.get("end_line"),
                    max_chars=int(data.get("max_chars") or 700),
                    avoid=data.get("avoid"),
                    root=data.get("repo") or data.get("root"),
                ),
            )
            return

        if path == "/v1/follow_imports":
            file_path = str(data.get("file") or data.get("path") or "")
            if not file_path:
                _json(self, 400, {"error": "file required"})
                return
            _json(
                self,
                200,
                ce.follow_imports(
                    file_path,
                    query=str(data.get("query") or ""),
                    keep=int(data.get("keep") or 6),
                    max_chars=int(data.get("max_chars") or 500),
                    avoid=data.get("avoid"),
                    root=data.get("repo") or data.get("root"),
                ),
            )
            return

        if path == "/v1/graph_neighbors":
            paths = data.get("paths") or data.get("files") or []
            if isinstance(paths, str):
                paths = [paths]
            if not paths:
                one = str(data.get("file") or data.get("path") or "")
                if one:
                    paths = [one]
            if not paths:
                _json(self, 400, {"error": "paths required"})
                return
            _json(
                self,
                200,
                ce.graph_neighbors(
                    list(paths),
                    query=str(data.get("query") or ""),
                    cap=int(data.get("cap") or 16),
                    keep=int(data.get("keep") or 4),
                    max_chars=int(data.get("max_chars") or 500),
                    avoid=data.get("avoid"),
                    root=data.get("repo") or data.get("root"),
                ),
            )
            return

        if path == "/v1/query_graph":
            question = str(data.get("question") or data.get("query") or "").strip()
            if not question:
                _json(self, 400, {"error": "question required"})
                return
            _json(
                self,
                200,
                ce.query_graph(
                    question,
                    keep=int(data.get("keep") or 6),
                    neighbor_keep=int(data.get("neighbor_keep") or 4),
                    max_chars=int(data.get("max_chars") or 400),
                    avoid=data.get("avoid"),
                    root=data.get("repo") or data.get("root"),
                ),
            )
            return

        if path == "/v1/grep_ident":
            ident = str(data.get("ident") or data.get("symbol") or "").strip()
            if not ident:
                _json(self, 400, {"error": "ident required"})
                return
            _json(
                self,
                200,
                ce.grep_ident(
                    ident,
                    max_hits=int(data.get("max_hits") or 12),
                    max_chars=int(data.get("max_chars") or 500),
                    keep=int(data.get("keep") or 4),
                    avoid=data.get("avoid"),
                    root=data.get("repo") or data.get("root") or data.get("path"),
                ),
            )
            return

        if path == "/v1/reopen_anchors":
            _json(
                self,
                200,
                ce.reopen_anchors(
                    prefer=data.get("prefer"),
                    avoid=data.get("avoid"),
                    max_files=int(data.get("max_files") or 4),
                    max_chars=int(data.get("max_chars") or 500),
                    root=data.get("repo") or data.get("root") or data.get("path"),
                ),
            )
            return

        if path == "/v1/session_anchors":
            _json(
                self,
                200,
                ce.session_anchors(
                    root=data.get("repo") or data.get("root") or data.get("path")
                ),
            )
            return

        if path == "/v1/shutdown":
            ce.shutdown()
            _json(self, 200, {"ok": True, "shutdown": True})
            # stop server from another thread, then hard-exit (ORT RSS).
            def _stop() -> None:
                time.sleep(0.2)
                getattr(self.server, "shutdown", lambda: None)()
                print("[engine] shutdown os._exit", file=sys.stderr, flush=True)
                os._exit(0)

            import threading

            threading.Thread(target=_stop, daemon=True).start()
            return

        # legacy reload
        if path == "/reload":
            root = Path(data.get("path") or (ce.repo or ".")).resolve()
            _json(self, 200, ce.open_repo(root, background=False))
            return

        _json(self, 404, {"error": "not found"})


# Set once the HTTP server exists so the idle sweeper can stop it. ``stop_daemon``
# cannot kill the engine's own pid — ``safe_terminate_pid`` skips ``self_or_ancestor``
# — so an idle engine has to retire itself through the server it owns.
_HTTPD: ThreadingHTTPServer | None = None


def _register_httpd(server: ThreadingHTTPServer) -> None:
    global _HTTPD
    _HTTPD = server


def _retire_self() -> bool:
    """Stop serving from inside the engine and exit the process.

    ``stop_daemon`` cannot kill the engine's own pid. HTTP ``shutdown()`` alone
    can leave a zombie interpreter (non-daemon keeper threads) with ORT RSS still
    held. ``os._exit`` is the RAM contract.
    """
    server = _HTTPD

    def _die() -> None:
        try:
            if server is not None:
                server.shutdown()
        except Exception:  # noqa: BLE001
            pass
        print("[engine] retire_self running=false", file=sys.stderr, flush=True)
        os._exit(0)

    threading.Thread(target=_die, name="ce-self-retire", daemon=True).start()
    return True


def _start_idle_sweeper(
    *,
    interval_s: float | None = None,
    stop_event: threading.Event | None = None,
) -> threading.Thread:
    """Start the background idle sweeper. Returns the thread so tests can join it.

    ``stop_event`` lets a caller retire the sweeper deterministically; production
    leaves it None and the daemon thread lives for the life of the process.
    """
    import gc
    import threading

    def _loop() -> None:
        while not (stop_event is not None and stop_event.is_set()):
            try:
                from pipeline.lifecycle_runtime import (
                    idle_seconds,
                    load_policy,
                    reconcile_clients,
                )

                # Poll often enough to honor a 25s idle window (was fixed 30s).
                idle = idle_seconds()
                if interval_s is not None:
                    sleep_s = interval_s
                elif idle <= 0:
                    sleep_s = 5.0
                else:
                    # After last MCP leave, poll every 1s so process exit hits ~10s not ~15–20s.
                    try:
                        left = load_policy().get("last_client_left_at")
                        armed = left is not None and not reconcile_clients()
                    except Exception:  # noqa: BLE001
                        armed = False
                    sleep_s = 1.0 if armed else max(5.0, min(10.0, idle / 5.0))
            except Exception:  # noqa: BLE001
                sleep_s = 5.0
            if stop_event is not None:
                if stop_event.wait(max(0.0, float(sleep_s))):
                    return
            else:
                time.sleep(max(0.0, float(sleep_s)))
            try:
                from pipeline.memory_governor import get_governor
                from pipeline.ce_service import get_context_engine

                demote = get_governor().maybe_demote_idle(get_context_engine().hub)
                if demote and demote.get("action") == "demote_serve":
                    print(
                        f"[engine] memory demote: tier={demote.get('tier')} "
                        f"idle_s={demote.get('idle_s')}",
                        file=sys.stderr,
                        flush=True,
                    )
                elif demote and demote.get("action") == "hold_mcp_clients":
                    # Hold FastEmbed hot while MCP is connected. Always arm the
                    # keepalive loop — when soft is up but dense is still cold
                    # the loop kicks async prewarm (2s poll) so Cursor-open
                    # settle does not sit soft=true/embed=false until first map.
                    try:
                        from pipeline.engine import ensure_embed_keepalive_loop

                        ensure_embed_keepalive_loop(
                            os.environ.get("CTX_REPO") or None
                        )
                    except Exception:  # noqa: BLE001
                        pass
                get_governor().refresh_from_hub(get_context_engine().hub)
            except Exception:  # noqa: BLE001
                pass
            try:
                from pipeline.lifecycle_runtime import enforce_mcp_warm_contract

                idle_result = enforce_mcp_warm_contract()
                action = str((idle_result or {}).get("action") or "none")
                # "none"/"already_standby"/"hold_clients" are quiet steady states.
                if action not in {"none", "already_standby", "hold_clients"}:
                    print(
                        f"[engine] warm contract: action={action} "
                        f"clients={(idle_result or {}).get('active_clients')} "
                        f"idle={(idle_result or {}).get('idle')}",
                        file=sys.stderr,
                        flush=True,
                    )
                if action == "standby" or (
                    isinstance((idle_result or {}).get("idle"), dict)
                    and (idle_result or {}).get("idle", {}).get("action") == "standby"
                ):
                    # Never retire mid-index even if policy raced past the busy check.
                    try:
                        from pipeline.lifecycle_runtime import _idle_busy_reason

                        busy = _idle_busy_reason()
                    except Exception:  # noqa: BLE001
                        busy = None
                    if busy is not None:
                        print(
                            f"[engine] idle sweep: skip retire ({busy})",
                            file=sys.stderr,
                            flush=True,
                        )
                        continue
                    # stop_daemon cannot kill this process (self pid is protected).
                    # Always retire in-process on disconnect standby — success is
                    # process absence, not a soft demote that leaves ~1GB RSS.
                    print(
                        "[engine] retire_self",
                        file=sys.stderr,
                        flush=True,
                    )
                    if _retire_self():
                        return
                    raise SystemExit(0)
            except Exception as exc:  # noqa: BLE001
                print(f"[engine] idle sweep failed: {type(exc).__name__}: {exc}",
                      file=sys.stderr, flush=True)
            # Safe GC collection point — daemon is idle, no embedding in progress.
            gc.collect()

    thread = threading.Thread(target=_loop, name="ce-idle-sweeper", daemon=True)
    thread.start()
    return thread


def run_server(
    repo: Path,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    open_on_start: bool = False,
) -> None:
    """Run Context Engine daemon (blocking)."""
    # Disable automatic GC in the daemon process. Native extensions (tokenizers,
    # MLX, numpy) release the GIL during computation; if Python's GC fires on
    # another thread while these extensions are mutating Python objects, it can
    # traverse freed/inconsistent memory → SIGSEGV. We collect manually at safe
    # points instead (after sync, during idle sweeps).
    import gc

    gc.disable()
    # A killed open leaves warm_phase.json and embed_prewarm.busy behind.
    # The watchdog reads those and force-restarts the next process on its
    # first tick, so the repo never finishes opening.
    try:
        from pipeline.engine import _mark_prewarm_busy
        from pipeline.warm_autoload import mark_down

        _mark_prewarm_busy(False)
        mark_down()
    except Exception:  # noqa: BLE001
        pass

    # Disable Rayon parallelism in tokenizers to prevent memory corruption.
    # The Rayon thread pool on macOS ARM64 corrupts CPython's heap.
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    from pipeline.sync_loop import enable_session_keeper_defaults

    enable_session_keeper_defaults()
    from pipeline.git_family import reconcile_git_families

    _start_idle_sweeper()
    ce = get_context_engine()
    repo = repo.resolve()
    t0 = time.perf_counter()
    print(
        f"[engine] Scubiee starting on http://{host}:{port}",
        file=sys.stderr,
        flush=True,
    )
    print(
        f"[engine] CTX_HOME={os.environ.get('CTX_HOME') or '(default)'}",
        file=sys.stderr,
        flush=True,
    )
    print(f"[engine] dashboard http://{host}:{port}/dashboard", file=sys.stderr, flush=True)

    httpd = ThreadingHTTPServer((host, port), Handler)
    _register_httpd(httpd)

    # Single-instance lock for foreground / daemon child
    try:
        from pipeline.daemon import acquire_lock, release_lock

        acquire_lock(os.getpid(), url=f"http://{host}:{port}", repo=str(repo))
    except Exception as exc:  # noqa: BLE001
        print(f"[engine] lock note: {exc}", file=sys.stderr, flush=True)

    def _on_exit() -> None:
        ce.shutdown()
        try:
            from pipeline.daemon import release_lock_if_owner

            release_lock_if_owner()
        except Exception:  # noqa: BLE001
            pass

    import atexit

    atexit.register(_on_exit)

    # Keep pid file in sync with the listening process (parent spawn may have
    # written a different pid before detach).
    try:
        from pipeline.daemon import pid_path

        pid_path().write_text(str(os.getpid()), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    print(
        f"[engine] listening +{time.perf_counter() - t0:.2f}s — "
        f"MCP/CLI should use CTX_ENGINE_URL=http://{host}:{port}",
        file=sys.stderr,
        flush=True,
    )

    def _after_listen() -> None:
        try:
            from pipeline.process_job import attach_engine_on_start

            attach_engine_on_start()
        except Exception as exc:  # noqa: BLE001
            print(f"[engine] job join note: {exc}", file=sys.stderr, flush=True)
        try:
            family = reconcile_git_families(prefer_root=repo)
            if family.superseded_project_ids:
                print(
                    f"[engine] git-family reconcile: canonical={family.canonical_project_ids} "
                    f"superseded={family.superseded_project_ids}",
                    file=sys.stderr,
                    flush=True,
                )
        except Exception as exc:  # noqa: BLE001
            print(f"[engine] git-family reconcile note: {exc}", file=sys.stderr, flush=True)
        try:
            from pipeline.memory_governor import get_governor

            get_governor().apply_tier("locate_only")
        except Exception:  # noqa: BLE001
            pass
        if open_on_start:
            print(f"[engine] opening {repo} …", file=sys.stderr, flush=True)
            ce.open_repo(repo, background=True)

    threading.Thread(target=_after_listen, name="ce-after-listen", daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[engine] shutdown", file=sys.stderr)
        ce.shutdown()
        httpd.server_close()
