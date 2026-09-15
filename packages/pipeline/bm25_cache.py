"""Persisted BM25 index — skip rebuild on warm load when chunks fingerprint matches."""

from __future__ import annotations

import pickle
import time
from pathlib import Path
from typing import Any

from conductor.bm25_index import BM25Index

BM25_CACHE_NAME = "bm25_cache.pkl"
BM25_CACHE_VERSION = 1


def bm25_cache_path(store_dir: Path) -> Path:
    return Path(store_dir).resolve() / BM25_CACHE_NAME


def chunks_fingerprint(store_dir: Path) -> str:
    """Cheap invalidation key: size + mtime of published chunks (+ meta chunks count)."""
    store_dir = Path(store_dir).resolve()
    chunks = store_dir / "chunks.jsonl"
    if not chunks.is_file():
        return "missing"
    st = chunks.stat()
    meta_n = ""
    meta = store_dir / "meta.json"
    if meta.is_file():
        try:
            import json

            meta_n = str(json.loads(meta.read_text(encoding="utf-8")).get("chunks", ""))
        except Exception:  # noqa: BLE001
            meta_n = ""
    return f"v{BM25_CACHE_VERSION}:{st.st_size}:{getattr(st, 'st_mtime_ns', int(st.st_mtime * 1e9))}:{meta_n}"


def invalidate_bm25_cache(store_dir: Path) -> None:
    path = bm25_cache_path(store_dir)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def save_bm25_cache(store_dir: Path, bm25: BM25Index, *, fingerprint: str | None = None) -> Path:
    store_dir = Path(store_dir).resolve()
    fp = fingerprint or chunks_fingerprint(store_dir)
    payload: dict[str, Any] = {
        "version": BM25_CACHE_VERSION,
        "fingerprint": fp,
        "saved_at": time.time(),
        "k1": bm25.k1,
        "b": bm25.b,
        "N": bm25.N,
        "docs": bm25.docs,
        "doc_len": bm25.doc_len,
        "avgdl": bm25.avgdl,
        "idf": bm25.idf,
        "_tf": bm25._tf,
    }
    path = bm25_cache_path(store_dir)
    tmp = path.with_suffix(".pkl.tmp")
    tmp.write_bytes(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))
    tmp.replace(path)
    return path


def load_bm25_cache(store_dir: Path, *, fingerprint: str | None = None) -> BM25Index | None:
    path = bm25_cache_path(store_dir)
    if not path.is_file():
        return None
    want = fingerprint or chunks_fingerprint(store_dir)
    try:
        raw = pickle.loads(path.read_bytes())
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(raw, dict):
        return None
    if int(raw.get("version") or 0) != BM25_CACHE_VERSION:
        return None
    if str(raw.get("fingerprint") or "") != want:
        return None
    try:
        bm25 = BM25Index.__new__(BM25Index)
        bm25.k1 = float(raw["k1"])
        bm25.b = float(raw["b"])
        bm25.docs = list(raw["docs"])
        bm25.N = int(raw["N"])
        bm25.doc_len = list(raw["doc_len"])
        bm25.avgdl = float(raw["avgdl"])
        bm25.idf = dict(raw["idf"])
        bm25._tf = list(raw["_tf"])
        if bm25.N != len(bm25.docs) or bm25.N != len(bm25._tf):
            return None
        bm25._rebuild_accel()
        return bm25
    except Exception:  # noqa: BLE001
        return None


def load_or_build_bm25(store_dir: Path, texts: list[str]) -> tuple[BM25Index, dict[str, Any]]:
    """Return BM25 + meta ``{source: cache|build, ms: float}``."""
    t0 = time.perf_counter()
    fp = chunks_fingerprint(store_dir)
    cached = load_bm25_cache(store_dir, fingerprint=fp)
    if cached is not None and cached.N == len(texts):
        return cached, {"source": "cache", "ms": (time.perf_counter() - t0) * 1000, "fingerprint": fp}
    bm25 = BM25Index(texts)
    try:
        save_bm25_cache(store_dir, bm25, fingerprint=fp)
    except Exception:  # noqa: BLE001
        pass
    return bm25, {"source": "build", "ms": (time.perf_counter() - t0) * 1000, "fingerprint": fp}
