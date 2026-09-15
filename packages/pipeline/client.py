"""HTTP client for the Context Engine daemon."""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# Refusing a connect to a closed local port costs ~2s on Windows; healthy()
# runs inside stop/ensure polling loops, so probe the socket first.
_LOOPBACK_CONNECT_TIMEOUT_S = 0.35
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

_TRANSIENT_ENGINE_MARKERS = (
    "unreachable",
    "remote end closed",
    "connection reset",
    "connection refused",
    "timed out",
    "10054",
    "10061",
    "broken pipe",
)


def is_transient_engine_error(message: str) -> bool:
    low = (message or "").lower()
    return any(marker in low for marker in _TRANSIENT_ENGINE_MARKERS)

DEFAULT_URL = "http://127.0.0.1:8765"


def engine_url() -> str:
    """Resolve the engine HTTP URL.

    Explicit ``CTX_ENGINE_URL`` / ``CTX_SEARCH_URL`` win. Under pytest
    (``CTX_ALLOW_TEST_HOME=1``) default to port **18765** so unit tests cannot
    steal the production daemon on **8765** — that was the post-update bind
    failure mode (orphans left on 8765 pointing at a deleted pytest temp repo).
    """
    explicit = (os.environ.get("CTX_ENGINE_URL") or os.environ.get("CTX_SEARCH_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    if (os.environ.get("CTX_ALLOW_TEST_HOME") or "").strip() in {"1", "true", "yes"}:
        port = (os.environ.get("CTX_ENGINE_PORT") or "18765").strip() or "18765"
        return f"http://127.0.0.1:{port}"
    return DEFAULT_URL


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
        raise ValueError("workspace path is required for Scubiee requests")

    def _loopback_listener_absent(self) -> bool:
        """True only when a local port is provably closed (fast negative)."""
        try:
            parts = urllib.parse.urlsplit(self.base)
            host = (parts.hostname or "").lower()
            port = parts.port
        except ValueError:
            return False
        if port is None or host not in _LOOPBACK_HOSTS:
            return False
        try:
            with socket.create_connection((host, port), timeout=_LOOPBACK_CONNECT_TIMEOUT_S):
                return False
        except OSError:
            return True

    def health(self) -> dict[str, Any]:
        """Return /health JSON (includes embedder_loaded when engine is up)."""
        if self._loopback_listener_absent():
            return {"ok": False, "error": "listener_absent"}
        # Honor client timeout (locate probes use <1s); never exceed 3s.
        # Cap health probes: short enough for snappy UX, long enough that a
        # brief ORT/DML GIL hitch under the CPU affinity floor does not flap
        # "unreachable" (cold FastEmbed load can hold the interpreter ~1–8s).
        health_timeout = max(0.2, min(float(getattr(self, "timeout", 3.0) or 3.0), 8.0))
        transport = (os.environ.get("CTX_ENGINE_HTTP_TRANSPORT") or "httpx").strip().lower()
        if transport in {"urllib", "legacy"}:
            return self._health_urllib(timeout=health_timeout)
        try:
            from pipeline.engine_http import shared_engine_http

            http = shared_engine_http(self.base, timeout=health_timeout, retries=1)
            return http.get_json_soft("/health")
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def _health_urllib(self, *, timeout: float = 3.0) -> dict[str, Any]:
        try:
            url = f"{self.base}/health"
            req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw) if raw else {}
                return data if isinstance(data, dict) else {"ok": False}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def healthy(self) -> bool:
        """True if /health returns ok. Always uses a short timeout."""
        return bool(self.health().get("ok"))

    def get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path)

    def post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("POST", path, body or {})

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        _allow_retry: bool = True,
    ) -> dict[str, Any]:
        transport = (os.environ.get("CTX_ENGINE_HTTP_TRANSPORT") or "httpx").strip().lower()
        if transport not in {"urllib", "legacy"}:
            return self._request_httpx(method, path, body, allow_retry=_allow_retry)
        return self._request_urllib(method, path, body, allow_retry=_allow_retry)

    def _prepare_body(self, method: str, body: dict[str, Any] | None) -> dict[str, Any] | None:
        if body is None or method == "GET":
            return None
        payload = dict(body)
        supplied_path = payload.get("path") or payload.get("repo") or payload.get("root")
        workspace = self._coerce_workspace(supplied_path)
        payload["path"] = workspace
        if self.client_name:
            payload.setdefault("client", self.client_name)
        if self.session_id:
            payload.setdefault("session_id", self.session_id)
        return payload

    def _request_httpx(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        *,
        allow_retry: bool,
    ) -> dict[str, Any]:
        from pipeline.engine_http import shared_engine_http

        payload = self._prepare_body(method, body)
        http = shared_engine_http(self.base, timeout=float(self.timeout))
        if method.upper() == "GET":
            return http.get_json_soft(path)
        return http.post_json(
            path,
            payload or {},
            retry=bool(allow_retry) and path in {"/v1/status", "/status"},
        )

    def _request_urllib(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        *,
        allow_retry: bool,
    ) -> dict[str, Any]:
        url = f"{self.base}{path}"
        data = None
        headers = {"Accept": "application/json"}
        payload = self._prepare_body(method, body)
        if payload is not None:
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
                payload_err = json.loads(err_body) if err_body else {}
            except Exception:  # noqa: BLE001
                payload_err = {"error": str(exc)}
            payload_err.setdefault("ok", False)
            payload_err.setdefault("http_status", exc.code)
            if allow_retry and exc.code in {502, 503, 504}:
                time.sleep(0.35)
                retried = self._request_urllib(method, path, body, allow_retry=False)
                if isinstance(retried, dict):
                    retried["retried"] = True
                    retried.setdefault("should_retry", False)
                return retried
            if is_transient_engine_error(str(payload_err.get("error") or exc)):
                payload_err["should_retry"] = True
            return payload_err
        except urllib.error.URLError as exc:
            err = f"Scubiee unreachable at {self.base}: {exc.reason}"
            if allow_retry and is_transient_engine_error(err):
                time.sleep(0.35)
                retried = self._request_urllib(method, path, body, allow_retry=False)
                if isinstance(retried, dict):
                    retried["retried"] = True
                    retried.setdefault("should_retry", False)
                return retried
            return {
                "ok": False,
                "error": err,
                "hint": "Run: scubiee setup   or   scubiee engine start",
                "should_retry": is_transient_engine_error(err),
            }
        except (TimeoutError, OSError, ConnectionError) as exc:
            err = f"Scubiee unreachable at {self.base}: {exc}"
            if allow_retry and is_transient_engine_error(err):
                time.sleep(0.35)
                retried = self._request_urllib(method, path, body, allow_retry=False)
                if isinstance(retried, dict):
                    retried["retried"] = True
                    retried.setdefault("should_retry", False)
                return retried
            return {
                "ok": False,
                "error": err,
                "hint": "Run: scubiee setup   or   scubiee engine start",
                "should_retry": is_transient_engine_error(err),
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
            raise ValueError("session_id is required to end a Scubiee session")
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
        self, pattern: str, *, glob: str = "**/*", max_hits: int = 200, path: str = ""
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
