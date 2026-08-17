"""Durable journal for dirty-path state across keeper restarts."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from pipeline.artifact_guard import atomic_write_text
from pipeline.dirty_ledger import DirtyLedger
from pipeline.project_id import projects_root


JOURNAL_NAME = "dirty_journal.json"


def _journal_path(project_id: str) -> Path:
    return projects_root() / project_id / JOURNAL_NAME


def save_dirty_journal(project_id: str, snapshot: dict[str, Any]) -> None:
    """Atomically persist a ledger snapshot in the project's durable store."""
    document = {
        "version": 1,
        "saved_at": time.time(),
        "snapshot": snapshot,
    }
    atomic_write_text(
        _journal_path(project_id),
        json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
    )


def load_dirty_journal(project_id: str) -> dict[str, Any] | None:
    """Load a journal document, reporting corruption without raising."""
    path = _journal_path(project_id)
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"ok": False, "reason": "corrupt", "error": str(exc)}
    if not isinstance(document, dict) or not isinstance(document.get("snapshot"), dict):
        return {
            "ok": False,
            "reason": "corrupt",
            "error": "journal must contain an object snapshot",
        }
    return document


def clear_dirty_journal(project_id: str) -> None:
    """Remove a project's dirty journal if one exists."""
    _journal_path(project_id).unlink(missing_ok=True)


def restore_ledger_from_journal(
    ledger: DirtyLedger,
    project_id: str,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Replay all non-published paths as immediately due.

    A missing or corrupt journal leaves the ledger empty so the root/Merkle
    probe can reconstruct dirty paths on the next reconciliation.
    """
    current_time = time.monotonic() if now is None else now
    document = load_dirty_journal(project_id)
    if document is None:
        return {
            "ok": True,
            "reason": "missing",
            "restored": 0,
            "dropped_published": 0,
        }
    if document.get("ok") is False:
        return {
            **document,
            "restored": 0,
            "dropped_published": 0,
        }

    paths = (document.get("snapshot") or {}).get("paths") or {}
    if not isinstance(paths, dict):
        return {
            "ok": False,
            "reason": "corrupt",
            "error": "snapshot paths must be an object",
            "restored": 0,
            "dropped_published": 0,
        }

    restored = 0
    dropped = 0
    for path, raw_entry in paths.items():
        if not isinstance(path, str) or not isinstance(raw_entry, dict):
            continue
        if raw_entry.get("state") == "published":
            dropped += 1
            continue
        reason = str(raw_entry.get("reason") or "journal_restore")
        # DirtyLedger adds its debounce to `now`; offset it so the replay is
        # eligible immediately while retaining the ledger's public API.
        replay_time = current_time - ledger.debounce_ms / 1000
        ledger.mark([path], reason=reason, now=replay_time)
        restored += 1

    return {
        "ok": True,
        "reason": "restored",
        "restored": restored,
        "dropped_published": dropped,
    }


class JournalingLedger:
    """Serialize DirtyLedger mutations with an atomic journal snapshot."""

    def __init__(
        self,
        project_id: str,
        ledger: DirtyLedger | None = None,
        *,
        now: float | None = None,
    ) -> None:
        self.project_id = project_id
        self.ledger = ledger or DirtyLedger()
        self._journal_lock = threading.RLock()
        self.restore_result = restore_ledger_from_journal(
            self.ledger,
            project_id,
            now=now,
        )
        if self.restore_result.get("restored") or self.restore_result.get("dropped_published"):
            self._persist()

    @property
    def debounce_ms(self) -> int:
        return self.ledger.debounce_ms

    @property
    def rewrite_debounce_ms(self) -> int:
        return self.ledger.rewrite_debounce_ms

    def _persist(self) -> None:
        save_dirty_journal(self.project_id, self.ledger.snapshot())

    def snapshot(self) -> dict[str, Any]:
        with self._journal_lock:
            return self.ledger.snapshot()

    def mark(
        self,
        paths: Iterable[str],
        *,
        reason: str,
        now: float | None = None,
    ) -> None:
        with self._journal_lock:
            self.ledger.mark(paths, reason=reason, now=now)
            self._persist()

    def due_paths(self, *, now: float | None = None) -> list[str]:
        with self._journal_lock:
            paths = self.ledger.due_paths(now=now)
            if paths:
                self._persist()
            return paths

    def defer(self, paths: Iterable[str], *, now: float | None = None) -> None:
        with self._journal_lock:
            self.ledger.defer(paths, now=now)
            self._persist()

    def force_due(self) -> list[str]:
        with self._journal_lock:
            paths = self.ledger.force_due()
            if paths:
                self._persist()
            return paths

    def begin(self, paths: Iterable[str]) -> None:
        with self._journal_lock:
            self.ledger.begin(paths)
            self._persist()

    def complete(self, paths: Iterable[str], *, published: bool) -> None:
        with self._journal_lock:
            self.ledger.complete(paths, published=published)
            self._persist()
