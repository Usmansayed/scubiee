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


def _json(handler: BaseHTTPRequestHandler, code: int, payload: dict) -> None:
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
        data = _read_json(self)
        ce = get_context_engine()

        if path in ("/api/settings", "/v1/settings"):
            _json(self, 200, ce.update_settings(data))
            return

        if path == "/v1/open":
            root = data.get("path") or (str(ce.repo) if ce.repo else ".")
            wait = bool(data.get("wait"))
            if wait:
                _json(self, 200, ce.open_repo(root, background=False))
            else:
                _json(self, 200, ce.open_repo(root, background=True))
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

        if path in ("/v1/status", "/status"):
            _json(self, 200, ce.status(data.get("path")))
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
            _json(self, 200, ce.sync(data.get("path") or None))
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
                    glob=str(data.get("glob") or "*.py"),
                    max_hits=int(data.get("max_hits") or 20),
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


def run_server(
    repo: Path,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    open_on_start: bool = True,
) -> None:
    """Run Context Engine daemon (blocking)."""
    from pipeline.sync_loop import enable_session_keeper_defaults

    enable_session_keeper_defaults()
    ce = get_context_engine()
    repo = repo.resolve()
    print(
        f"[engine] Context Engine starting on http://{host}:{port}",
        file=sys.stderr,
        flush=True,
    )
    print(
        f"[engine] CTX_HOME={os.environ.get('CTX_HOME') or '(default)'}",
        file=sys.stderr,
        flush=True,
    )
    print(f"[engine] dashboard http://{host}:{port}/dashboard", file=sys.stderr, flush=True)

    if open_on_start:
        print(f"[engine] opening {repo} …", file=sys.stderr, flush=True)
        # Background warm so HTTP accepts health immediately
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
