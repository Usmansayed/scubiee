"""Unified warm / auto-load phase machine (side-channel, not /health).

ORT session init holds the Python GIL (microsoft/onnxruntime#27063), so
ThreadingHTTPServer ``/health`` *will* time out during dense prewarm even when
the engine PID is healthy. Callers must use this module instead of treating
health timeouts as ``engine dead`` while ``phase == prewarm``.

See ``docs/architecture/warm-autoload.md``.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

PHASE_DOWN = "down"
PHASE_SOFT = "soft"
PHASE_PREWARM = "prewarm"
PHASE_DENSE = "dense"
PHASE_ERROR = "error"

_LOCK = threading.RLock()
_PHASE = PHASE_DOWN
_UPDATED_AT = 0.0
_ERROR: str | None = None

# How long prewarm may hold the GIL before we treat the stamp as stuck.
# 45s: DML init is usually 10–35s; 180s left hung ORT protected forever.
DEFAULT_PREWARM_MAX_AGE_S = 45.0


def _home() -> Path:
    from pipeline.project_id import context_engine_home

    return context_engine_home()


def phase_path() -> Path:
    return _home() / "warm_phase.json"


def busy_stamp_path() -> Path:
    try:
        from pipeline.engine import _prewarm_busy_path

        return _prewarm_busy_path()
    except Exception:  # noqa: BLE001
        return _home() / "embed_prewarm.busy"


def read_phase(*, max_age_s: float | None = None) -> dict[str, Any]:
    """Read phase from memory (same process) or disk (MCP/watchdog)."""
    with _LOCK:
        mem = {
            "phase": _PHASE,
            "updated_at": _UPDATED_AT,
            "error": _ERROR,
            "source": "memory",
        }
    path = phase_path()
    disk: dict[str, Any] | None = None
    try:
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                disk = {
                    "phase": str(raw.get("phase") or PHASE_DOWN),
                    "updated_at": float(raw.get("updated_at") or 0.0),
                    "error": raw.get("error"),
                    "source": "disk",
                }
    except Exception:  # noqa: BLE001
        disk = None

    # Prefer fresher of memory vs disk (watchdog is another process → disk wins).
    chosen = mem
    if disk is not None:
        if float(disk.get("updated_at") or 0) >= float(mem.get("updated_at") or 0):
            chosen = disk
        elif os.getpid() and mem.get("updated_at"):
            # Same engine process: memory is authoritative when newer.
            chosen = mem if float(mem.get("updated_at") or 0) > 0 else disk

    age = None
    try:
        ts = float(chosen.get("updated_at") or 0)
        if ts > 0:
            age = time.time() - ts
    except (TypeError, ValueError):
        age = None
    chosen["age_s"] = age
    if max_age_s is not None and age is not None and age > float(max_age_s):
        if chosen.get("phase") == PHASE_PREWARM:
            chosen = {
                **chosen,
                "phase": PHASE_ERROR,
                "error": chosen.get("error") or "prewarm_stale",
                "stale": True,
            }
    return chosen


def _write_phase_file(path: Path, body: str) -> bool:
    """Atomic replace, retried; plain overwrite as the last resort.

    The watchdog and MCP bridges read this file from other processes. On
    Windows ``os.replace`` onto a file another process has open fails with
    WinError 5/32; that error used to be swallowed, so disk kept saying
    "prewarm" after the embedder loaded and the watchdog restarted a healthy
    engine as hung (issue 2). Readers open with share-write, so an in-place
    overwrite still lands when the rename cannot.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(body, encoding="utf-8")
    except OSError:
        return False
    for attempt in range(5):
        try:
            tmp.replace(path)
            return True
        except OSError:
            time.sleep(0.02 * (attempt + 1))
    try:
        path.write_text(body, encoding="utf-8")
        return True
    except OSError:
        return False
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def set_phase(phase: str, *, error: str | None = None) -> dict[str, Any]:
    """Publish phase to memory + disk (best-effort)."""
    global _PHASE, _UPDATED_AT, _ERROR
    phase_s = str(phase or PHASE_DOWN).strip().lower() or PHASE_DOWN
    now = time.time()
    with _LOCK:
        _PHASE = phase_s
        _UPDATED_AT = now
        _ERROR = str(error) if error else None
        snap = {
            "phase": _PHASE,
            "updated_at": _UPDATED_AT,
            "error": _ERROR,
            "pid": os.getpid(),
        }
    _write_phase_file(phase_path(), json.dumps(snap) + "\n")
    # Keep legacy busy stamp in sync for older watchdog paths.
    try:
        from pipeline.engine import _mark_prewarm_busy

        _mark_prewarm_busy(phase_s == PHASE_PREWARM)
    except Exception:  # noqa: BLE001
        pass
    return snap


def begin_prewarm() -> dict[str, Any]:
    """Mark ORT load in-flight. Do not refresh the stamp if already prewarming.

    Duplicate kicks used to reset ``updated_at`` and stretch the 45s abort
    window forever (hung DML stayed ``should_ignore_health_fail``).
    """
    cur = read_phase()
    if cur.get("phase") == PHASE_PREWARM and not cur.get("stale"):
        return cur
    if cur.get("stale") or str(cur.get("error") or "") == "prewarm_stale":
        return cur
    return set_phase(PHASE_PREWARM)


