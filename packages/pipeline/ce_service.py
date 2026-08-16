"""Context Engine RuntimeManager — core backend (independent of MCP).

Three managers inside one process:
  RuntimeManager  — lifecycle, publish search generation, serve queries
  IndexManager    — probe / full index / incremental sync
  ResourceManager — host admission / batching

MCP / CLI / dashboard are thin clients.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from pipeline.engine import clear_engines, load_engine
from pipeline.index_manager import get_index_manager
from pipeline.registration import (
    is_always_allowed,
    is_registered,
    needs_registration_consent,
    register_project as do_register_project,
    registration_prompt_payload,
)
from pipeline.settings import get_registration_mode, load_prefs, save_prefs
from pipeline.store import PipelineStore
from pipeline.sync_loop import (
    BackgroundSyncLoop,
    auto_index_enabled,
    enable_session_keeper_defaults,
)


class RuntimeManager:
    """Process-local runtime: workspace, keeper, published search engine."""

    def __init__(self) -> None:
        self.repo: Path | None = None
        self.engine = None
        self.sync_loop: BackgroundSyncLoop | None = None
        self.project_id: str | None = None
        self.warm_state: str = "idle"
        self.warming: bool = False
        self.indexing: bool = False
        self.warm_error: str | None = None
        self.warm_ms: float | None = None
        self.generation: int = 0
        self.last_sync_at: float | None = None
        self._lock = threading.RLock()
        self.index = get_index_manager()

    # --- publish (searcher generation) ------------------------------------

    def publish_engine(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Reload and publish the live search engine after index/sync commit.

        Keeper / sync must call this so HTTP search (skip_freshness) stays correct.
        """
        repo = self.repo
        if repo is None:
            return {"ok": False, "error": "no repo"}
        with self._lock:
            try:
                clear_engines()
                eng = load_engine(repo, force_reload=True)
                self.engine = eng
                self.generation += 1
                self.last_sync_at = time.time()
                self.warm_state = "ready"
                self.warm_error = None
                return {
                    "ok": True,
                    "generation": self.generation,
                    "last_sync_at": self.last_sync_at,
                    "chunks": len(eng.texts),
                    "payload": payload,
                }
            except Exception as exc:  # noqa: BLE001
                self.warm_error = str(exc)
                return {"ok": False, "error": str(exc), "generation": self.generation}

    def health(self) -> dict[str, Any]:
        index_usable = False
        if self.repo is not None:
            try:
                from pipeline.project_id import index_is_usable, resolve_project

                ref = resolve_project(self.repo)
                index_usable = index_is_usable(ref.store_dir)
            except Exception:  # noqa: BLE001
                index_usable = self.engine is not None
        return {
            "ok": True,
            "service": "context-engine",
            "warm": self.engine is not None,
            "warm_state": self.warm_state,
            "generation": self.generation,
            "index_usable": index_usable,
            "last_sync_at": self.last_sync_at,
            "repo": str(self.repo) if self.repo else None,
            "dashboard": "/dashboard",
            "api": "/v1/*",
        }

    def mark_dirty(self, paths: list[str], *, reason: str = "write") -> dict[str, Any]:
        """Queue changed files for the active keeper's debounced sync path."""
        normalized = sorted({str(path).replace("\\", "/") for path in paths if str(path)})
        loop = self.sync_loop
        if loop is None:
            return {"ok": False, "error": "keeper not running", "paths": normalized}
        loop.mark_dirty(normalized, reason=reason)
        return {"ok": True, "paths": normalized, "reason": reason}

    def note_locate(self) -> dict[str, Any]:
        """Keep publication stable while CE locate tools are in active use."""
        loop = self.sync_loop
        if loop is None:
            return {"ok": False, "error": "keeper not running"}
        loop.note_locate()
        return {"ok": True}

    # --- lifecycle ---------------------------------------------------------

    def open_repo(self, root: Path | str, *, background: bool = False) -> dict[str, Any]:
        """Register/warm policy for a repo. background=True starts a thread."""
        root = Path(root).resolve()
        if background:
            t = threading.Thread(
                target=self._open_repo_sync, args=(root,), name="ce-open", daemon=True
            )
            t.start()
            return {"ok": True, "repo": str(root), "warming": True, "async": True}
        return self._open_repo_sync(root)

    def _open_repo_sync(self, root: Path) -> dict[str, Any]:
        enable_session_keeper_defaults()
        with self._lock:
            self._stop_keeper(final=True, reason="open_repo")
            clear_engines()
            self.engine = None
            self.repo = root
            self.warm_error = None

            mode = get_registration_mode()
            if mode == "automatic":
                return self._warm_after_register(root, always_allow=True)

            if is_registered(root) or is_always_allowed(root):
                if is_always_allowed(root) and not is_registered(root):
                    do_register_project(
                        root, always_allow=True, index=auto_index_enabled()
                    )
                return self._warm_registered(root)

            self.warm_state = "awaiting_registration"
            self.warming = False
            return {
                "ok": True,
                "repo": str(root),
                "warm_state": self.warm_state,
                "registration_mode": mode,
                **registration_prompt_payload(root),
            }

    def _should_start_keeper(self) -> bool:
        prefs = load_prefs()
        return bool(prefs.get("incremental_indexing", True) or prefs.get("file_watching", True))

    def _start_keeper(self, repo: Path) -> None:
        if not self._should_start_keeper():
            return
        if self.sync_loop and self.sync_loop.running:
            return
        loop = BackgroundSyncLoop(repo, on_refresh=self.publish_engine)
        loop.start()
        self.sync_loop = loop

    def _stop_keeper(self, *, final: bool = True, reason: str = "stop") -> None:
        loop = self.sync_loop
        if not loop:
            return
        if final:
            try:
                loop.final_check(reason=reason)
            except Exception:  # noqa: BLE001
                pass
        loop.stop()
        self.sync_loop = None

    def _warm_after_register(self, root: Path, *, always_allow: bool) -> dict[str, Any]:
        self.warming = True
        self.warm_state = "indexing"
        try:
            result = do_register_project(
                root, always_allow=always_allow, index=auto_index_enabled()
            )
            if not result.ok:
                raise RuntimeError(result.error or "registration failed")
            self.project_id = result.project_id
            return self._warm_registered(root)
        except Exception as exc:  # noqa: BLE001
            self.warm_error = str(exc)
            self.warm_state = "error"
            self.warming = False
            return {"ok": False, "error": str(exc), "warm_state": "error"}

    def _warm_registered(self, root: Path) -> dict[str, Any]:
        from pipeline.project_id import index_is_usable, resolve_project

        self.warming = True
        self.warm_error = None
        self.warm_state = "warming"
        t0 = time.perf_counter()
        try:
            ref = resolve_project(root)
            self.project_id = ref.project_id
            self.repo = root
            store = PipelineStore(root, base_dir=ref.store_dir, project_id=ref.project_id)
            if not index_is_usable(store.base) and auto_index_enabled():
                self.indexing = True
                self.warm_state = "indexing"
                idx = self.index.full_index(root, force=False, fast=False)
                self.indexing = False
                if idx.get("deferred"):
                    raise RuntimeError(
                        f"Index deferred under resource pressure: {idx.get('error')}"
                    )
                if not idx.get("ok", True) and idx.get("error"):
                    raise RuntimeError(str(idx["error"]))
            elif not index_is_usable(store.base):
                raise RuntimeError("No index found. Run: ctx register .  or  ctx index .")

            pub = self.publish_engine()
            if not pub.get("ok"):
                raise RuntimeError(pub.get("error") or "publish failed")
            eng = self.engine
            self.warm_ms = (time.perf_counter() - t0) * 1000
            self.warm_state = "ready"
            self._start_keeper(root)
            return {
                "ok": True,
                "repo": str(root),
                "project_id": self.project_id,
                "warm_state": "ready",
                "warm_ms": self.warm_ms,
                "generation": self.generation,
                "chunks": len(eng.texts) if eng else 0,
            }
        except Exception as exc:  # noqa: BLE001
            self.warm_error = str(exc)
            self.warm_state = "error"
            return {"ok": False, "error": str(exc), "warm_state": "error"}
        finally:
            self.warming = False
            self.indexing = False

    def shutdown(self) -> None:
        self._stop_keeper(final=True, reason="shutdown")
        clear_engines()
        self.engine = None

    # --- API ---------------------------------------------------------------

    def status(self, root: Path | str | None = None) -> dict[str, Any]:
        repo = Path(root).resolve() if root else (self.repo or Path.cwd())
        prefs = load_prefs()
        payload: dict[str, Any] = {
            "ok": True,
            "service": "context-engine",
            "repo": str(repo),
            "registration_mode": get_registration_mode(),
            "registered": is_registered(repo),
            "always_allow": is_always_allowed(repo),
            "project_id": self.project_id,
            "warm_state": self.warm_state,
            "warming": self.warming,
            "indexing": self.indexing,
            "warm_error": self.warm_error,
            "warm_ms": self.warm_ms,
            "generation": self.generation,
            "last_sync_at": self.last_sync_at,
            "prefs": {
                "registration_mode": prefs.get("registration_mode"),
                "incremental_indexing": prefs.get("incremental_indexing"),
                "file_watching": prefs.get("file_watching"),
            },
            "engine": self.engine.status() if self.engine else None,
            "keeper": self.sync_loop.status() if self.sync_loop else None,
        }
        try:
            from pipeline.resources import get_resource_manager

            payload["resources"] = get_resource_manager().status()
        except Exception:  # noqa: BLE001
            payload["resources"] = None

        if needs_registration_consent(repo):
            payload["needs_registration"] = registration_prompt_payload(repo)
            return payload

        try:
            store = PipelineStore(repo)
            payload["project_id"] = self.project_id or store.project_id
            payload["root_probe"] = self.index.probe(repo)
            payload["meta"] = {
                k: store.load_meta().get(k)
                for k in (
                    "chunks",
                    "files_indexed",
                    "embed_model",
                    "embed_backend",
                    "fast",
                    "collection",
                    "project_id",
                    "last_incremental_at",
                )
            }
            payload["last_bg_sync"] = (
                self.sync_loop.last_result if self.sync_loop else None
            )
        except Exception as exc:  # noqa: BLE001
            payload["store_error"] = str(exc)
        return payload

    def register(
        self,
        root: Path | str | None = None,
        *,
        always_allow: bool = False,
        index: bool = True,
    ) -> dict[str, Any]:
        repo = Path(root).resolve() if root else (self.repo or Path.cwd())
        result = do_register_project(
            repo,
            always_allow=always_allow,
            index=index and auto_index_enabled(),
        )
        out = result.to_dict()
        if result.ok:
            warm = self._warm_registered(repo)
            out["warm"] = warm
        return out

    def search(self, query: str, *, top_k: int = 8, root: Path | str | None = None) -> dict[str, Any]:
        # Serve published generation; freshness is keeper + publish_engine.
        gate = self._gate(root)
        if gate:
            return gate
        eng = self._ensure_engine(root)
        if eng is None:
            return {"status": "warming", "ready": False, "warm_state": self.warm_state}
        hits = eng.search(query, top_k=top_k, skip_freshness=True)
        return {
            "ok": True,
            "query": query,
            "generation": self.generation,
            "keeper": self.sync_loop.status() if self.sync_loop else None,
            "timings": getattr(eng, "_last_timings", {}),
            "hits": [
                {
                    "rank": h.rank,
                    "path": h.file,
                    "file": h.file,
                    "score": round(h.score, 4),
                    "chunk_id": h.chunk_id,
                    "start_line": getattr(h, "start_line", None),
                    "end_line": getattr(h, "end_line", None),
                    "why": (h.preview or "")[:200],
                    "source": h.source,
                    "channels": (
                        h.source.split(":", 1)[1].split("+")
                        if isinstance(h.source, str) and h.source.startswith("D_channel_best:")
                        else None
                    ),
                }
                for h in hits
            ],
            "hint": (
                "Arrow only — use query_graph / read_span / follow_imports / "
                "graph_neighbors / grep_ident to gather more context without full files."
            ),
        }

    def locate(self, query: str, *, top_k: int = 5, root: Path | str | None = None) -> dict[str, Any]:
        gate = self._gate(root)
        if gate:
            return gate
        eng = self._ensure_engine(root)
        if eng is None:
            return {"status": "warming", "ready": False}
        t0 = time.perf_counter()
        hits = eng.locate_capability(query, top_k=top_k)
        return {
            "ok": True,
            "query": query,
            "ms": round((time.perf_counter() - t0) * 1000, 2),
            "hits": [
                {
                    "path": h.path,
                    "symbol": h.symbol,
                    "why": h.why,
                    "score": round(h.score, 4),
                    "card_id": h.card_id,
                }
                for h in hits
            ],
        }

    def sync(self, root: Path | str | None = None) -> dict[str, Any]:
        gate = self._gate(root)
        if gate:
            return gate
        repo = Path(root).resolve() if root else (self.repo or Path.cwd())
        self.repo = repo
        out = self.index.sync(repo)
        if out.get("refreshed"):
            pub = self.publish_engine()
            out["published"] = pub
            out["generation"] = self.generation
        return out

    def grep(
        self, pattern: str, *, glob: str = "*.py", max_hits: int = 20, root: Path | str | None = None
    ) -> dict[str, Any]:
        gate = self._gate(root)
        if gate:
            return gate
        from pipeline.capability import grep_code

        repo = Path(root).resolve() if root else (self.repo or Path.cwd())
        t0 = time.perf_counter()
        hits = grep_code(repo, pattern, glob=glob, max_hits=max_hits)
        return {
            "ok": True,
            "pattern": pattern,
            "ms": round((time.perf_counter() - t0) * 1000, 2),
            "hits": hits,
        }

    def outline(self, path: str, *, root: Path | str | None = None) -> dict[str, Any]:
        gate = self._gate(root)
        if gate:
            return gate
        from pipeline.capability import file_outline

        repo = Path(root).resolve() if root else (self.repo or Path.cwd())
        rel = path.replace("\\", "/")
        try:
            if Path(path).is_absolute():
                rel = str(Path(path).resolve().relative_to(repo)).replace("\\", "/")
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "path": rel, "symbols": file_outline(repo, rel)}

    def read_span(
        self,
        path: str,
        *,
        start_line: int | None = None,
        end_line: int | None = None,
        max_chars: int = 700,
        avoid: list[str] | None = None,
        root: Path | str | None = None,
    ) -> dict[str, Any]:
        gate = self._gate(root)
        if gate:
            return gate
        eng = self._ensure_engine(root)
        if eng is None:
            return {"status": "warming", "ready": False}
        from pipeline.context_nav import tool_read_span

        return tool_read_span(
            eng,
            path,
            start_line=start_line,
            end_line=end_line,
            max_chars=max_chars,
            avoid=avoid,
        )

    def follow_imports(
        self,
        path: str,
        *,
        query: str = "",
        keep: int = 6,
        max_chars: int = 500,
        avoid: list[str] | None = None,
        root: Path | str | None = None,
    ) -> dict[str, Any]:
        gate = self._gate(root)
        if gate:
            return gate
        eng = self._ensure_engine(root)
        if eng is None:
            return {"status": "warming", "ready": False}
        from pipeline.context_nav import tool_follow_imports

        return tool_follow_imports(
            eng,
            path,
            query=query,
            keep=keep,
            max_chars=max_chars,
            avoid=avoid,
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
        root: Path | str | None = None,
    ) -> dict[str, Any]:
        gate = self._gate(root)
        if gate:
            return gate
        eng = self._ensure_engine(root)
        if eng is None:
            return {"status": "warming", "ready": False}
        from pipeline.context_nav import tool_graph_neighbors

        return tool_graph_neighbors(
            eng,
            paths,
            query=query,
            cap=cap,
            keep=keep,
            max_chars=max_chars,
            avoid=avoid,
        )

    def query_graph(
        self,
        question: str,
        *,
        keep: int = 6,
        neighbor_keep: int = 4,
        max_chars: int = 400,
        avoid: list[str] | None = None,
        root: Path | str | None = None,
    ) -> dict[str, Any]:
        gate = self._gate(root)
        if gate:
            return gate
        eng = self._ensure_engine(root)
        if eng is None:
            return {"status": "warming", "ready": False}
        from pipeline.context_nav import tool_query_graph

        return tool_query_graph(
            eng,
            question,
            keep=keep,
            neighbor_keep=neighbor_keep,
            max_chars=max_chars,
            avoid=avoid,
        )

    def grep_ident(
        self,
        ident: str,
        *,
        max_hits: int = 12,
        max_chars: int = 500,
        keep: int = 4,
        avoid: list[str] | None = None,
        root: Path | str | None = None,
    ) -> dict[str, Any]:
        gate = self._gate(root)
        if gate:
            return gate
        eng = self._ensure_engine(root)
        if eng is None:
            return {"status": "warming", "ready": False}
        from pipeline.context_nav import tool_grep_ident

        return tool_grep_ident(
            eng,
            ident,
            max_hits=max_hits,
            max_chars=max_chars,
            keep=keep,
            avoid=avoid,
        )

    def reopen_anchors(
        self,
        *,
        prefer: list[str] | None = None,
        avoid: list[str] | None = None,
        max_files: int = 4,
        max_chars: int = 500,
        root: Path | str | None = None,
    ) -> dict[str, Any]:
        gate = self._gate(root)
        if gate:
            return gate
        eng = self._ensure_engine(root)
        if eng is None:
            return {"status": "warming", "ready": False}
        from pipeline.context_nav import tool_reopen_anchors

        return tool_reopen_anchors(
            eng,
            prefer=prefer,
            avoid=avoid,
            max_files=max_files,
            max_chars=max_chars,
        )

    def session_anchors(self, *, root: Path | str | None = None) -> dict[str, Any]:
        gate = self._gate(root)
        if gate:
            return gate
        eng = self._ensure_engine(root)
        if eng is None:
            return {"status": "warming", "ready": False}
        from pipeline.context_nav import tool_session_status

        return tool_session_status(eng)

    def get_settings(self) -> dict[str, Any]:
        return load_prefs()

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        prefs = load_prefs()
        for key in (
            "registration_mode",
            "incremental_indexing",
            "file_watching",
            "resource_management",
        ):
            if key in patch:
                prefs[key] = patch[key]
        save_prefs(prefs)
        if "resource_management" in patch:
            try:
                from pipeline.resources import get_resource_manager

                get_resource_manager().reload_prefs()
            except Exception:  # noqa: BLE001
                pass
        return load_prefs()

    def _gate(self, root: Path | str | None) -> dict[str, Any] | None:
        repo = Path(root).resolve() if root else (self.repo or Path.cwd())
        if needs_registration_consent(repo):
            return registration_prompt_payload(repo)
        return None

    def _ensure_engine(self, root: Path | str | None):
        if self.engine is not None:
            return self.engine
        repo = Path(root).resolve() if root else self.repo
        if repo is None:
            return None
        if self.warm_state == "awaiting_registration":
            return None
        try:
            self.repo = repo
            eng = load_engine(repo)
            self.engine = eng
            self.warm_state = "ready"
            if self.generation == 0:
                self.generation = 1
            return eng
        except Exception:  # noqa: BLE001
            return None


# Back-compat alias
ContextEngine = RuntimeManager

_CE: RuntimeManager | None = None
_CE_LOCK = threading.Lock()


def get_context_engine() -> RuntimeManager:
    global _CE
    with _CE_LOCK:
        if _CE is None:
            _CE = RuntimeManager()
        return _CE


def get_runtime_manager() -> RuntimeManager:
    return get_context_engine()
