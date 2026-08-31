"""Context Engine HTTP daemon — single backend for MCP, CLI, dashboard."""

from __future__ import annotations

import json
import os
import sys
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

        def admit(root: str) -> dict:
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
                explicit=bool(data.get("explicit") or data.get("wait")),
            )

        if path in ("/api/settings", "/v1/settings"):
            _json(self, 200, ce.update_settings(data))
            return

        if path == "/v1/open":
            root = data.get("path")
            if not root:
                _json(self, 400, {"ok": False, "error": "workspace path required"})
                return
            admission = admit(root)
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
            admission = admit(root)
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
            _json(
                self,
                200,
                ce.sync(
                    data.get("path") or None,
                    confirm=bool(data.get("confirm")),
                ),
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
            # stop server from another thread
            def _stop() -> None:
                time.sleep(0.2)
                getattr(self.server, "shutdown", lambda: None)()

            import threading

            threading.Thread(target=_stop, daemon=True).start()
            return

        # legacy reload
        if path == "/reload":
            root = Path(data.get("path") or (ce.repo or ".")).resolve()
            _json(self, 200, ce.open_repo(root, background=False))
            return

        _json(self, 404, {"error": "not found"})


def _start_idle_sweeper(*, interval_s: float | None = None) -> None:
    import gc
    import threading

    def _loop() -> None:
        while True:
            try:
                from pipeline.lifecycle_runtime import idle_seconds

                # Poll often enough to honor a 25s idle window (was fixed 30s).
                idle = idle_seconds()
                sleep_s = interval_s if interval_s is not None else (
                    5.0 if idle <= 0 else max(5.0, min(10.0, idle / 5.0))
                )
            except Exception:  # noqa: BLE001
                sleep_s = 5.0
            time.sleep(max(5.0, float(sleep_s)))
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
                get_governor().refresh_from_hub(get_context_engine().hub)
            except Exception:  # noqa: BLE001
                pass
            try:
                from pipeline.lifecycle_runtime import apply_idle_policy

                apply_idle_policy()
            except Exception:  # noqa: BLE001
                pass
            # Safe GC collection point — daemon is idle, no embedding in progress.
            gc.collect()

    thread = threading.Thread(target=_loop, name="ce-idle-sweeper", daemon=True)
    thread.start()


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

    # Disable Rayon parallelism in tokenizers to prevent memory corruption.
    # The Rayon thread pool on macOS ARM64 corrupts CPython's heap.
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    from pipeline.sync_loop import enable_session_keeper_defaults

    enable_session_keeper_defaults()
    from pipeline.git_family import reconcile_git_families

    try:
        from pipeline.memory_governor import get_governor

        get_governor().apply_tier("locate_only")
    except Exception:  # noqa: BLE001
        pass

    family = reconcile_git_families(prefer_root=repo)
    if family.superseded_project_ids:
        print(
            f"[engine] git-family reconcile: canonical={family.canonical_project_ids} "
            f"superseded={family.superseded_project_ids}",
            file=sys.stderr,
            flush=True,
        )
    _start_idle_sweeper()
    ce = get_context_engine()
    repo = repo.resolve()
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
    try:
        from pipeline.process_job import attach_engine_on_start

        attach_engine_on_start()
    except Exception as exc:  # noqa: BLE001
        print(f"[engine] job join note: {exc}", file=sys.stderr, flush=True)

    if open_on_start:
        print(f"[engine] opening {repo} …", file=sys.stderr, flush=True)
        # Explicit callers may opt in; ordinary IDE/daemon startup stays idle
        # until a path-bearing CE request is admitted.
        ce.open_repo(repo, background=True)

    httpd = ThreadingHTTPServer((host, port), Handler)

    # Single-instance lock for foreground / daemon child
    try:
        from pipeline.daemon import acquire_lock, release_lock

        acquire_lock(os.getpid(), url=f"http://{host}:{port}", repo=str(repo))
    except Exception as exc:  # noqa: BLE001
        print(f"[engine] lock note: {exc}", file=sys.stderr, flush=True)

    def _on_exit() -> None:
        ce.shutdown()
        try:
            from pipeline.daemon import release_lock

            release_lock()
        except Exception:  # noqa: BLE001
            pass

    import atexit

    atexit.register(_on_exit)

    print(
        f"[engine] listening — MCP/CLI should use CTX_ENGINE_URL=http://{host}:{port}",
        file=sys.stderr,
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[engine] shutdown", file=sys.stderr)
        ce.shutdown()
        httpd.server_close()
