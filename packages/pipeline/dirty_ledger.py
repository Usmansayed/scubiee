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


# A human or an agent just wrote this file and is waiting on it. These reasons
# get the short (hot) debounce and the hot publish lane; ``disk_poll``/bulk
# discovery keeps the long debounce so editor save bursts still coalesce.
HOT_SYNC_REASONS: frozenset[str] = frozenset(
    {
        "write",
        "changed_file",
        "editor_save",
        "probe_write",
        "after_kiro_write",
        "watch",
    }
)

DEFAULT_HOT_DEBOUNCE_MS = 250


def hot_debounce_ms_default() -> int:
    """``CTX_HOT_DEBOUNCE_MS`` (default 250) — read per call so tests can set it."""
    raw = (os.environ.get("CTX_HOT_DEBOUNCE_MS") or "").strip()
    try:
        value = int(raw) if raw else DEFAULT_HOT_DEBOUNCE_MS
    except ValueError:
        value = DEFAULT_HOT_DEBOUNCE_MS
    return max(0, value)


def is_hot_reason(reason: str | None) -> bool:
    return str(reason or "") in HOT_SYNC_REASONS


@dataclass
class DirtyEntry:
    path: str
    reason: str
    state: str = "queued"
    due_at: float = 0.0
    rewrites: int = 0
    processing_since: float = 0.0
    # Monotonic timestamp of the most recent mark — the moment the user's save
    # started waiting. Used to report the debounce stage of the save→map budget.
    marked_at: float = 0.0


class DirtyLedger:
    """Coalesce changed paths and track their processing/publication state."""

    def __init__(
        self,
        *,
        debounce_ms: int = 1000,
        rewrite_debounce_ms: int = 2000,
        hot_debounce_ms: int | None = None,
    ) -> None:
        self.debounce_ms = debounce_ms
        self.rewrite_debounce_ms = rewrite_debounce_ms
        self.hot_debounce_ms = (
            hot_debounce_ms_default() if hot_debounce_ms is None else max(0, int(hot_debounce_ms))
        )
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
        # A save the user is waiting on cannot sit behind a 1s debounce and then
        # a 2s rewrite slide — that alone eats most of the 5s map budget. Hot
        # reasons use the short debounce for both the first mark and any rewrite,
        # so repeated agent saves can never push the due time past the SLA.
        hot = is_hot_reason(reason)
        # The hot lane is a floor, never a ceiling: a caller that asked for a
        # shorter debounce (tests, `--now` style flushes) keeps it.
        hot_first_delay = min(self.hot_debounce_ms, self.debounce_ms) / 1000
        hot_rewrite_delay = min(self.hot_debounce_ms, self.rewrite_debounce_ms) / 1000
        first_delay = hot_first_delay if hot else self.debounce_ms / 1000
        with self._lock:
            for path in paths:
                key = normalize_dirty_path(path)
                entry = self._entries.get(key)
                if entry is None or entry.state != "queued":
                    self._entries[key] = DirtyEntry(
                        path=path.replace("\\", "/"),
                        reason=reason,
                        due_at=current_time + first_delay,
                        marked_at=current_time,
                    )
                    continue

                entry.rewrites += 1
                entry.marked_at = current_time
                if hot:
                    # An editor's atomic save is a burst (write + rename), so the
                    # quiet window still restarts from the *last* event — but on
                    # the hot budget, not the 2s bulk one, or the save cannot
                    # reach map inside 5s.
                    entry.reason = reason
                    entry.due_at = current_time + hot_rewrite_delay
                elif is_hot_reason(entry.reason):
                    # A background poll re-reporting a file the user just saved
                    # must not delay it, and must not steal the hot lane.
                    entry.due_at = min(entry.due_at, current_time + hot_rewrite_delay)
                else:
                    entry.reason = reason
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
