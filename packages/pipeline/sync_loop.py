"""Keeper sync loop — Cursor/Claude Context session lifecycle.

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

from pipeline.dirty_ledger import DirtyLedger

DEFAULT_INTERVAL_MS = int(os.environ.get("CTX_SYNC_INTERVAL_MS", str(5 * 60 * 1000)))
DEFAULT_INITIAL_DELAY_MS = int(os.environ.get("CTX_SYNC_INITIAL_DELAY_MS", "5000"))
DEFAULT_DEBOUNCE_MS = int(os.environ.get("CTX_DEBOUNCE_MS", "1500"))
DEFAULT_REWRITE_DEBOUNCE_MS = int(os.environ.get("CTX_REWRITE_DEBOUNCE_MS", "2500"))
DEFAULT_LOCATE_STREAK_MS = int(os.environ.get("CTX_LOCATE_STREAK_MS", "8000"))
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
    ):
        self.repo = repo.resolve()
        self.interval_ms = max(1000, interval_ms)
        self.on_refresh = on_refresh
        self.locate_streak_ms = max(0, locate_streak_ms)
        self.dirty_ledger = DirtyLedger(
            debounce_ms=debounce_ms,
            rewrite_debounce_ms=rewrite_debounce_ms,
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
        self.running = False

    def status(self) -> dict:
        dirty = self.dirty_ledger.snapshot()
        states = [entry["state"] for entry in dirty["paths"].values()]
        return {
            "running": bool(self.running and self._thread and self._thread.is_alive()),
            "repo": str(self.repo),
            "interval_ms": self.interval_ms,
            "last_probe": self.last_probe,
            "last_sync": self.last_result,
            "dirty": dirty,
            "overlay_ready": "overlay_ready" in states,
            "publish_pending": self._pending_publish is not None,
            "locate_streak_active": self._locate_streak_active(),
        }

    def mark_dirty(self, paths: Iterable[str], *, reason: str = "write") -> None:
        self.dirty_ledger.mark(paths, reason=reason)

    def note_locate(self, *, now: float | None = None) -> None:
        self._last_locate_at = time.monotonic() if now is None else now

    def drain_due(self, *, now: float | None = None) -> list[dict]:
        current_time = time.monotonic() if now is None else now
        paths = self.dirty_ledger.due_paths(now=current_time)
        if not paths:
            self.drain_publish(now=current_time)
            return []

        self.dirty_ledger.begin(paths)
        try:
            payload = self._sync_paths(paths, reason="dirty")
        except Exception:
            self.dirty_ledger.mark(paths, reason="retry", now=current_time)
            raise
        self.last_result = payload
        if payload.get("refreshed"):
            self._publish_or_hold(payload, paths=paths, now=current_time)
        else:
            self.dirty_ledger.complete(paths, published=True)
        self.drain_publish(now=current_time)
        return [payload]

    def drain_publish(self, *, now: float | None = None) -> bool:
        current_time = time.monotonic() if now is None else now
        if self._pending_publish is None or self._locate_streak_active(now=current_time):
            return False

        payload = self._pending_publish
        paths = self._pending_paths
        self._pending_publish = None
        self._pending_paths = set()
        self._notify_refresh(payload)
        self.dirty_ledger.complete(paths, published=True)
        return True

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
            return self.keeper_tick(reason=reason)
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
        self._notify_refresh(payload)
        self.dirty_ledger.complete(paths, published=True)

    def _notify_refresh(self, payload: dict) -> None:
        if not self.on_refresh:
            return
        try:
            self.on_refresh(payload)
        except Exception as exc:  # noqa: BLE001
            print(f"[keeper] on_refresh error: {exc}", file=sys.stderr, flush=True)

    def _run(self) -> None:
        delay = int(os.environ.get("CTX_SYNC_INITIAL_DELAY_MS", str(DEFAULT_INITIAL_DELAY_MS)))
        if self._stop.wait(max(0, delay) / 1000.0):
            return
        next_probe = time.monotonic()
        while not self._stop.is_set():
            try:
                now = time.monotonic()
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