def end_prewarm(*, ok: bool, error: str | None = None) -> dict[str, Any]:
    if ok:
        return set_phase(PHASE_DENSE, error=None)
    return set_phase(PHASE_ERROR, error=error or "prewarm_failed")


def mark_soft() -> dict[str, Any]:
    cur = read_phase()
    if cur.get("phase") in {PHASE_PREWARM, PHASE_DENSE}:
        return cur
    return set_phase(PHASE_SOFT)


def mark_down() -> dict[str, Any]:
    return set_phase(PHASE_DOWN)


def in_prewarm(*, max_age_s: float = DEFAULT_PREWARM_MAX_AGE_S) -> bool:
    snap = read_phase(max_age_s=max_age_s)
    if snap.get("phase") == PHASE_PREWARM and not snap.get("stale"):
        return True
    # Legacy stamp fallback
    try:
        from pipeline.engine import prewarm_busy_stamp_active

        return bool(prewarm_busy_stamp_active(max_age_s=max_age_s))
    except Exception:  # noqa: BLE001
        return False


def hung_prewarm_should_abort(*, max_age_s: float = DEFAULT_PREWARM_MAX_AGE_S) -> bool:
    """True when ORT prewarm has been in-flight longer than the abort window.

    Independent of /health — DML init can answer health for a while, then wedge,
    or wedge without ever flipping phase=dense.
    """
    snap = read_phase(max_age_s=max_age_s)
    # A stale file whose phase is not prewarm is a leftover from a dead
    # process, not an in-flight embedder. Killing the live PID for that
    # restarts the open forever.
    phase = str(snap.get("phase") or "")
    if str(snap.get("error") or "") == "prewarm_stale" or (
        phase == PHASE_PREWARM and snap.get("stale")
    ):
        return True
    if snap.get("phase") == PHASE_PREWARM:
        age = snap.get("age_s")
        try:
            if age is not None and float(age) > float(max_age_s):
                return True
        except (TypeError, ValueError):
            pass
    try:
        from pipeline.engine import _prewarm_busy_path

        path = _prewarm_busy_path()
        if path.is_file():
            parts = (path.read_text(encoding="utf-8") or "0").split()
            age = time.time() - float(parts[0] or 0)
            if len(parts) > 1:
                from pipeline.daemon import _pid_alive

                writer = int(float(parts[1] or 0))
                # pid 0 = stamp neutralised by _mark_prewarm_busy(False).
                if writer <= 0 or not _pid_alive(writer):
                    return False
            elif age > float(max_age_s):
                # Old stamp with no pid. It outlived the process that wrote it.
                return False
            return age > float(max_age_s)
    except Exception:  # noqa: BLE001
        return False
    return False


def should_ignore_health_fail(*, max_age_s: float = DEFAULT_PREWARM_MAX_AGE_S) -> bool:
    """True when /health timeout is expected (ORT GIL during prewarm)."""
    return in_prewarm(max_age_s=max_age_s)


def idle_busy_reason() -> str | None:
    """Non-None ⇒ disconnect idle sweeper must not stop the engine."""
    # max_age_s must be passed so a wedged prewarm (init thread died/hung
    # without ever calling end_prewarm) actually expires here. Without it,
    # read_phase() never sets `stale`, so this stayed "busy:prewarm" forever
    # on every idle-sweep tick regardless of how old the snapshot was.
    snap = read_phase(max_age_s=DEFAULT_PREWARM_MAX_AGE_S)
    if snap.get("phase") == PHASE_PREWARM and not snap.get("stale"):
        return "warm_phase:prewarm"
    try:
        from pipeline.engine import prewarm_busy_stamp_active

        if prewarm_busy_stamp_active(max_age_s=DEFAULT_PREWARM_MAX_AGE_S):
            return "embed_prewarm"
    except Exception:  # noqa: BLE001
        pass
    if snap.get("phase") == PHASE_ERROR and snap.get("error") == "prewarm_stale":
        return None
    return None


def mcp_frontend_present() -> bool:
    try:
        from pipeline.process_control import (
            _is_mcp_bridge_process,
            enumerate_scubiee_processes,
        )

        # exclude_self=False: the per-candidate process-tree walk is the slow
        # part (~1s/tick on Windows), and a bridge that is our own ancestor
        # (engine spawned under a bridge) is still real demand.
        me = os.getpid()
        for proc in enumerate_scubiee_processes(exclude_self=False):
            if int(proc.get("pid") or 0) == me:
                continue
            if _is_mcp_bridge_process(proc):
                return True
    except Exception:  # noqa: BLE001
        return False
    return False


def mcp_or_client_demand() -> tuple[int, bool]:
    try:
        from pipeline.lifecycle_runtime import active_client_count

        clients = int(active_client_count())
    except Exception:  # noqa: BLE001
        clients = 0
    return clients, bool(clients > 0 or mcp_frontend_present())
