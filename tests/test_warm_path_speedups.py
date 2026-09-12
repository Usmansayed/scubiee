"""Warm-path speedups: FAISS mmap, BM25 cache, TurboQuant matrix hydrate."""

from __future__ import annotations

from pathlib import Path

import faiss
import numpy as np


def test_turboquant_load_keeps_ntotal_and_shape(tmp_path: Path) -> None:
    from pipeline.turbo_quant import CompressedEmbeddingStore

    rng = np.random.default_rng(2)
    x = rng.normal(size=(64, 48)).astype(np.float32)
    store = CompressedEmbeddingStore(dim=48, bits=4)
    store.add(x)
    path = tmp_path / "tq.npz"
    store.save(path)
    loaded = CompressedEmbeddingStore.load(path)
    assert loaded.ntotal == 64
    assert loaded.to_float32().shape == (64, 48)
    assert isinstance(loaded._codes, np.ndarray)
    assert loaded._codes.shape == (64, 48)


def test_bm25_cache_roundtrip(tmp_path: Path) -> None:
    from pipeline.bm25_cache import (
        chunks_fingerprint,
        invalidate_bm25_cache,
        load_or_build_bm25,
    )

    store = tmp_path / "store"
    store.mkdir()
    chunks = store / "chunks.jsonl"
    chunks.write_text('{"id":0}\n{"id":1}\n', encoding="utf-8")
    (store / "meta.json").write_text('{"chunks":2}\n', encoding="utf-8")
    texts = ["def alpha():\n    return 1", "def beta():\n    return 2"]

    bm25_a, meta_a = load_or_build_bm25(store, texts)
    assert meta_a["source"] == "build"
    assert bm25_a.N == 2
    assert (store / "bm25_cache.pkl").is_file()

    bm25_b, meta_b = load_or_build_bm25(store, texts)
    assert meta_b["source"] == "cache"
    assert bm25_b.search("alpha", top_k=1)[0][0] == bm25_a.search("alpha", top_k=1)[0][0]

    chunks.write_text('{"id":0}\n{"id":1}\n{"id":2}\n', encoding="utf-8")
    (store / "meta.json").write_text('{"chunks":3}\n', encoding="utf-8")
    texts3 = texts + ["def gamma():\n    pass"]
    bm25_c, meta_c = load_or_build_bm25(store, texts3)
    assert meta_c["source"] == "build"
    assert bm25_c.N == 3

    fp = chunks_fingerprint(store)
    invalidate_bm25_cache(store)
    assert not (store / "bm25_cache.pkl").is_file()
    assert fp.startswith("v1:")


def test_read_faiss_index_mmap_or_ram(tmp_path: Path) -> None:
    from pipeline.vectordb import _read_faiss_index

    dim = 16
    index = faiss.IndexIDMap2(faiss.IndexFlatIP(dim))
    mat = np.random.default_rng(0).normal(size=(20, dim)).astype(np.float32)
    faiss.normalize_L2(mat)
    ids = np.arange(20, dtype=np.int64)
    index.add_with_ids(mat, ids)
    path = tmp_path / "faiss.index"
    faiss.write_index(index, str(path))

    loaded = _read_faiss_index(path)
    assert int(loaded.ntotal) == 20
    D, I = loaded.search(mat[:1], 3)
    assert I.shape == (1, 3)
    assert int(I[0, 0]) == 0
