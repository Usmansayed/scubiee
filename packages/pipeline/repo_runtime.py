"""Repository-scoped daemon state shared by every session for that repository."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline.project_id import resolve_project


@dataclass
class RepoRuntime:
    """Mutable state owned by exactly one managed repository."""

    project_id: str
    repo: Path
    engine: Any = None
    keeper: Any = None
    sessions: set[str] = field(default_factory=set)
    session_metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_activity_at: float = field(default_factory=time.time)
    error: str | None = None
    generation: int = 0
    priority: str = "idle"
    warm_state: str = "idle"
    warming: bool = False
    indexing: bool = False
    warm_ms: float | None = None
    last_sync_at: float | None = None
    auto_admitted: bool = False

    def touch(
        self,
        session_id: str | None = None,
        *,
        client: str | None = None,
        metadata: dict[str, Any] | None = None,
        priority: str = "active",
    ) -> None:
        now = time.time()
        if session_id:
            self.sessions.add(session_id)
            current = dict(self.session_metadata.get(session_id) or {})
            current.setdefault("started_at", now)
            current.update(metadata or {})
            current.update(
                {
                    "session_id": session_id,
                    "client": client or current.get("client"),
                    "last_seen_at": now,
                    "session_authored": True,
                }
            )
            self.session_metadata[session_id] = current
        self.last_activity_at = now
        self.priority = priority

    def end_session(self, session_id: str) -> int:
        self.sessions.discard(session_id)
        metadata = self.session_metadata.get(session_id)
        if metadata is not None:
            metadata["ended_at"] = time.time()
        if not self.sessions:
            self.priority = "idle"
        return len(self.sessions)

    def status(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "repo": str(self.repo),
            "sessions": len(self.sessions),
            "session_ids": sorted(self.sessions),
            "session_metadata": {
                session_id: dict(self.session_metadata[session_id])
                for session_id in sorted(self.sessions)
                if session_id in self.session_metadata
            },
            "last_activity_at": self.last_activity_at,
            "error": self.error,
            "generation": self.generation,
            "priority": self.priority,
            "warm_state": self.warm_state,
            "warming": self.warming,
            "indexing": self.indexing,
            "last_sync_at": self.last_sync_at,
            "auto_admitted": self.auto_admitted,
        }


class RepoHub:
    """Thread-safe registry of isolated repository runtimes."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._runtimes: dict[str, RepoRuntime] = {}

    def ensure(
        self,
        root: Path | str,
        *,
        session_id: str | None = None,
        client: str | None = None,
        metadata: dict[str, Any] | None = None,
        priority: str = "active",
    ) -> RepoRuntime:
        ref = resolve_project(Path(root).resolve())
        with self._lock:
            runtime = self._runtimes.get(ref.project_id)
            if runtime is None:
                runtime = RepoRuntime(ref.project_id, ref.root)
                self._runtimes[ref.project_id] = runtime
            else:
                runtime.repo = ref.root
            runtime.touch(
                session_id,
                client=client,
                metadata=metadata,
                priority=priority,
            )
            return runtime

    def get(self, project_id: str) -> RepoRuntime | None:
        with self._lock:
            return self._runtimes.get(project_id)

    def drop(self, project_id: str) -> RepoRuntime | None:
        with self._lock:
            return self._runtimes.pop(project_id, None)

    def list_status(self) -> list[dict[str, Any]]:
        with self._lock:
            return [runtime.status() for runtime in self._runtimes.values()]

    def isolate_failure(self, project_id: str, error: Exception | str) -> None:
        with self._lock:
            runtime = self._runtimes.get(project_id)
            if runtime is None:
                return
            runtime.error = str(error)
            runtime.warm_state = "error"
            runtime.warming = False
            runtime.indexing = False
