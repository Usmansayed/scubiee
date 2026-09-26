"""Prove FAISS VectorDB stores embeddings, collections, cwd isolation, reload."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from pipeline.vectordb import VectorDatabase, cwd_collection_name


@pytest.fixture
def vdb(tmp_path: Path) -> VectorDatabase:
    return VectorDatabase(root=tmp_path / "vectordb")


def test_create_add_search_persist(vdb: VectorDatabase, tmp_path: Path):
    dim = 32
    col = vdb.create_collection("demo", dim=dim, cwd=tmp_path / "proj", bits=4)
    rng = np.random.default_rng(0)
    vectors = rng.normal(size=(20, dim)).astype(np.float32)
    # make id 0 distinctive
    vectors[0] = 0
    vectors[0, 0] = 1.0
    payloads = [{"file": f"f{i}.py", "chunk_id": i} for i in range(20)]
    n = col.add(vectors, list(range(20)), payloads)
    assert n == 20
    assert col.ntotal == 20
    vdb.save_collection("demo")

    # Files on disk
    cpath = vdb._collection_path("demo")
    assert (cpath / "faiss.index").exists()
    assert (cpath / "turboquant.npz").exists()
    assert (cpath / "ids.npy").exists()
    assert (cpath / "payloads.jsonl").exists()
    assert (cpath / "meta.json").exists()
    assert vdb.catalog_path.exists()

    # Reload fresh DB instance
    vdb2 = VectorDatabase(root=vdb.root)
    col2 = vdb2.get_collection("demo")
    assert col2.ntotal == 20
    stats = col2.stats()
    assert stats["faiss_ntotal"] == 20
    assert stats["compressed_bytes"] > 0
    assert stats["compression_ratio"] >= 4.0

    q = vectors[0].copy()
    hits = col2.search(q, top_k=3)
    assert len(hits) >= 1
    top_id, top_score, payload = hits[0]
    assert top_id == 0
    assert payload.get("file") == "f0.py"
    assert top_score > 0.5


def test_cwd_collection_isolation(vdb: VectorDatabase, tmp_path: Path):
    a = tmp_path / "repoA"
    b = tmp_path / "repoB"
    a.mkdir()
    b.mkdir()
    ca = vdb.get_or_create_for_cwd(a, dim=16, bits=4)
    cb = vdb.get_or_create_for_cwd(b, dim=16, bits=4)
    assert ca.name != cb.name
    assert ca.name == cwd_collection_name(a)

    rng = np.random.default_rng(1)
    ca.add(rng.normal(size=(5, 16)).astype(np.float32), list(range(5)))
    cb.add(rng.normal(size=(3, 16)).astype(np.float32), list(range(3)))
    vdb.save_collection(ca.name)
    vdb.save_collection(cb.name)

    assert ca.ntotal == 5
    assert cb.ntotal == 3
    names = {c["name"] for c in vdb.list_collections()}
    assert ca.name in names and cb.name in names

    found = vdb.find_by_cwd(a)
    assert found is not None and found.ntotal == 5


def test_delete_and_drop(vdb: VectorDatabase, tmp_path: Path):
    col = vdb.create_collection("tmp", dim=8, cwd=tmp_path, bits=4)
    rng = np.random.default_rng(2)
    col.add(rng.normal(size=(10, 8)).astype(np.float32), list(range(10)))
    removed = col.delete([1, 2, 3])
    assert removed == 3
    assert col.ntotal == 7
    vdb.save_collection("tmp")
    vdb.drop_collection("tmp")
    assert not vdb.has_collection("tmp")
    assert vdb.list_collections() == [] or all(
        c["name"] != "tmp" for c in vdb.list_collections()
    )


def test_mmap_reload_can_add_a_vector(vdb: VectorDatabase, tmp_path: Path):
    """IFC mmap indexes abort on add. Reload must copy into owned RAM first."""
    dim = 8
    col = vdb.create_collection("mmap", dim=dim, cwd=tmp_path, bits=4)
    rng = np.random.default_rng(4)
    col.add(rng.normal(size=(6, dim)).astype(np.float32), list(range(6)))
    vdb.save_collection("mmap")

    loaded = VectorDatabase(root=vdb.root).get_collection("mmap")
    assert loaded._index_viewed is True
    extra = np.zeros((1, dim), dtype=np.float32)
    extra[0, 0] = 1.0
    loaded.add(extra, [99], [{"file": "new.py"}])
    assert loaded._index_viewed is False
    assert loaded.ntotal == 7
    hits = loaded.search(extra, top_k=1)
    assert hits and hits[0][0] == 99


def test_upsert_same_ids(vdb: VectorDatabase, tmp_path: Path):
    col = vdb.create_collection("up", dim=8, cwd=tmp_path, bits=4)
    rng = np.random.default_rng(3)
    v1 = rng.normal(size=(2, 8)).astype(np.float32)
    col.add(v1, [0, 1], [{"v": 1}, {"v": 1}])
    v2 = rng.normal(size=(2, 8)).astype(np.float32)
    col.add(v2, [0, 1], [{"v": 2}, {"v": 2}])
    assert col.ntotal == 2
    assert col.payloads[0]["v"] == 2


def test_concurrent_search_survives_add_delete_compact(vdb: VectorDatabase, tmp_path: Path):
    """Faiss allows concurrent searches only — mutation must exclude readers.

    Reader threads hammering ``search`` while the writer runs
    ``add``/``delete``/``compact`` used to abort the process
    (``MaybeOwnedVector::resize`` / connection reset mid-sync) because those
    mutators did not take the lock ``search`` holds.
    """
    import threading

    dim = 24
    col = vdb.create_collection("race", dim=dim, cwd=tmp_path / "proj", bits=4)
    rng = np.random.default_rng(7)
    base = rng.normal(size=(120, dim)).astype(np.float32)
    col.add(base, list(range(120)), [{"chunk_id": i} for i in range(120)])

    stop = threading.Event()
    errors: list[BaseException] = []
    searches = [0]
    search_lock = threading.Lock()

    def reader() -> None:
        q = rng.normal(size=(dim,)).astype(np.float32)
        while not stop.is_set():
            try:
                col.search(q, top_k=5)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
                return
            with search_lock:
                searches[0] += 1

    threads = [threading.Thread(target=reader, daemon=True) for _ in range(4)]
    for t in threads:
        t.start()

    try:
        next_id = 120
        for round_n in range(12):
            extra = rng.normal(size=(4, dim)).astype(np.float32)
            ids = list(range(next_id, next_id + 4))
            col.add(extra, ids, [{"chunk_id": i} for i in ids])
            next_id += 4
            col.delete([round_n * 3])
            if round_n % 4 == 3:
                col.compact()
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=10)

    assert not errors, f"concurrent search raised: {errors[:3]}"
    assert searches[0] > 0, "readers never ran — test proves nothing"
    # Post-state coherence: ids unique, tombstones a subset of ids, live count sane.
    assert len(col.ids) == len(set(col.ids))
    assert set(col.meta.dead_ids).issubset(set(col.ids))
    assert col.live_count == len(col.ids) - len(col.meta.dead_ids)
    assert col.live_count > 0
    q = np.zeros(dim, dtype=np.float32)
    q[0] = 1.0
    col.search(q, top_k=5)  # still usable after the storm
