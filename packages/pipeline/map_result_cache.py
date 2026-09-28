"""Proximity map result cache — true few-ms repeats while clients stay connected.

Entries are keyed on the engine's index token (``pipeline.index_generation``:
runtime epoch + publish generation). Every publish changes the token, so a
remap after an edit misses and re-queries instead of replaying pre-edit cards.
No token (engine not loaded / stamp unreadable) means no caching at all.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path
from typing import Any


_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, str, dict[str, Any]]] = {}
# Last successful map payload per repo|query, with the token it was built on.
_LAST: dict[str, tuple[float, str, dict[str, Any]]] = {}


def map_result_cache_enabled() -> bool:
    raw = (os.environ.get("CTX_MAP_RESULT_CACHE") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _ttl_s() -> float:
    # Default 300s — idle hold (120s) must not expire cache before post_idle map.
    # Freshness comes from the token; the TTL only bounds memory.
    raw = (os.environ.get("CTX_MAP_RESULT_CACHE_TTL_S") or "300").strip()
    try:
        return max(5.0, float(raw))
    except ValueError:
        return 120.0


def current_index_token(repo: str | Path) -> str | None:
    """Token of the index the engine is serving for ``repo`` (None = unknown)."""
    try:
        from pipeline.index_generation import read_token

        return read_token(repo)
    except Exception:  # noqa: BLE001
        return None


def _norm_query(query: str) -> str:
    return " ".join((query or "").lower().split())


def _norm_repo(repo: str) -> str:
    try:
        return str(Path(repo).resolve()).replace("\\", "/").lower()
    except Exception:  # noqa: BLE001
        return str(repo or "").replace("\\", "/").lower()


def _key(repo: str, query: str, fingerprint: str) -> str:
    blob = f"{_norm_repo(repo)}|{fingerprint}|{_norm_query(query)}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:40]


def _last_key(repo: str, query: str) -> str:
    return f"{_norm_repo(repo)}|{_norm_query(query)}"


def _cached_map_is_dense(payload: dict[str, Any]) -> bool:
    if payload.get("dense") is True:
        return "pseudo" not in str(payload.get("retrieve_mode") or "")
    timings = payload.get("timings") if isinstance(payload.get("timings"), dict) else {}
    return timings.get("dense") is True and "pseudo" not in str(timings.get("retrieve_mode") or "")


def get_map_cached(
    *,
    repo: str,
    query: str,
    fingerprint: str | None,
) -> dict[str, Any] | None:
    """Cached map payload built on index token ``fingerprint``, else None."""
    if not map_result_cache_enabled() or not fingerprint:
        return None
    now = time.time()
    lk = _last_key(repo, query)
    with _LOCK:
        last = _LAST.get(lk)
        if last and (now - last[0]) <= _ttl_s():
            if last[1] != fingerprint:
                # Built on an older publish: never serve it again.
                _LAST.pop(lk, None)
            else:
                out = dict(last[2])
                if not _cached_map_is_dense(out):
                    _LAST.pop(lk, None)
                else:
                    timing = dict(out.get("timing") or {})
                    timing["cache"] = "last"
                    out["timing"] = timing
                    out["cache"] = "last"
                    return out
    key = _key(repo, query, fingerprint)
    with _LOCK:
        row = _CACHE.get(key)
        if not row:
            return None
        ts, fp, payload = row
        if fp != fingerprint or (now - ts) > _ttl_s():
            _CACHE.pop(key, None)
            return None
        out = dict(payload)
    if not _cached_map_is_dense(out):
        _CACHE.pop(key, None)
        return None
    timing = dict(out.get("timing") or {})
    timing["cache"] = "hit"
    out["timing"] = timing
    out["cache"] = "hit"
    return out


def put_map_cached(
    *,
    repo: str,
    query: str,
    fingerprint: str | None,
    payload: dict[str, Any],
) -> None:
    """Store a map payload built on index token ``fingerprint`` (read *before* the search)."""
    if not map_result_cache_enabled() or not fingerprint:
        return
    if not isinstance(payload, dict) or not payload.get("ok", True):
        return
    if payload.get("warming") or payload.get("error") in {
        "engine_warming",
        "dense_embed_loading",
        "dense_embed_required",
    }:
        return
    timings = payload.get("timings") if isinstance(payload.get("timings"), dict) else {}
    if payload.get("dense") is not True and timings.get("dense") is not True:
        return
    key = _key(repo, query, fingerprint)
    stored = dict(payload)
    timing = dict(stored.get("timing") or {})
    timing["cache"] = "miss"
    stored["timing"] = timing
    now = time.time()
    with _LOCK:
        _CACHE[key] = (now, fingerprint, stored)
        _LAST[_last_key(repo, query)] = (now, fingerprint, stored)
        if len(_CACHE) > 64:
            oldest = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[: len(_CACHE) - 64]
            for k, _ in oldest:
                _CACHE.pop(k, None)
        if len(_LAST) > 64:
            oldest_l = sorted(_LAST.items(), key=lambda kv: kv[1][0])[: len(_LAST) - 64]
            for k, _ in oldest_l:
                _LAST.pop(k, None)


def clear_map_cache() -> None:
    with _LOCK:
        _CACHE.clear()
        _LAST.clear()


def get_recent_map_cards(*, repo: str, limit: int = 16) -> list[dict[str, Any]]:
    """Most recent map cards for repo (process-local) — lean pack reuse without disk.

    Only cards built on the index the engine serves now: after a publish they
    may point at lines that moved or code that is gone.
    """
    if not map_result_cache_enabled():
        return []
    token = current_index_token(repo)
    if not token:
        return []
    root = _norm_repo(repo)
    now = time.time()
    best: tuple[float, list[dict[str, Any]]] | None = None
    with _LOCK:
        for key, (ts, fp, payload) in _LAST.items():
            if not key.startswith(root + "|"):
                continue
            if fp != token or (now - ts) > _ttl_s():
                continue
            cards = list((payload or {}).get("cards") or [])
            if cards and (best is None or ts > best[0]):
                best = (ts, cards)
    if best is None:
        return []
    return best[1][: max(1, int(limit))]
