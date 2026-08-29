"""Thread-safe bookkeeping for debounced incremental index updates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
import threading
import time
from typing import Any, Iterable


def normalize_dirty_path(path: str) -> str:
    """Canonical ledger key: forward slashes; casefold on Windows."""
    p = (path or "").replace("\\", "/").lstrip("./")
    if os.name == "nt":
        return p.casefold()
    return p


@dataclass
class DirtyEntry:
    path: str
    reason: str
    state: str = "queued"
    due_at: float = 0.0
    rewrites: int = 0
    processing_since: float = 0.0


class DirtyLedger:
    """Coalesce changed paths and track their processing/publication state."""

    def __init__(
        self,
        *,
        debounce_ms: int = 1500,
        rewrite_debounce_ms: int = 2500,
    ) -> None:
        self.debounce_ms = debounce_ms
        self.rewrite_debounce_ms = rewrite_debounce_ms
        self._entries: dict[str, DirtyEntry] = {}
        self._lock = threading.Lock()

    def mark(
        self,
        paths: Iterable[str],
        *,
        reason: str,
        now: float | None = None,
    ) -> None:
        current_time = time.monotonic() if now is None else now
        with self._lock:
            for path in paths:
                key = normalize_dirty_path(path)
                entry = self._entries.get(key)
                if entry is None or entry.state != "queued":
                    self._entries[key] = DirtyEntry(
                        path=path.replace("\\", "/"),
                        reason=reason,
                        due_at=current_time + self.debounce_ms / 1000,
                    )
                    continue

                entry.reason = reason
                entry.rewrites += 1
                entry.due_at = current_time + self.rewrite_debounce_ms / 1000

    def due_paths(self, *, now: float | None = None) -> list[str]:
        current_time = time.monotonic() if now is None else now
        with self._lock:
            paths = [
                entry.path
                for entry in self._entries.values()
                if entry.state == "queued" and entry.due_at <= current_time
            ]
            for entry in self._entries.values():
                if entry.state == "queued" and entry.due_at <= current_time:
                    entry.state = "due"
            return paths

    def defer(self, paths: Iterable[str], *, now: float | None = None) -> None:
        """Return unprocessed paths to the queue without scheduling a full index."""
        current_time = time.monotonic() if now is None else now
        with self._lock:
            for path in paths:
                entry = self._entries.get(normalize_dirty_path(path))
                if entry is not None:
                    entry.state = "queued"
                    entry.due_at = current_time

    def force_due(self) -> list[str]:
        """Make queued paths available for the final shutdown drain."""
        with self._lock:
            paths = [entry.path for entry in self._entries.values() if entry.state == "queued"]
            for entry in self._entries.values():
                if entry.state == "queued":
                    entry.due_at = 0.0
            return paths

    def begin(self, paths: Iterable[str]) -> None:
        current_time = time.monotonic()
        with self._lock:
            for path in paths:
                key = normalize_dirty_path(path)
                entry = self._entries.get(key)
                if entry is not None:
                    entry.state = "processing"
                    entry.processing_since = current_time

    def complete(self, paths: Iterable[str], *, published: bool) -> None:
        state = "published" if published else "overlay_ready"
        with self._lock:
            for path in paths:
                key = normalize_dirty_path(path)
                entry = self._entries.get(key)
                if entry is not None:
                    entry.state = state
                    entry.processing_since = 0.0

    def recover_stale_processing(self, *, max_age_s: float = 90.0, now: float | None = None) -> list[str]:
        """Reset paths stuck in processing (crash/hang) back to queued."""
        current_time = time.monotonic() if now is None else now
        recovered: list[str] = []
        with self._lock:
            for key, entry in self._entries.items():
                if entry.state != "processing":
                    continue
                since = float(entry.processing_since or 0.0)
                if since <= 0.0 or current_time - since >= max_age_s:
                    entry.state = "queued"
                    entry.due_at = current_time
                    entry.processing_since = 0.0
                    recovered.append(entry.path)
        return recovered

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "paths": {
                    path: asdict(entry) for path, entry in self._entries.items()
                }
            }
