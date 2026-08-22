"""HTTP client for the Context Engine daemon."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_URL = "http://127.0.0.1:8765"


def engine_url() -> str:
    return (
        os.environ.get("CTX_ENGINE_URL")
        or os.environ.get("CTX_SEARCH_URL")
        or DEFAULT_URL
    ).rstrip("/")


class EngineClient:
    """Thin HTTP client — no business logic."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = 120.0,
        workspace_path: str | Path | None = None,
        client: str | None = None,
        session_id: str | None = None,
    ):
        self.base = (base_url or engine_url()).rstrip("/")
        self.timeout = timeout
        self.workspace_path = (
            str(Path(workspace_path).resolve()) if workspace_path else None
        )
        self.client_name = client
        self.session_id = session_id

    def _coerce_workspace(self, supplied: Any) -> str:
        """Only existing directories are workspaces — never mkdir from a query string."""
        if supplied:
            try:
                candidate = Path(str(supplied))
                if candidate.is_dir():
                    return str(candidate.resolve())
            except OSError:
                pass
            if not self.workspace_path:
                raise ValueError(f"workspace path is not a directory: {supplied}")
        if self.workspace_path:
            return str(self.workspace_path)
        raise ValueError("workspace path is required for Context Engine requests")

    def healthy(self) -> bool:
        """True if /health returns ok. Always uses a short timeout."""
        try:
            url = f"{self.base}/health"
            req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw) if raw else {}
                return bool(data.get("ok"))
        except Exception:  # noqa: BLE001
            return False

    def get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path)

    def post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("POST", path, body or {})

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base}{path}"
        data = None
        headers = {"Accept": "application/json"}
        if body is not None and method != "GET":
            payload = dict(body)
            supplied_path = payload.get("path") or payload.get("repo") or payload.get("root")
            workspace = self._coerce_workspace(supplied_path)
            payload["path"] = workspace
            if self.client_name:
                payload.setdefault("client", self.client_name)
            if self.session_id:
                payload.setdefault("session_id", self.session_id)
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            try:
                err_body = exc.read().decode("utf-8")
                payload = json.loads(err_body) if err_body else {}
            except Exception:  # noqa: BLE001
                payload = {"error": str(exc)}
            payload.setdefault("ok", False)
            payload.setdefault("http_status", exc.code)
            return payload
        except urllib.error.URLError as exc:
            return {
                "ok": False,
                "error": f"Context Engine unreachable at {self.base}: {exc.reason}",
                "hint": "Run: ctx setup   or   ctx engine start",
            }
        except (TimeoutError, OSError, ConnectionError) as exc:
            # WinError 10054/10061 etc. — treat as unreachable, don't crash callers
            return {
                "ok": False,
                "error": f"Context Engine unreachable at {self.base}: {exc}",
                "hint": "Run: ctx setup   or   ctx engine start",
            }

    # Convenience wrappers matching CE API
    def status(self, path: str | None = None) -> dict[str, Any]:
        return self.post("/v1/status", {"path": path or self.workspace_path})

    def open_repo(self, path: str, *, wait: bool = False) -> dict[str, Any]:
        return self.post(
            "/v1/open",
            {"path": path, "wait": wait, "explicit": True},
        )

    def lifecycle(self, action: str, path: str = "", **options: Any) -> dict[str, Any]:
        return self.post(
            "/v1/lifecycle",
            {"action": action, "path": path or self.workspace_path, **options},
        )

    def end_session(self, path: str = "") -> dict[str, Any]:
        if not self.session_id:
            raise ValueError("session_id is required to end a Context Engine session")
        return self.post(
            "/v1/session/end",
            {"path": path or self.workspace_path, "session_id": self.session_id},
        )

    def register(
        self, path: str = "", *, always_allow: bool = False, index: bool = True
    ) -> dict[str, Any]:
        return self.post(
            "/v1/register",
            {"path": path, "always_allow": always_allow, "index": index},
        )

    def search(self, query: str, *, top_k: int = 8, path: str = "") -> dict[str, Any]:
        return self.post("/v1/search", {"query": query, "top_k": top_k, "path": path})

    def locate(self, query: str, *, top_k: int = 5, path: str = "") -> dict[str, Any]:
        return self.post("/v1/locate", {"query": query, "top_k": top_k, "path": path})

    def sync(self, path: str = "", *, confirm: bool = False) -> dict[str, Any]:
        return self.post("/v1/sync", {"path": path, "confirm": bool(confirm)})

    def publish(self, path: str = "", *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Reload the daemon's in-memory search engine after an external sync/index."""
        body: dict[str, Any] = {"path": path}
        if payload is not None:
            body["payload"] = payload
        return self.post("/v1/publish", body)

    def mark_dirty(
        self, paths: list[str], *, reason: str = "changed_file", path: str = ""
    ) -> dict[str, Any]:
        return self.post("/v1/dirty", {"paths": paths, "reason": reason, "path": path})

    def note_locate(self, *, path: str = "") -> dict[str, Any]:
        return self.post("/v1/note_locate", {"path": path})

    def grep(
        self, pattern: str, *, glob: str = "*.py", max_hits: int = 20, path: str = ""
    ) -> dict[str, Any]:
        return self.post(
            "/v1/grep",
            {"pattern": pattern, "glob": glob, "max_hits": max_hits, "path": path},
        )

    def outline(self, file_path: str, *, repo: str = "") -> dict[str, Any]:
        return self.post("/v1/outline", {"file": file_path, "repo": repo or None})

    def read_span(
        self,
        file_path: str,
        *,
        start_line: int | None = None,
        end_line: int | None = None,
        max_chars: int = 700,
        avoid: list[str] | None = None,
        repo: str = "",
    ) -> dict[str, Any]:
        return self.post(
            "/v1/read_span",
            {
                "file": file_path,
                "start_line": start_line,
                "end_line": end_line,
                "max_chars": max_chars,
                "avoid": avoid,
                "repo": repo or None,
            },
        )

    def follow_imports(
        self,
        file_path: str,
        *,
        query: str = "",
        keep: int = 6,
        max_chars: int = 500,
        avoid: list[str] | None = None,
        repo: str = "",
    ) -> dict[str, Any]:
        return self.post(
            "/v1/follow_imports",
            {
                "file": file_path,
                "query": query,
                "keep": keep,
                "max_chars": max_chars,
                "avoid": avoid,
                "repo": repo or None,
            },
        )

    def graph_neighbors(
        self,
        paths: list[str],
        *,
        query: str = "",
        cap: int = 16,
        keep: int = 4,
        max_chars: int = 500,
        avoid: list[str] | None = None,
        repo: str = "",
    ) -> dict[str, Any]:
        return self.post(
            "/v1/graph_neighbors",
            {
                "paths": paths,
                "query": query,
                "cap": cap,
                "keep": keep,
                "max_chars": max_chars,
                "avoid": avoid,
                "repo": repo or None,
            },
        )

    def query_graph(
        self,
        question: str,
        *,
        keep: int = 6,
        neighbor_keep: int = 4,
        max_chars: int = 400,
        avoid: list[str] | None = None,
        repo: str = "",
    ) -> dict[str, Any]:
        return self.post(
            "/v1/query_graph",
            {
                "question": question,
                "keep": keep,
                "neighbor_keep": neighbor_keep,
                "max_chars": max_chars,
                "avoid": avoid,
                "repo": repo or None,
            },
        )

    def grep_ident(
        self,
        ident: str,
        *,
        max_hits: int = 12,
        max_chars: int = 500,
        keep: int = 4,
        avoid: list[str] | None = None,
        path: str = "",
    ) -> dict[str, Any]:
        return self.post(
            "/v1/grep_ident",
            {
                "ident": ident,
                "max_hits": max_hits,
                "max_chars": max_chars,
                "keep": keep,
                "avoid": avoid,
                "path": path,
            },
        )

    def reopen_anchors(
        self,
        *,
        prefer: list[str] | None = None,
        avoid: list[str] | None = None,
        max_files: int = 4,
        max_chars: int = 500,
        path: str = "",
    ) -> dict[str, Any]:
        return self.post(
            "/v1/reopen_anchors",
            {
                "prefer": prefer,
                "avoid": avoid,
                "max_files": max_files,
                "max_chars": max_chars,
                "path": path,
            },
        )

    def session_anchors(self, path: str = "") -> dict[str, Any]:
        return self.post("/v1/session_anchors", {"path": path})

    def settings(self) -> dict[str, Any]:
        return self.get("/api/settings")

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        return self.post("/api/settings", patch)
