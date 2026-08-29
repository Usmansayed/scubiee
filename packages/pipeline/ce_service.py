"""Context Engine RuntimeManager — core backend (independent of MCP).

Three managers inside one process:
  RuntimeManager  — lifecycle, publish search generation, serve queries
  IndexManager    — probe / full index / incremental sync
  ResourceManager — host admission / batching

MCP / CLI / dashboard are thin clients.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

from pipeline.engine import clear_engines, drop_engine, load_engine
from pipeline.index_manager import get_index_manager


def _daemon_version() -> str:
    """Return the installed scubiee version for the /health response."""
    try:
        from importlib.metadata import version

        return version("scubiee")
    except Exception:  # noqa: BLE001
        return "unknown"
from pipeline.registration import (
    is_always_allowed,
    is_registered,
    needs_registration_consent,
    register_project as do_register_project,
    registration_prompt_payload,
)
from pipeline.repo_runtime import RepoHub, RepoRuntime
from pipeline.settings import get_registration_mode, load_prefs, save_prefs
from pipeline.store import PipelineStore
from pipeline.sync_loop import (
    BackgroundSyncLoop,
    auto_index_enabled,
    enable_session_keeper_defaults,
)


class _RuntimePublisher:
    """Keeper callback that preserves the public ``publish_engine`` identity."""

    def __init__(self, manager: "RuntimeManager", runtime: RepoRuntime) -> None:
        self.manager = manager
        self.runtime = runtime

    def __call__(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.manager._publish_runtime(self.runtime, payload)

    def __eq__(self, other: object) -> bool:
        return other == self.manager.publish_engine


class RuntimeManager:
    """Process-local runtime: workspace, keeper, published search engine."""

    def __init__(self) -> None:
        self.hub = RepoHub()
        self._active_runtime: RepoRuntime | None = None
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
        self._admission_pauses: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self.index = get_index_manager()

    def _save_active_runtime(self) -> None:
        """Persist the legacy facade fields onto its repository runtime."""
        runtime = self._active_runtime
        if runtime is None:
            return
        runtime.repo = self.repo or runtime.repo
        runtime.engine = self.engine
        runtime.keeper = self.sync_loop
        runtime.warm_state = self.warm_state
        runtime.warming = self.warming
        runtime.indexing = self.indexing
        runtime.error = self.warm_error
        runtime.warm_ms = self.warm_ms
        runtime.generation = self.generation
        runtime.last_sync_at = self.last_sync_at

    def _load_runtime_facade(self, runtime: RepoRuntime) -> None:
        self._active_runtime = runtime
        self.repo = runtime.repo
        self.engine = runtime.engine
        self.sync_loop = runtime.keeper
        self.project_id = runtime.project_id
        self.warm_state = runtime.warm_state
        self.warming = runtime.warming
        self.indexing = runtime.indexing
        self.warm_error = runtime.error
        self.warm_ms = runtime.warm_ms
        self.generation = runtime.generation
        self.last_sync_at = runtime.last_sync_at

    def _activate_runtime(
        self,
        root: Path | str,
        *,
        client: str | None = None,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RepoRuntime:
        """Switch the compatible active facade without stopping other repos."""
        runtime = self.hub.ensure(
            Path(root).resolve(),
            client=client,
            session_id=session_id,
            metadata=metadata,
        )
        with self._lock:
            if self._active_runtime is not runtime:
                self._save_active_runtime()
                self._load_runtime_facade(runtime)
            runtime.touch(priority="active")
        return runtime

    @staticmethod
    def _auto_limits() -> tuple[int, int]:
        prefs = load_prefs()
        config = prefs.get("auto_admission")
        config = config if isinstance(config, dict) else {}

        def value(env_name: str, pref_name: str, default: int) -> int:
            raw = os.environ.get(env_name)
            if raw is None:
                raw = config.get(pref_name, default)
            try:
                return max(0, int(raw))
            except (TypeError, ValueError):
                return default

        return (
            value("CTX_AUTO_MAX_REPOS", "max_repositories", 8),
            value("CTX_AUTO_LARGE_REPO_FILES", "large_repo_files", 10_000),
        )

    @staticmethod
    def _repo_file_count(repo: Path, *, stop_after: int) -> int:
        count = 0
        ignored = {".git", ".scubiee", "__pycache__"}
        for _root, dirs, files in os.walk(repo):
            dirs[:] = [name for name in dirs if name not in ignored]
            count += len(files)
            if stop_after and count > stop_after:
                break
        return count

    def admit_request(
        self,
        root: Path | str,
        *,
        client: str | None = None,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        explicit: bool = False,
    ) -> dict[str, Any]:
        """Admit a path-bearing CE request without creating managed state."""
        from pipeline import repo_lifecycle as lifecycle

        repo = Path(root).resolve()
        admission = lifecycle.activate_repo(repo)
        status = str(admission.get("status") or admission.get("state") or "")
        if status != "activated":
            return {
                **admission,
                "status": status,
                "pause_reason": admission.get("pause_reason"),
                "client": client,
                "session_id": session_id,
                "session_authored": bool(session_id),
            }

        existing = self.hub.get(str(admission["project_id"]))
        max_repositories, large_repo_files = self._auto_limits()
        if existing is None and not explicit:
            file_count = self._repo_file_count(repo, stop_after=large_repo_files)
            if large_repo_files and file_count > large_repo_files:
                self._admission_pauses[str(repo)] = {
                    "reason": "large_repo",
                    "at": time.time(),
                    "file_count": file_count,
                }
                return {
                    **admission,
                    "ok": False,
                    "status": "paused",
                    "pause_reason": "large_repo",
                    "file_count": file_count,
                    "large_repo_files": large_repo_files,
                    "client": client,
                    "session_id": session_id,
                    "session_authored": bool(session_id),
                }
            auto_count = sum(
                1
                for item in self.hub.list_status()
                if item.get("auto_admitted")
            )
            if max_repositories and auto_count >= max_repositories:
                self._admission_pauses[str(repo)] = {
                    "reason": "auto_limit",
                    "at": time.time(),
                    "auto_limit": max_repositories,
                }
                return {
                    **admission,
                    "ok": False,
                    "status": "paused",
                    "pause_reason": "auto_limit",
                    "auto_limit": max_repositories,
                    "client": client,
                    "session_id": session_id,
                    "session_authored": bool(session_id),
                }

        runtime = self._activate_runtime(
            repo,
            client=client,
            session_id=session_id,
            metadata=metadata,
        )
        self._admission_pauses.pop(str(repo), None)
        runtime.auto_admitted = True
        if session_id:
            from pipeline.session_store import record_session_metadata

            session = record_session_metadata(
                repo,
                session_id,
                client=client,
                metadata=metadata,
            )
        else:
            session = None

        if runtime.engine is None and runtime.warm_state != "ready":
            opened = self._warm_registered(repo)
        else:
            opened = {
                "ok": True,
                "repo": str(repo),
                "project_id": runtime.project_id,
                "warm_state": runtime.warm_state,
                "reused": True,
            }
        self._save_active_runtime()
        return {
            **admission,
            "status": "activated",
            "open": opened,
            "client": client,
            "session_id": session_id,
            "session": session,
            "session_authored": bool(session_id),
            "runtime_shared": existing is not None,
        }

    def end_session(self, root: Path | str, session_id: str) -> dict[str, Any]:
        """End one session without idling a repository used by another."""
        from pipeline import repo_lifecycle as lifecycle

        repo = Path(root).resolve()
        lifecycle_data = lifecycle.lifecycle_status(repo)
        project_id = lifecycle_data.get("project_id")
        runtime = self.hub.get(str(project_id)) if project_id else None
        if runtime is None:
            return {
                "ok": False,
                "status": "not_active",
                "repo": str(repo),
                "session_id": session_id,
                "remaining_sessions": 0,
            }
        remaining = runtime.end_session(session_id)
        from pipeline.session_store import end_session as end_stored_session

        end_stored_session(repo, session_id)
        return {
            "ok": True,
            "status": "ended",
            "repo": str(repo),
            "project_id": runtime.project_id,
            "session_id": session_id,
            "remaining_sessions": remaining,
            "runtime_active": runtime.project_id in {
                item["project_id"] for item in self.hub.list_status()
            },
        }

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
                drop_engine(repo)
                eng = load_engine(repo, force_reload=True)
                self.engine = eng
                self.generation += 1
                self.last_sync_at = time.time()
                self.warm_state = "ready"
                self.warm_error = None
                self._save_active_runtime()
                return {
                    "ok": True,
                    "generation": self.generation,
                    "last_sync_at": self.last_sync_at,
                    "chunks": len(eng.texts),
                    "payload": payload,
                }
            except Exception as exc:  # noqa: BLE001
                self.warm_error = str(exc)
                if self.project_id:
                    self.hub.isolate_failure(self.project_id, exc)
                self._save_active_runtime()
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
            "service": "scubiee",
            "version": _daemon_version(),
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
            from pipeline.repo_lifecycle import activate_repo

            admission = activate_repo(root)
            if admission.get("status") != "activated":
                return admission
            self._activate_runtime(root)
            self.warm_error = None
            return self._warm_registered(root)

    def _should_start_keeper(self) -> bool:
        prefs = load_prefs()
        return bool(prefs.get("incremental_indexing", True) or prefs.get("file_watching", True))

    def _start_keeper(self, repo: Path) -> None:
        if not self._should_start_keeper():
            return
        if self.sync_loop and self.sync_loop.running:
            return
        runtime = self._active_runtime
        if runtime is None or runtime.repo != repo.resolve():
            runtime = self._activate_runtime(repo)
        loop = BackgroundSyncLoop(repo, on_refresh=_RuntimePublisher(self, runtime))
        loop.start()
        self.sync_loop = loop
        self._save_active_runtime()

    def _publish_runtime(self, runtime: RepoRuntime, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Publish from a keeper without changing another repository's facade."""
        try:
            drop_engine(runtime.repo)
            engine = load_engine(runtime.repo, force_reload=True)
            runtime.engine = engine
            runtime.generation += 1
            runtime.last_sync_at = time.time()
            runtime.warm_state = "ready"
            runtime.error = None
            if self._active_runtime is runtime:
                self._load_runtime_facade(runtime)
            try:
                from pipeline.storage_policy import compact_collection

                compact_collection(runtime.project_id, force=False)
            except Exception:  # noqa: BLE001
                pass
            return {
                "ok": True,
                "generation": runtime.generation,
                "last_sync_at": runtime.last_sync_at,
                "chunks": len(engine.texts),
                "payload": payload,
            }
        except Exception as exc:  # noqa: BLE001
            self.hub.isolate_failure(runtime.project_id, exc)
            return {"ok": False, "error": str(exc), "generation": runtime.generation}

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
                from pipeline.incremental import IndexConfirmRequired, preflight_index_scope

                try:
                    preflight_index_scope(root, fast=False, confirm=False, force=False)
                except IndexConfirmRequired as exc:
                    self.warming = False
                    self.warm_state = "needs_confirm"
                    self.warm_error = str(exc)
                    payload = exc.to_payload(root)
                    payload.update(
                        {
                            "warm_state": "needs_confirm",
                            "file_count": exc.n_files,
                        }
                    )
                    return payload
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
                raise RuntimeError("No index found. Run: scubiee register .  or  scubiee index .")

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
        self._save_active_runtime()
        for item in self.hub.list_status():
            runtime = self.hub.get(str(item["project_id"]))
            if runtime and runtime.keeper:
                try:
                    runtime.keeper.final_check(reason="shutdown")
                except Exception:  # noqa: BLE001
                    pass
                runtime.keeper.stop()
                runtime.keeper = None
        clear_engines()
        self.engine = None

    # --- API ---------------------------------------------------------------

    def status(self, root: Path | str | None = None) -> dict[str, Any]:
        repo = Path(root).resolve() if root else (self.repo or Path.cwd())
        from pipeline.repo_lifecycle import UNMANAGED, lifecycle_status

        lifecycle = lifecycle_status(repo)
        admission_pause = self._admission_pauses.get(str(repo)) or {}
        project_id = lifecycle.get("project_id")
        runtime = self.hub.get(str(project_id)) if project_id else None
        keeper = runtime.keeper if runtime else None
        keeper_status = keeper.status() if keeper else None
        dirty = (
            keeper_status.get("dirty")
            if isinstance(keeper_status, dict)
            else {"paths": {}}
        )
        if not isinstance(dirty, dict):
            dirty = {"paths": {}}
        dirty_paths = dirty.get("paths")
        dirty_paths = dirty_paths if isinstance(dirty_paths, dict) else {}
        current_files = sorted(str(path) for path in dirty_paths)

        try:
            from pipeline.fair_schedule import get_embed_scheduler

            scheduler_queue = get_embed_scheduler().status()
            scheduler_queue.setdefault(
                "queue_depth", int(scheduler_queue.get("queued") or 0)
            )
            scheduler_queue.setdefault(
                "waiting", list(scheduler_queue.get("queue") or [])
            )
        except Exception:  # noqa: BLE001
            scheduler_queue = {
                "holder": None,
                "queue_depth": 0,
                "waiting": [],
                "served": {},
            }

        storage_bytes: dict[str, Any] = {
            "project_id": project_id,
            "store_bytes": 0,
            "vector_bytes": 0,
            "bytes_used": 0,
            "reclaimable_bytes": 0,
        }
        if project_id:
            try:
                from pipeline.storage_policy import repo_storage_status

                storage_bytes = repo_storage_status(str(project_id))
            except Exception as exc:  # noqa: BLE001
                storage_bytes["error"] = str(exc)

        session_rows = []
        if runtime:
            session_rows = [
                dict(runtime.session_metadata[session_id])
                for session_id in sorted(runtime.sessions)
                if session_id in runtime.session_metadata
            ]
        timestamps = dict(lifecycle.get("timestamps") or {})
        timestamps.update(
            {
                "last_activity_at": runtime.last_activity_at if runtime else None,
                "last_runtime_sync_at": runtime.last_sync_at if runtime else None,
                "admission_paused_at": admission_pause.get("at"),
            }
        )
        prefs = load_prefs()
        payload: dict[str, Any] = {
            "ok": True,
            "service": "scubiee",
            "repo": str(repo),
            "lifecycle": lifecycle["state"],
            "registration_mode": get_registration_mode(),
            "registered": is_registered(repo),
            "always_allow": is_always_allowed(repo),
            "project_id": project_id,
            "warm_state": runtime.warm_state if runtime else "idle",
            "warming": runtime.warming if runtime else False,
            "indexing": runtime.indexing if runtime else False,
            "warm_error": runtime.error if runtime else None,
            "warm_ms": runtime.warm_ms if runtime else None,
            "generation": runtime.generation if runtime else 0,
            "last_sync_at": runtime.last_sync_at if runtime else None,
            "prefs": {
                "registration_mode": prefs.get("registration_mode"),
                "incremental_indexing": prefs.get("incremental_indexing"),
                "file_watching": prefs.get("file_watching"),
                "auto_admission": prefs.get("auto_admission"),
            },
            "engine": runtime.engine.status() if runtime and runtime.engine else None,
            "keeper": keeper_status,
            "repositories": self.hub.list_status(),
            "sessions": session_rows,
            "dirty": dirty,
            "pending": {
                "dirty_count": len(dirty_paths),
                "publish": bool(
                    keeper_status.get("publish_pending")
                    if isinstance(keeper_status, dict)
                    else False
                ),
                "sync_status": (
                    keeper_status.get("sync_status")
                    if isinstance(keeper_status, dict)
                    else "idle"
                ),
            },
            "scheduler_queue": scheduler_queue,
            "current_files": current_files,
            "pause_reason": admission_pause.get("reason")
            or lifecycle.get("pause_reason"),
            "timestamps": timestamps,
            "storage_bytes": storage_bytes,
        }
        try:
            from pipeline.resources import get_resource_manager

            payload["resources"] = get_resource_manager().status()
        except Exception:  # noqa: BLE001
            payload["resources"] = None
        from pipeline.runtime_profile import get_runtime_profile_state

        profile_state = get_runtime_profile_state()
        resource_status = payload["resources"]
        envelope = (
            resource_status.get("envelope")
            if isinstance(resource_status, dict)
            else None
        )
        payload.update(
            {
                "preferred_profile": profile_state.preferred_profile,
                "active_profile": profile_state.active_profile,
                "backup_reason": profile_state.backup_reason,
                "envelope": envelope,
                "recommended_command": (
                    "python -m pipeline setup --repair"
                    if profile_state.backup_reason
                    else "python -m pipeline serve"
                ),
            }
        )

        if lifecycle["state"] == UNMANAGED:
            payload["needs_registration"] = registration_prompt_payload(repo)
            return payload

        try:
            store = PipelineStore(repo)
            payload["project_id"] = project_id or store.project_id
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
                keeper.last_result if keeper else None
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
        # Laptop safety: never feed unbounded text into the GPU embed path.
        q = (query or "").strip()
        if not q:
            return {"ok": False, "error": "query required", "hits": []}
        max_q = int(os.environ.get("CTX_QUERY_MAX_CHARS", "2000") or "2000")
        if len(q) > max_q:
            q = q[:max_q]
        eng = self._ensure_engine(root)
        if eng is None:
            return {"status": "warming", "ready": False, "warm_state": self.warm_state}
        try:
            hits = eng.search(q, top_k=top_k, skip_freshness=True)
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "error": f"search failed: {exc}",
                "query": q,
                "hits": [],
                "hint": "Retry once; if persistent run: scubiee engine ensure .",
            }
        return {
            "ok": True,
            "query": q,
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

    def sync(
        self, root: Path | str | None = None, *, confirm: bool = False
    ) -> dict[str, Any]:
        gate = self._gate(root)
        if gate:
            return gate
        repo = Path(root).resolve() if root else (self.repo or Path.cwd())
        self._activate_runtime(repo)
        out = self.index.sync(repo, confirm=confirm)
        if out.get("refreshed"):
            pub = self.publish_engine()
            out["published"] = pub
            out["generation"] = self.generation
        return out

    def publish(self, root: Path | str | None = None, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Reload search after an out-of-process index/sync wrote new artifacts."""
        gate = self._gate(root)
        if gate:
            return gate
        repo = Path(root).resolve() if root else (self.repo or Path.cwd())
        self._activate_runtime(repo)
        return self.publish_engine(payload)

    def grep(
        self, pattern: str, *, glob: str = "**/*", max_hits: int = 200, root: Path | str | None = None
    ) -> dict[str, Any]:
        gate = self._gate(root)
        if gate:
            return gate
        from pipeline.capability import grep_scan

        repo = Path(root).resolve() if root else (self.repo or Path.cwd())
        t0 = time.perf_counter()
        report = grep_scan(repo, pattern, glob=glob, max_hits=max_hits)
        return {
            "ok": True,
            "pattern": pattern,
            "glob": glob,
            "ms": round((time.perf_counter() - t0) * 1000, 2),
            "hits": report["hits"],
            "count": report["count"],
            "truncated": report["truncated"],
            "has_more": report["has_more"],
            "max_hits": report["max_hits"],
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
        symbols = file_outline(repo, rel)
        out: dict[str, Any] = {"ok": True, "path": rel, "symbols": symbols}
        suffix = Path(rel).suffix.lower()
        if suffix not in {".py", ".pyi"}:
            out["language_unsupported"] = True
            out["note"] = "outline is Python AST only; use focus(mode=span) for this file."
        return out

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
            "auto_admission",
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
        repo = Path(root).resolve() if root else self.repo
        if repo is None:
            return None
        with self._lock:
            runtime = self._activate_runtime(repo)
            if runtime.engine is not None:
                return runtime.engine
            if runtime.warm_state == "awaiting_registration":
                return None
            try:
                eng = load_engine(repo)
                runtime.engine = eng
                runtime.warm_state = "ready"
                if runtime.generation == 0:
                    runtime.generation = 1
                self._load_runtime_facade(runtime)
                return runtime.engine
            except Exception as exc:  # noqa: BLE001
                if runtime.project_id:
                    self.hub.isolate_failure(runtime.project_id, exc)
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
