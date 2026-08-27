"""Keeper sync loop — Cursor/Claude Context session lifecycle.

CE_LIVE_PROBE_20260818_mcp_verify

While MCP / ``scubiee serve`` is open: periodic root-hash probe → incremental sync
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
from pipeline.project_id import resolve_project, context_engine_home
from pipeline.sync_status import derive_sync_status

DEFAULT_INTERVAL_MS = int(os.environ.get("CTX_SYNC_INTERVAL_MS", str(5 * 60 * 1000)))
DEFAULT_INITIAL_DELAY_MS = int(os.environ.get("CTX_SYNC_INITIAL_DELAY_MS", "5000"))
DEFAULT_DEBOUNCE_MS = int(os.environ.get("CTX_DEBOUNCE_MS", "1500"))
DEFAULT_REWRITE_DEBOUNCE_MS = int(os.environ.get("CTX_REWRITE_DEBOUNCE_MS", "2500"))
DEFAULT_LOCATE_STREAK_MS = int(os.environ.get("CTX_LOCATE_STREAK_MS", "8000"))
DEFAULT_LIVE_MAX_FILES = int(os.environ.get("CTX_LIVE_MAX_FILES", "200"))
DEFAULT_LIVE_MAX_CHUNKS = int(os.environ.get("CTX_LIVE_MAX_CHUNKS", "300"))
DEFAULT_AUTO_FULL_INDEX_CHUNKS = int(os.environ.get("CTX_AUTO_FULL_INDEX_CHUNKS", "10000"))
DEFAULT_BULK_REINDEX_THRESHOLD = int(os.environ.get("CTX_BULK_REINDEX_THRESHOLD", "300"))
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
        self.auto_full_index_chunks = max(1, DEFAULT_AUTO_FULL_INDEX_CHUNKS)
        self.bulk_reindex_threshold = max(1, DEFAULT_BULK_REINDEX_THRESHOLD)
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
        # Adaptive change-poll backoff: track probe durations to detect slow I/O
        # (antivirus interference, network drives, etc.) and reduce poll frequency.
        self._probe_durations: list[float] = []  # last N probe durations in seconds
        self._original_change_poll_ms = self.change_poll_ms
        self._backoff_active = False

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
            "auto_full_index_chunks": self.auto_full_index_chunks,
            "bulk_reindex_threshold": self.bulk_reindex_threshold,
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

    def _estimate_dirty_chunks(self, paths: list[str]) -> tuple[int, dict[str, int]]:
        """Estimate changed chunks without parsing or mutating the index.

        Existing files use their indexed chunk count. New files use a conservative
        line-based estimate because their chunk count does not exist yet. The
        estimate is only a gate for the 10000-chunk safety limit; incremental_sync
        applies the exact post-parse limit before writing graph/vector artifacts.
        """
        counts: dict[str, int] = {}
        try:
            from pipeline.store import PipelineStore

            ref = resolve_project(self.repo)
            store = PipelineStore(
                self.repo,
                base_dir=ref.store_dir,
                project_id=ref.project_id,
            )
            for chunk in store.load_chunks():
                rel = chunk.file.replace("\\", "/")
                counts[rel] = counts.get(rel, 0) + 1
        except Exception:
            counts = {}

        estimates: dict[str, int] = {}
        for raw_path in paths:
            path = str(raw_path).replace("\\", "/")
            estimate = counts.get(path, 0)
            if estimate <= 0:
                candidate = self.repo / path
                if candidate.is_file():
                    try:
                        lines = sum(1 for _ in candidate.open("r", encoding="utf-8", errors="ignore"))
                    except OSError:
                        lines = 0
                    estimate = max(1, min(2000, (lines + 24) // 25))
                else:
                    estimate = 1
            estimates[path] = estimate
        return sum(estimates.values()), estimates

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

        Includes adaptive backoff: if root_probe consistently takes > 2s
        (3 consecutive probes), doubles change_poll_ms up to 10s max.
        Restores original interval when probes drop back under 500ms.
        """
        from pipeline.root_probe import root_probe

        current_time = time.monotonic() if now is None else now
        t_probe_start = time.perf_counter()
        try:
            probe = root_probe(self.repo)
        except Exception as exc:  # noqa: BLE001
            print(f"[keeper] change poll failed: {exc}", file=sys.stderr, flush=True)
            return []
        probe_duration = time.perf_counter() - t_probe_start

        # --- Adaptive backoff: track probe durations for slow I/O detection ---
        self._probe_durations.append(probe_duration)
        # Keep only the last 5 durations for averaging
        if len(self._probe_durations) > 5:
            self._probe_durations = self._probe_durations[-5:]
        self._adapt_poll_interval()

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

    def _adapt_poll_interval(self) -> None:
        """Adaptive backoff: slow I/O → increase poll interval; fast I/O → restore.

        If the last 3 probes all took > 2s, double the poll interval (up to 10s).
        If the last 3 probes all took < 500ms, restore to the original interval.
        This handles antivirus interference and slow network drives gracefully.
        """
        MAX_POLL_MS = 10_000
        SLOW_THRESHOLD_S = 2.0
        FAST_THRESHOLD_S = 0.5
        MIN_SAMPLES = 3

        if len(self._probe_durations) < MIN_SAMPLES:
            return

        recent = self._probe_durations[-MIN_SAMPLES:]
        avg_ms = sum(recent) * 1000 / len(recent)

        if all(d > SLOW_THRESHOLD_S for d in recent):
            # All recent probes are slow — back off
            if not self._backoff_active or self.change_poll_ms < MAX_POLL_MS:
                new_poll = min(self.change_poll_ms * 2, MAX_POLL_MS)
                if new_poll != self.change_poll_ms:
                    print(
                        f"[keeper] slow I/O detected ({avg_ms:.0f}ms avg), "
                        f"backing off to {new_poll}ms poll interval",
                        file=sys.stderr,
                        flush=True,
                    )
                    self.change_poll_ms = new_poll
                    self._backoff_active = True
        elif all(d < FAST_THRESHOLD_S for d in recent) and self._backoff_active:
            # I/O recovered — restore original interval
            if self.change_poll_ms != self._original_change_poll_ms:
                print(
                    f"[keeper] I/O recovered ({avg_ms:.0f}ms avg), "
                    f"restoring {self._original_change_poll_ms}ms poll interval",
                    file=sys.stderr,
                    flush=True,
                )
                self.change_poll_ms = self._original_change_poll_ms
                self._backoff_active = False

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

        estimated_total, estimates = self._estimate_dirty_chunks(paths)

        deferred = self._defer_for_active_session(
            paths, now=current_time, estimated_total=estimated_total
        )
        if deferred is not None:
            return [deferred]

        # --- Tier 3: >10000 chunks — refuse, require explicit full index ---
        if estimated_total > self.auto_full_index_chunks:
            self.needs_full = True
            payload = {
                "refreshed": False,
                "files": paths[:50],
                "chunks_upserted": 0,
                "chunks_removed": 0,
                "strategy": "explicit_full_index_required",
                "needs_full": True,
                "estimated_chunks": estimated_total,
                "auto_full_index_chunks": self.auto_full_index_chunks,
                "error": (
                    f"approximately {estimated_total} chunks changed, exceeding the "
                    f"automatic limit of {self.auto_full_index_chunks}; run "
                    f"`scubiee index {self.repo} --force` explicitly"
                ),
                "warnings": [
                    "Automatic sync paused before graph/vector mutation; explicit full indexing is required."
                ],
            }
            self.last_result = payload
            self.dirty_ledger.defer(paths, now=current_time + 60.0)
            return [payload]

        # --- Tier 2: 301–10000 chunks — bulk reindex (800 MB, sub-batched with checkpoints) ---
        if estimated_total > self.bulk_reindex_threshold:
            self.catchup_chunked = True
            try:
                payload = self._bulk_sync_paths(paths, reason="bulk_reindex")
            except Exception:
                # Only re-mark paths that are NOT already published by
                # completed sub-batches — avoid overriding durable progress.
                snap = self.dirty_ledger.snapshot().get("paths", {})
                unpublished = [
                    p for p in paths
                    if (snap.get(p) or {}).get("state") != "published"
                ]
                if unpublished:
                    self.dirty_ledger.mark(unpublished, reason="retry", now=current_time)
                self.catchup_chunked = False
                raise
            self.live_batches += 1
            self.last_result = payload
            if payload.get("strategy") == "explicit_full_index_required":
                self.needs_full = True
                payload["needs_full"] = True
            elif payload.get("refreshed"):
                # _bulk_sync_paths already committed sub-batches to journal;
                # just notify the publication layer for generation advance.
                self._notify_refresh(payload)
            self.catchup_chunked = False
            self.drain_publish(now=current_time)
            return [payload]

        # --- Tier 1: ≤300 chunks — fast live batch ---
        batch: list[str] = []
        estimated_batch = 0
        for path in paths:
            if len(batch) >= self.live_max_files:
                break
            estimate = estimates.get(path, 1)
            if batch and estimated_batch + estimate > self.live_max_chunks:
                break
            batch.append(path)
            estimated_batch += estimate
            if estimated_batch >= self.live_max_chunks:
                break
        if not batch:
            batch = [paths[0]]
        batch_set = set(batch)
        deferred = [path for path in paths if path not in batch_set]
        if deferred:
            self.catchup_chunked = True
            self.dirty_ledger.defer(deferred, now=current_time)
        self.dirty_ledger.begin(batch)
        try:
            payload = self._sync_paths(batch, reason="dirty")
        except Exception:
            self.dirty_ledger.mark(batch, reason="retry", now=current_time)
            raise
        self.live_batches += 1
        chunk_count = int(payload.get("chunks_upserted") or 0) + int(payload.get("chunks_removed") or 0)
        if deferred:
            self.catchup_chunked = True
            payload["strategy"] = "catchup_chunked"
            payload["catchup_chunked"] = True
            payload["live_limits"] = {
                "max_files": self.live_max_files,
                "max_chunks": self.live_max_chunks,
                "deferred_paths": len(deferred),
                "chunks": chunk_count,
            }
        elif chunk_count > self.live_max_chunks:
            payload["live_limits"] = {
                "max_files": self.live_max_files,
                "max_chunks": self.live_max_chunks,
                "deferred_paths": 0,
                "chunks": chunk_count,
            }
        self.last_result = payload
        if payload.get("strategy") == "explicit_full_index_required":
            self.needs_full = True
            payload["needs_full"] = True
            self.dirty_ledger.defer(batch, now=current_time + 60.0)
        elif payload.get("refreshed"):
            self._invalidate_session_paths(batch)
            self._publish_or_hold(payload, paths=batch, now=current_time)
        else:
            self.dirty_ledger.complete(batch, published=False)
            if isinstance(payload, dict):
                warns = payload.setdefault("warnings", [])
                if isinstance(warns, list):
                    warns.append(
                        "sync did not refresh the index; search may be stale until retry"
                    )
        self.drain_publish(now=current_time)
        if not any(
            entry.get("state") in {"queued", "due", "processing"}
            for entry in self.dirty_ledger.snapshot().get("paths", {}).values()
        ):
            self.catchup_chunked = False
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

    def _clients_active(self) -> bool:
        """True when an MCP/IDE/experiment client is registered against the engine."""
        try:
            from pipeline.lifecycle_runtime import active_client_count

            return active_client_count() > 0
        except Exception:  # noqa: BLE001
            return False

    def _defer_for_active_session(
        self, paths: list[str], *, now: float, estimated_total: int
    ) -> dict | None:
        """Hold bulk/heavy sync while agents are locating or MCP clients are attached.

        Tier-1 live batches (≤ bulk threshold) always proceed after debounce so
        edits show up in the vector DB within seconds. Bulk reindex replaces the
        live vector set — defer that mid-session and re-check shortly.
        """
        clients = self._clients_active()
        locate = self._locate_streak_active(now=now)
        bulk = estimated_total > self.bulk_reindex_threshold
        # Live path: never defer. Bulk path: defer if clients or locate-streak.
        if not bulk or not (clients or locate):
            return None
        # Re-queue soon; do not drop dirty state.
        self.dirty_ledger.defer(paths, now=now + 15.0)
        reason = "clients_active" if clients else "locate_streak_bulk"
        print(
            f"[keeper] defer sync ({reason}): {len(paths)} paths "
            f"~{estimated_total} chunks",
            file=sys.stderr,
            flush=True,
        )
        payload = {
            "refreshed": False,
            "files": paths[:50],
            "chunks_upserted": 0,
            "chunks_removed": 0,
            "strategy": "deferred_active_session",
            "reason": reason,
            "estimated_chunks": estimated_total,
            "clients_active": clients,
            "locate_streak_active": locate,
        }
        self.last_result = payload
        return payload

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
            # Safe point: collect garbage after sync completes. GC is disabled
            # globally in the daemon to prevent SIGSEGV during native extension
            # work (tokenizers/MLX/numpy). We collect manually here when no
            # embedding is in progress.
            import gc

            gc.collect()

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

    def _bulk_sync_paths(self, paths: list[str], *, reason: str) -> dict:
        """Process dirty paths in committed sub-batches with bootstrap memory budget.

        Used for 301–10000 chunk changes (like a GitHub pull) that should
        complete in minutes. Processes files in sub-batches of ~50, committing
        each to disk atomically. If the process is interrupted (power loss,
        crash), only the in-flight sub-batch is lost — completed sub-batches
        are durable, and the dirty journal re-queues unfinished paths on restart.

        Uses 800 MB RSS cap and batch 48 — same as initial full index.
        """
        from pipeline.incremental import incremental_sync

        BULK_SUB_BATCH = max(1, int(os.environ.get("CTX_BULK_SUB_BATCH", "50") or "50"))
        total_files = len(paths)
        total_upserted = 0
        total_removed = 0
        batches_done = 0
        t0 = time.monotonic()
        last_error: str | None = None
        last_strategy = "bulk_reindex"

        print(
            f"[keeper] bulk sync starting: {total_files} files in ~"
            f"{(total_files + BULK_SUB_BATCH - 1) // BULK_SUB_BATCH} sub-batches [{reason}]",
            file=sys.stderr,
            flush=True,
        )

        for i in range(0, total_files, BULK_SUB_BATCH):
            sub_batch = paths[i : i + BULK_SUB_BATCH]
            # Mark this sub-batch as processing in the journal so a crash
            # leaves them in a retriable state (not marked published).
            self.dirty_ledger.begin(sub_batch)
            try:
                result = incremental_sync(self.repo, force_files=sub_batch, bulk=True)
            except Exception as exc:
                # Return this sub-batch and all remaining to queue for retry.
                self.dirty_ledger.mark(sub_batch, reason="bulk_retry", now=time.monotonic())
                remaining = paths[i + BULK_SUB_BATCH:]
                if remaining:
                    self.dirty_ledger.mark(remaining, reason="bulk_retry", now=time.monotonic())
                last_error = str(exc)
                print(
                    f"[keeper] bulk sub-batch {batches_done + 1} failed: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                break

            if result.refreshed:
                self._invalidate_session_paths(sub_batch)
                self.dirty_ledger.complete(sub_batch, published=True)
                total_upserted += result.chunks_upserted
                total_removed += result.chunks_removed
            elif result.strategy == "explicit_full_index_required":
                # Exact post-parse guard fired — stop bulk and escalate.
                # Re-queue this sub-batch and all remaining un-attempted paths.
                self.dirty_ledger.mark(sub_batch, reason="bulk_oversized", now=time.monotonic())
                remaining = paths[i + BULK_SUB_BATCH:]
                if remaining:
                    self.dirty_ledger.mark(remaining, reason="bulk_oversized", now=time.monotonic())
                last_error = result.error
                last_strategy = "explicit_full_index_required"
                break
            else:
                # Deferred (resource pressure) or other non-refresh — re-queue
                # for retry rather than marking published (files weren't indexed).
                self.dirty_ledger.mark(sub_batch, reason="bulk_deferred", now=time.monotonic())
                remaining = paths[i + BULK_SUB_BATCH:]
                if remaining:
                    self.dirty_ledger.mark(remaining, reason="bulk_deferred", now=time.monotonic())
                if result.error:
                    last_error = result.error
                if result.strategy == "deferred":
                    last_error = last_error or "resource pressure — bulk deferred"
                break

            batches_done += 1
            elapsed = time.monotonic() - t0
            print(
                f"[keeper] bulk sub-batch {batches_done} done: "
                f"{len(sub_batch)} files, {result.chunks_upserted} upserted "
                f"({elapsed:.1f}s elapsed, {total_files - i - len(sub_batch)} files remaining)",
                file=sys.stderr,
                flush=True,
            )

        elapsed_ms = (time.monotonic() - t0) * 1000
        refreshed = total_upserted > 0 or total_removed > 0
        payload = {
            "refreshed": refreshed,
            "files": paths,
            "chunks_upserted": total_upserted,
            "chunks_removed": total_removed,
            "ms": round(elapsed_ms, 1),
            "strategy": last_strategy,
            "reason": reason,
            "bulk": True,
            "dirty_paths": paths,
            "bulk_progress": {
                "sub_batches_done": batches_done,
                "sub_batch_size": BULK_SUB_BATCH,
                "total_files": total_files,
                "files_completed": min(batches_done * BULK_SUB_BATCH, total_files),
            },
            # Only surface error to status if nothing succeeded; otherwise
            # a partial failure would permanently show "error" even though
            # most chunks were indexed. Partial errors go into warnings.
            "error": last_error if not refreshed else None,
            "warnings": [last_error] if (last_error and refreshed) else [],
        }
        print(
            f"[keeper] bulk sync done: {total_upserted} upserted, "
            f"{total_removed} removed in {elapsed_ms:.0f}ms "
            f"({batches_done} sub-batches)",
            file=sys.stderr,
            flush=True,
        )

        # Restore conservative background budget so the daemon doesn't keep
        # After bulk work, restore the conservative background budget so the daemon
        # doesn't keep running at elevated resources for subsequent small live edits.
        try:
            from pipeline.memory_budget import background_budget, force_apply_memory_budget

            force_apply_memory_budget(background_budget())
            print(
                "[keeper] budget restored to background (500MB + 15% CPU)",
                file=sys.stderr,
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[keeper] budget restore failed: {exc}", file=sys.stderr, flush=True)

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
            home = context_engine_home()
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
    home = context_engine_home()
    home.mkdir(parents=True, exist_ok=True)
    p = home / TRIGGER_NAME
    p.write_text(str(time.time()), encoding="utf-8")
    return p
