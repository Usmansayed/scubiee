"""Keeper sync loop — Cursor/Claude Context session lifecycle.

CE_LIVE_PROBE_20260818_mcp_verify

While MCP / ``ctx serve`` is open: periodic root-hash probe → incremental sync
only when dirty. On cwd switch or process exit: one final check, then stop.
"""

from __future__ import annotations

import atexit
import os
import sys
import threading
import time
from pathlib import Path
from typing import Iterable

from pipeline.dirty_journal import JournalingLedger
from pipeline.dirty_ledger import DirtyLedger
from pipeline.project_id import resolve_project
from pipeline.sync_status import derive_sync_status

DEFAULT_INTERVAL_MS = int(os.environ.get("CTX_SYNC_INTERVAL_MS", str(5 * 60 * 1000)))
DEFAULT_INITIAL_DELAY_MS = int(os.environ.get("CTX_SYNC_INITIAL_DELAY_MS", "5000"))
DEFAULT_DEBOUNCE_MS = int(os.environ.get("CTX_DEBOUNCE_MS", "1500"))
DEFAULT_REWRITE_DEBOUNCE_MS = int(os.environ.get("CTX_REWRITE_DEBOUNCE_MS", "2500"))
DEFAULT_LOCATE_STREAK_MS = int(os.environ.get("CTX_LOCATE_STREAK_MS", "8000"))
DEFAULT_LIVE_MAX_FILES = int(os.environ.get("CTX_LIVE_MAX_FILES", "40"))
DEFAULT_LIVE_MAX_CHUNKS = int(os.environ.get("CTX_LIVE_MAX_CHUNKS", "100"))
DEFAULT_CHANGE_POLL_MS = int(os.environ.get("CTX_CHANGE_POLL_MS", "1000"))
DEFAULT_WAKE_GAP_MS = int(os.environ.get("CTX_WAKE_GAP_MS", "30000"))
TRIGGER_NAME = ".sync-trigger"

# Process-wide registry for atexit final_check
_ACTIVE_LOOPS: list["BackgroundSyncLoop"] = []
_ATEXIT_REGISTERED = False


def enable_session_keeper_defaults() -> None:
    """MCP / serve entrypoints: turn keeper + auto-index on unless user set env."""
    os.environ.setdefault("CTX_BACKGROUND_SYNC", "1")
    os.environ.setdefault("CTX_ALLOW_BG_FULL", "0")
    os.environ.setdefault("CTX_AUTO_INDEX", "1")
    os.environ.setdefault("CTX_SYNC_INTERVAL_MS", str(5 * 60 * 1000))
    os.environ.setdefault("CTX_CHANGE_POLL_MS", "1000")


