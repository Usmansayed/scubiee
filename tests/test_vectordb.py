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


def test_upsert_same_ids(vdb: VectorDatabase, tmp_path: Path):
    col = vdb.create_collection("up", dim=8, cwd=tmp_path, bits=4)
    rng = np.random.default_rng(3)
    v1 = rng.normal(size=(2, 8)).astype(np.float32)
    col.add(v1, [0, 1], [{"v": 1}, {"v": 1}])
    v2 = rng.normal(size=(2, 8)).astype(np.float32)
    col.add(v2, [0, 1], [{"v": 2}, {"v": 2}])
    assert col.ntotal == 2
    assert col.payloads[0]["v"] == 2
