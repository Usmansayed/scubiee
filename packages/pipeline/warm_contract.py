"""Attach-warm → steady locate contract.

Product SLA:
- From MCP bridge attach, reach ``warm_ready`` within ``CTX_WARM_DEADLINE_MS`` (30s).
- After ready, map/pack stay hot while any client (incl. bridge) is registered.
- Unload only after last client leave + disconnect debounce.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_WARM_DEADLINE_MS = 30_000

_LOCK = threading.Lock()
_STARTED_AT: float | None = None
_READY_AT: float | None = None
_AST_HYDRATED = False
_AST_SOURCE: str | None = None
_PHASE = "idle"
_LAST_ERROR: str | None = None


@dataclass(frozen=True)
class WarmSnapshot:
    engine_healthy: bool
    embedder_loaded: bool
    ast_hydrated: bool
    started_at: float | None = None
    elapsed_ms: float | None = None
    soft_search_ready: bool = False


def warm_deadline_ms() -> int:
    raw = (os.environ.get("CTX_WARM_DEADLINE_MS") or str(DEFAULT_WARM_DEADLINE_MS)).strip()
    try:
        return max(1000, int(float(raw)))
    except ValueError:
        return DEFAULT_WARM_DEADLINE_MS


def attach_warm_enabled() -> bool:
    """Delegate to RuntimeController (single knob)."""
    from pipeline.runtime_controller import attach_warm_enabled as _enabled

    return _enabled()


def compute_warm_ready(snap: WarmSnapshot, *, need_ast: bool = False) -> bool:
    """Soft binder ready is enough for map; dense embed may still be loading."""
    if not snap.engine_healthy:
        return False
    if not (snap.soft_search_ready or snap.embedder_loaded):
        return False
    if need_ast and not snap.ast_hydrated:
        return False
    return True


def _stamp_path() -> Path:
    home = (os.environ.get("CTX_HOME") or "").strip()
    base = Path(home) if home else (Path.home() / ".scubiee")
    return base / "warm_attach.json"


def mark_warm_start(repo: Path | str | None = None, *, now: float | None = None) -> float:
    """Record attach-warm start (process + shared stamp for bridge/locate)."""
    global _STARTED_AT, _READY_AT, _PHASE, _LAST_ERROR
    started = float(time.time() if now is None else now)
    with _LOCK:
        if _STARTED_AT is None or started < _STARTED_AT:
            _STARTED_AT = started
            _READY_AT = None
        _PHASE = "starting"
        _LAST_ERROR = None
        local_started = _STARTED_AT
    payload = {
        "started_at": local_started,
        "deadline_ms": warm_deadline_ms(),
        "repo": str(Path(repo).resolve()) if repo else None,
        "pid": os.getpid(),
    }
    try:
        path = _stamp_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(path)
    except Exception:  # noqa: BLE001
        pass
    return local_started


def mark_warm_ready(*, now: float | None = None) -> float | None:
    """Freeze attach→ready duration once (do not keep growing warm_elapsed_ms)."""
    global _READY_AT
    current = float(time.time() if now is None else now)
    with _LOCK:
        if _READY_AT is None:
            _READY_AT = current
        return _READY_AT


def warm_started_at() -> float | None:
    global _STARTED_AT
    with _LOCK:
        if _STARTED_AT is not None:
            started = _STARTED_AT
        else:
            started = None
    if started is None:
        try:
            raw = json.loads(_stamp_path().read_text(encoding="utf-8"))
            started = float(raw.get("started_at"))
        except Exception:  # noqa: BLE001
            return None
        with _LOCK:
            if _STARTED_AT is None:
                _STARTED_AT = started
    # Ignore stale attach stamps (previous Cursor session).
    age = time.time() - float(started)
    if age < 0 or age > max(120.0, warm_deadline_ms() / 1000.0 * 6.0):
        return None
    return float(started)


def warm_elapsed_ms(*, now: float | None = None) -> float | None:
    """Ms since attach start.

    Once warm becomes ready, freeze at attach→ready so status does not look like
    a 100s warm-up while the clock keeps ticking.
    """
    started = warm_started_at()
    if started is None:
        return None
    current = time.time() if now is None else now
    with _LOCK:
        ready_at = _READY_AT
    end = float(ready_at) if ready_at is not None else float(current)
    return round(max(0.0, (end - started) * 1000.0), 1)


def warm_remaining_s(*, now: float | None = None) -> float | None:
    started = warm_started_at()
    if started is None:
        return None
    current = time.time() if now is None else now
    return max(0.0, (warm_deadline_ms() / 1000.0) - (current - started))


def set_ast_hydrated(ok: bool, *, source: str | None = None) -> None:
    global _AST_HYDRATED, _AST_SOURCE
    with _LOCK:
        _AST_HYDRATED = bool(ok)
        if source:
            _AST_SOURCE = source


def ast_hydrated() -> bool:
    with _LOCK:
        return bool(_AST_HYDRATED)


def set_warm_phase(phase: str, *, error: str | None = None) -> None:
    global _PHASE, _LAST_ERROR
    with _LOCK:
        _PHASE = str(phase or "idle")
        if error is not None:
            _LAST_ERROR = str(error)


def warm_status_fields(
    *,
    engine_healthy: bool,
    embedder_loaded: bool | None,
    need_ast: bool = False,
    soft_search_ready: bool | None = None,
) -> dict[str, Any]:
    """Fields to merge into status/gate payloads."""
    emb = bool(embedder_loaded) if embedder_loaded is not None else False
    soft = bool(soft_search_ready) if soft_search_ready is not None else False
    snap = WarmSnapshot(
        engine_healthy=bool(engine_healthy),
        embedder_loaded=emb,
        soft_search_ready=soft,
        ast_hydrated=ast_hydrated(),
        started_at=warm_started_at(),
        elapsed_ms=warm_elapsed_ms(),
    )
    ready = compute_warm_ready(snap, need_ast=need_ast)
    map_ready = compute_warm_ready(snap, need_ast=False)
    if ready or map_ready:
        mark_warm_ready()
        # Refresh elapsed after freeze.
        snap = WarmSnapshot(
            engine_healthy=bool(engine_healthy),
            embedder_loaded=emb,
            soft_search_ready=soft,
            ast_hydrated=ast_hydrated(),
            started_at=warm_started_at(),
            elapsed_ms=warm_elapsed_ms(),
        )
    with _LOCK:
        phase = _PHASE
        err = _LAST_ERROR
        src = _AST_SOURCE
    if ready:
        phase = "ready"
    elif snap.started_at is not None and not ready:
        if phase in {"idle", "starting"} and (emb or soft):
            phase = "hydrating" if need_ast and not snap.ast_hydrated else "embedding"
    return {
        "warm_ready": ready,
        "warm_ready_map": map_ready,
        "warm_phase": phase,
        "warm_elapsed_ms": snap.elapsed_ms,
        "warm_deadline_ms": warm_deadline_ms(),
        "warm_remaining_s": warm_remaining_s(),
        "ast_hydrated": snap.ast_hydrated,
        "ast_hydrate_source": src,
        "warm_error": err,
        "attach_warm": attach_warm_enabled(),
    }