def auto_index_enabled() -> bool:
    return os.environ.get("CTX_AUTO_INDEX", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _register_atexit() -> None:
    global _ATEXIT_REGISTERED
    if _ATEXIT_REGISTERED:
        return
    _ATEXIT_REGISTERED = True

    def _on_exit() -> None:
        for loop in list(_ACTIVE_LOOPS):
            try:
                loop.final_check(reason="process_exit")
            except Exception as exc:  # noqa: BLE001
                print(f"[keeper] final_check on exit failed: {exc}", file=sys.stderr, flush=True)
            try:
                loop.stop()
            except Exception:  # noqa: BLE001
                pass

    atexit.register(_on_exit)


class BackgroundSyncLoop:
    """Periodic root-probe + incremental_sync; final_check on stop/cwd/exit."""

    def __init__(
        self,
        repo: Path,
        *,
        interval_ms: int = DEFAULT_INTERVAL_MS,
        on_refresh=None,
        debounce_ms: int = DEFAULT_DEBOUNCE_MS,
        rewrite_debounce_ms: int = DEFAULT_REWRITE_DEBOUNCE_MS,
        locate_streak_ms: int = DEFAULT_LOCATE_STREAK_MS,
        live_max_files: int = DEFAULT_LIVE_MAX_FILES,
        live_max_chunks: int = DEFAULT_LIVE_MAX_CHUNKS,
        change_poll_ms: int = DEFAULT_CHANGE_POLL_MS,
        wake_gap_ms: int = DEFAULT_WAKE_GAP_MS,
    ):
        self.repo = repo.resolve()
        self.project_id = resolve_project(self.repo).project_id
        self.interval_ms = max(1000, interval_ms)
        self.on_refresh = on_refresh
        self.locate_streak_ms = max(0, locate_streak_ms)
        self.live_max_files = max(1, live_max_files)
        self.live_max_chunks = max(1, live_max_chunks)
        self.change_poll_ms = max(250, change_poll_ms)
        self.wake_gap_ms = max(1000, wake_gap_ms)
        self.dirty_ledger = JournalingLedger(
            self.project_id,
            DirtyLedger(
                debounce_ms=debounce_ms,
                rewrite_debounce_ms=rewrite_debounce_ms,
            ),
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._syncing = False
        self._lock = threading.Lock()
        self._last_locate_at: float | None = None
        self._pending_publish: dict | None = None
        self._pending_paths: set[str] = set()
        self.last_result: dict | None = None
        self.last_probe: dict | None = None
        self.needs_full = False
        self.catchup_chunked = False
        self.live_batches = 0
        self.live_invalidations = 0
        self.running = False
        self._last_clock_at: float | None = None
        self._watcher_restart_count = 0
        self._watcher_last_reconcile: float | None = None
        self._watcher_last_wake_reconcile: float | None = None
        self._watcher_last_error: str | None = None

    def status(self) -> dict:
        dirty = self.dirty_ledger.snapshot()
        states = [entry["state"] for entry in dirty["paths"].values()]
        sync_status = derive_sync_status(
            dirty=dirty,
            syncing=self._syncing,
            publish_pending=self._pending_publish is not None,
            needs_full=self.needs_full,
            catchup_chunked=self.catchup_chunked,
            last_result=self.last_result,
        )
        return {
            "running": bool(self.running and self._thread and self._thread.is_alive()),
            "repo": str(self.repo),
            "project_id": self.project_id,
            "interval_ms": self.interval_ms,
            "last_probe": self.last_probe,
            "last_sync": self.last_result,
            "dirty": dirty,
            "overlay_ready": "overlay_ready" in states,
            "publish_pending": self._pending_publish is not None,
            "locate_streak_active": self._locate_streak_active(),
            "live_max_files": self.live_max_files,
            "live_max_chunks": self.live_max_chunks,
            "needs_full": self.needs_full,
            "catchup_chunked": self.catchup_chunked,
            "live_batches": self.live_batches,
            "session_invalidations": self.live_invalidations,
            "sync_status": sync_status,
            "journal_restore": self.dirty_ledger.restore_result,
            "watcher": {
                "restart_count": self._watcher_restart_count,
                "last_reconcile": self._watcher_last_reconcile,
                "last_wake_reconcile": self._watcher_last_wake_reconcile,
                "last_error": self._watcher_last_error,
            },
        }

    def mark_dirty(
        self,
        paths: Iterable[str],
        *,
        reason: str = "write",
        now: float | None = None,
    ) -> None:
        # An edit ends the locate streak: process+publish freshness beats mid-thought
        # stability once the agent has changed disk.
        if str(reason) in {"write", "disk_poll", "changed_file", "editor_save", "probe_write", "after_kiro_write", "watch"}:
            self._last_locate_at = None
        self.dirty_ledger.mark(paths, reason=reason, now=now)

    def note_locate(self, *, now: float | None = None) -> None:
        self._last_locate_at = time.monotonic() if now is None else now

    def poll_repo_changes(self, *, now: float | None = None) -> list[str]:
        """Cheap disk poll → enqueue changed paths for the debounced live path.

        This is the agent-write producer: Kiro/Cursor edits do not need to call
        /v1/dirty explicitly. The 5-minute keeper tick remains the backup.
        """
        from pipeline.root_probe import root_probe

        current_time = time.monotonic() if now is None else now
        try:
            probe = root_probe(self.repo)
        except Exception as exc:  # noqa: BLE001
            print(f"[keeper] change poll failed: {exc}", file=sys.stderr, flush=True)
            return []
        if probe.clean:
            return []
        paths = sorted(
            {
                str(p).replace("\\", "/")
                for p in [*probe.added, *probe.modified, *probe.removed]
                if str(p).strip()
            }
        )
        if not paths:
            return []
        # Do not re-mark already queued/processing paths — that would slide the
        # rewrite debounce forever while the file remains dirty on disk.
        snap = self.dirty_ledger.snapshot().get("paths") or {}
        fresh = [
            path
            for path in paths
            if str((snap.get(path) or {}).get("state") or "")
            not in {"queued", "due", "processing", "overlay_ready"}
        ]
        if not fresh:
            self.last_probe = {**probe.to_dict(), "reason": "change_poll"}
            return []
        self.dirty_ledger.mark(fresh, reason="disk_poll", now=current_time)
        self.last_probe = {**probe.to_dict(), "reason": "change_poll"}
        return fresh

    def reconcile(self, reason: str = "manual") -> dict:
        """Probe the repository and enqueue Merkle-discovered dirty paths."""
        try:
            paths = self.poll_repo_changes()
            self._watcher_last_reconcile = time.monotonic()
            self._watcher_last_error = None
            return {
                "reason": reason,
                "dirty_paths": paths,
                "marked": len(paths),
                "sync_status": self.status()["sync_status"],
            }
        except Exception as exc:
            self._watcher_last_error = str(exc)
            raise

    def note_watcher_overflow(self) -> dict:
        """Discard buffered watcher detail and immediately trust Merkle state."""
        self.needs_full = True
        return self.reconcile(reason="watcher_overflow")

    def note_watcher_restart(self, error: str | None = None) -> None:
        self._watcher_restart_count += 1
        self._watcher_last_error = error

    def check_time_gap(self, *, now: float | None = None) -> dict | None:
        """Detect suspend/resume from a monotonic scheduling gap."""
        current_time = time.monotonic() if now is None else now
        previous = self._last_clock_at
        self._last_clock_at = current_time
        if previous is None or current_time < previous:
            return None
        if current_time - previous <= self.wake_gap_ms / 1000:
            return None
        self._watcher_last_wake_reconcile = current_time
        return self.reconcile(reason="sleep_wake")

    def drain_due(self, *, now: float | None = None) -> list[dict]:
        current_time = time.monotonic() if now is None else now
        paths = self.dirty_ledger.due_paths(now=current_time)
        if not paths:
            self.drain_publish(now=current_time)
            return []

        batch = paths[: self.live_max_files]
        deferred = paths[self.live_max_files :]
        if deferred:
            self.catchup_chunked = True
            self.needs_full = True
            self.dirty_ledger.defer(deferred, now=current_time)
        self.dirty_ledger.begin(batch)
        try:
            payload = self._sync_paths(batch, reason="dirty")
        except Exception:
            self.dirty_ledger.mark(batch, reason="retry", now=current_time)
            raise
        self.live_batches += 1
        chunk_count = int(payload.get("chunks_upserted") or 0) + int(payload.get("chunks_removed") or 0)
        if deferred or chunk_count > self.live_max_chunks:
            self.catchup_chunked = True
            self.needs_full = True
            payload["strategy"] = "catchup_chunked"
            payload["needs_full"] = True
            payload["live_limits"] = {
                "max_files": self.live_max_files,
                "max_chunks": self.live_max_chunks,
                "deferred_paths": len(deferred),
                "chunks": chunk_count,
            }
        self.last_result = payload
        if payload.get("refreshed"):
            self._invalidate_session_paths(batch)
            self._publish_or_hold(payload, paths=batch, now=current_time)
        else:
            self.dirty_ledger.complete(batch, published=True)
        self.drain_publish(now=current_time)
        return [payload]

    def drain_publish(self, *, now: float | None = None, force: bool = False) -> bool:
        current_time = time.monotonic() if now is None else now
        if self._pending_publish is None or (
            not force and self._locate_streak_active(now=current_time)
        ):
            return False

        payload = self._pending_publish
        paths = self._pending_paths
        self._pending_publish = None
        self._pending_paths = set()
        if self._notify_refresh(payload):
            self.dirty_ledger.complete(paths, published=True)
            return True
        payload["dense_pending"] = True
        payload["publish_error"] = payload.get("publish_error") or "publish_failed"
        self._pending_publish = payload
        self._pending_paths = set(paths)
        self.dirty_ledger.complete(paths, published=False)
        return False

    def _locate_streak_active(self, *, now: float | None = None) -> bool:
        if self._last_locate_at is None:
            return False
        current_time = time.monotonic() if now is None else now
        return current_time - self._last_locate_at < self.locate_streak_ms / 1000

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        enabled = os.environ.get("CTX_BACKGROUND_SYNC", "0").strip().lower()
        if enabled in {"0", "false", "no", "off"}:
            print("[keeper] background sync disabled (CTX_BACKGROUND_SYNC)", file=sys.stderr)
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ctx-keeper", daemon=True)
        self._thread.start()
        self.running = True
        if self not in _ACTIVE_LOOPS:
            _ACTIVE_LOOPS.append(self)
        _register_atexit()
        self._start_trigger_watcher()
        print(
            f"[keeper] WARNING: root-probe every {self.interval_ms}ms for {self.repo}",
            file=sys.stderr,
            flush=True,
        )

    def stop(self) -> None:
        self._stop.set()
        self.running = False
        if self in _ACTIVE_LOOPS:
            _ACTIVE_LOOPS.remove(self)

    def keeper_tick(self, *, reason: str = "interval") -> dict:
        """Root probe first; incremental sync only when dirty. No embed on clean."""
        from pipeline.root_probe import root_probe

        # Background ticks yield under resource pressure; final/trigger still try.
        if reason == "interval":
            try:
                from pipeline.resources import get_resource_manager

                b = get_resource_manager().budget("sync")
                if not b.allow:
                    print(
                        f"[keeper] skip tick — resources {b.pressure}: {b.reason}",
                        file=sys.stderr,
                        flush=True,
                    )
                    out = {
                        "refreshed": False,
                        "strategy": "deferred",
                        "reason": reason,
                        "resources": b.to_dict(),
                    }
                    self.last_result = out
                    return out
            except Exception as exc:  # noqa: BLE001
                print(f"[keeper] resource check skipped: {exc}", file=sys.stderr, flush=True)

        with self._lock:
            if self._syncing:
                return {"skipped": True, "reason": "already syncing"}
            self._syncing = True
        try:
            probe = root_probe(self.repo)
            self.last_probe = {**probe.to_dict(), "reason": reason}
            if probe.clean:
                print(
                    f"[keeper] root clean ({probe.ms:.0f}ms, checked={probe.files_checked}) [{reason}]",
                    file=sys.stderr,
                    flush=True,
                )
                out = {
                    "refreshed": False,
                    "strategy": "root_clean",
                    "probe": probe.to_dict(),
                    "reason": reason,
                }
                self.last_result = out
                return out

            print(
                f"[keeper] root dirty changed={probe.changed_count} "
                f"(+{len(probe.added)} ~{len(probe.modified)} -{len(probe.removed)}) "
                f"[{reason}] — incremental sync",
                file=sys.stderr,
                flush=True,
            )
            return self._sync_unlocked(probe_meta=probe.to_dict(), reason=reason)
        finally:
            with self._lock:
                self._syncing = False

    def final_check(self, *, reason: str = "shutdown") -> dict:
        """One last cheap probe (+ sync if dirty). Best-effort; once per stop."""
        if getattr(self, "_final_done", False):
            return {"skipped": True, "reason": "final_already_done"}
        self._final_done = True
        try:
            result = self.keeper_tick(reason=reason)
            forced_paths = self.dirty_ledger.force_due()
            if forced_paths:
                self.drain_due()
            result["publish_delivered"] = self.drain_publish(force=True)
            return result
        except Exception as exc:  # noqa: BLE001
            print(f"[keeper] final_check failed: {exc}", file=sys.stderr, flush=True)
            return {"error": str(exc), "reason": reason}

    def sync_once(self) -> dict:
        """Force incremental path (trigger file / manual). Still root-gated via tick."""
        return self.keeper_tick(reason="trigger")

    def _sync_unlocked(self, *, probe_meta: dict | None = None, reason: str = "interval") -> dict:
        from pipeline.incremental import incremental_sync

        result = incremental_sync(self.repo)
        payload = result.to_dict()
        payload["probe"] = probe_meta
        payload["reason"] = reason
        self.last_result = payload
        if result.refreshed:
            print(
                f"[keeper] refreshed {len(result.files)} files in {result.ms:.0f}ms",
                file=sys.stderr,
                flush=True,
            )
            self._publish_or_hold(payload, paths=result.files)
        return payload

    def _sync_paths(self, paths: list[str], *, reason: str) -> dict:
        from pipeline.incremental import incremental_sync

        result = incremental_sync(self.repo, force_files=paths)
        payload = result.to_dict()
        payload["reason"] = reason
        payload["dirty_paths"] = paths
        return payload

    def _invalidate_session_paths(self, paths: list[str]) -> None:
        try:
            from pipeline.session_store import invalidate_paths

            result = invalidate_paths(self.repo, paths)
            self.live_invalidations += int(result.get("removed") or 0)
        except Exception as exc:  # noqa: BLE001
            print(f"[keeper] session invalidation failed: {exc}", file=sys.stderr, flush=True)

    def _publish_or_hold(
        self,
        payload: dict,
        *,
        paths: Iterable[str],
        now: float | None = None,
    ) -> None:
        current_time = time.monotonic() if now is None else now
        if self._locate_streak_active(now=current_time):
            payload["overlay_ready"] = True
            self._pending_publish = payload
            self._pending_paths.update(paths)
            self.dirty_ledger.complete(paths, published=False)
            return
        if self._notify_refresh(payload):
            self.dirty_ledger.complete(paths, published=True)
        else:
            payload["dense_pending"] = True
            payload["publish_error"] = payload.get("publish_error") or "publish_failed"
            self.dirty_ledger.complete(paths, published=False)

    def _notify_refresh(self, payload: dict) -> bool:
        """Deliver a coherent publication. False means prior generation stays live."""
        if not self.on_refresh:
            return True
        try:
            result = self.on_refresh(payload)
        except Exception as exc:  # noqa: BLE001
            print(f"[keeper] on_refresh error: {exc}", file=sys.stderr, flush=True)
            payload["publish_error"] = str(exc)
            return False
        if isinstance(result, dict) and result.get("ok") is False:
            payload["publish_error"] = str(result.get("error") or "publish_failed")
            return False
        return True

    def _run(self) -> None:
        delay = int(os.environ.get("CTX_SYNC_INITIAL_DELAY_MS", str(DEFAULT_INITIAL_DELAY_MS)))
        if self._stop.wait(max(0, delay) / 1000.0):
            return
        next_probe = time.monotonic()
        next_change_poll = time.monotonic()
        while not self._stop.is_set():
            try:
                now = time.monotonic()
                self.check_time_gap(now=now)
                if now >= next_change_poll:
                    self.poll_repo_changes(now=now)
                    next_change_poll = now + self.change_poll_ms / 1000.0
                if now >= next_probe:
                    self.keeper_tick(reason="interval")
                    next_probe = now + self.interval_ms / 1000.0
                self.drain_due(now=now)
                self.drain_publish(now=now)
            except Exception as exc:  # noqa: BLE001
                print(f"[keeper] error: {exc}", file=sys.stderr, flush=True)
            if self._stop.wait(0.25):
                break

    def _start_trigger_watcher(self) -> None:
        if os.environ.get("CTX_TRIGGER_WATCHER", "1").strip().lower() in {"0", "false", "off"}:
            return

        def _watch() -> None:
            home = Path.home() / ".context-engine"
            home.mkdir(parents=True, exist_ok=True)
            trigger = home / TRIGGER_NAME
            last = trigger.stat().st_mtime if trigger.exists() else 0.0
            while not self._stop.is_set():
                try:
                    if trigger.exists():
                        m = trigger.stat().st_mtime
                        if m > last:
                            last = m
                            print(
                                "[keeper] trigger file touched — probe",
                                file=sys.stderr,
                                flush=True,
                            )
                            time.sleep(0.5)
                            self.keeper_tick(reason="trigger")
                except OSError:
                    pass
                if self._stop.wait(1.0):
                    break

        threading.Thread(target=_watch, name="ctx-trigger", daemon=True).start()


# Alias used in docs / status
KeeperLoop = BackgroundSyncLoop


def touch_sync_trigger() -> Path:
    """Hook helper: touch after Write/Edit so MCP catches up (Claude Context)."""
    home = Path.home() / ".context-engine"
    home.mkdir(parents=True, exist_ok=True)
    p = home / TRIGGER_NAME
    p.write_text(str(time.time()), encoding="utf-8")
    return p
