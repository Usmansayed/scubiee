"""replace_all/compact after an mmap load must not re-append the old faiss.index."""

from __future__ import annotations

from pathlib import Path

import faiss
import numpy as np

from pipeline.vectordb import CollectionMeta, FaissCollection

DIM = 16


def _vecs(n: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).normal(size=(n, DIM)).astype(np.float32)


def _fresh(path: Path, n: int = 20) -> FaissCollection:
    col = FaissCollection(path, CollectionMeta(name="t", cwd="", dim=DIM, bits=8))
    col.add(_vecs(n, 0), list(range(n)))
    col.save()
    return col


def _disk_ntotal(path: Path) -> int:
    return int(faiss.read_index(str(path / "faiss.index")).ntotal)


def _disk_ids(path: Path) -> list[int]:
    idx = faiss.read_index(str(path / "faiss.index"))
    return sorted(faiss.vector_to_array(idx.id_map).tolist())


def test_replace_all_after_load_does_not_double(tmp_path: Path) -> None:
    p = tmp_path / "c"
    _fresh(p)
    col = FaissCollection.load(p)
    col.replace_all(_vecs(20, 1), list(range(20)))
    assert col.index.ntotal == 20
    col.save()
    assert _disk_ntotal(p) == 20
    assert _disk_ids(p) == list(range(20))


def test_replace_all_with_fewer_ids_after_load(tmp_path: Path) -> None:
    p = tmp_path / "c"
    _fresh(p)
    col = FaissCollection.load(p)
    col.replace_all(_vecs(5, 2), [100, 101, 102, 103, 104])
    col.save()
    assert _disk_ids(p) == [100, 101, 102, 103, 104]


def test_compact_with_persisted_tombstones_after_load(tmp_path: Path) -> None:
    p = tmp_path / "c"
    col = _fresh(p)
    col.delete([3, 4])
    col.save()
    loaded = FaissCollection.load(p)
    assert loaded.dead_count == 2
    loaded.compact()
    assert loaded.index.ntotal == 18
    loaded.save()
    assert _disk_ntotal(p) == 18
    assert _disk_ids(p) == [i for i in range(20) if i not in (3, 4)]


def test_upsert_after_load_keeps_one_copy(tmp_path: Path) -> None:
    p = tmp_path / "c"
    _fresh(p)
    col = FaissCollection.load(p)
    new = _vecs(1, 3)
    col.add(new, [7])
    col.save()
    assert _disk_ids(p) == list(range(20))
    hits = FaissCollection.load(p).search(new[0], top_k=1)
    assert hits[0][0] == 7


def test_repeated_cycles_stay_flat(tmp_path: Path) -> None:
    p = tmp_path / "c"
    _fresh(p)
    for cycle in range(4):
        col = FaissCollection.load(p)
        col.replace_all(_vecs(20, 10 + cycle), list(range(20)))
        col.save()
        col = FaissCollection.load(p)
        col.delete([cycle])
        col.compact()
        col.save()
        col = FaissCollection.load(p)
        col.add(_vecs(1, 50 + cycle), [cycle])
        col.save()
    assert _disk_ntotal(p) == 20
    assert _disk_ids(p) == list(range(20))
    assert (p / "faiss.index").stat().st_size < 20 * DIM * 4 * 2 + 4096


def test_load_rebuilds_index_with_duplicate_ids(tmp_path: Path) -> None:
    """A doubled faiss.index from older builds is detected and rebuilt on load."""
    p = tmp_path / "c"
    col = _fresh(p, n=10)
    doubled = faiss.IndexIDMap2(faiss.IndexFlatIP(DIM))
    mat = col.compressed.to_float32().copy()
    faiss.normalize_L2(mat)
    doubled.add_with_ids(mat, np.arange(10, dtype=np.int64))
    doubled.add_with_ids(mat, np.arange(10, dtype=np.int64))
    faiss.write_index(doubled, str(p / "faiss.index"))

    loaded = FaissCollection.load(p)
    assert loaded.index.ntotal == 10
    assert loaded._index_viewed is False
    loaded.save()
    assert _disk_ids(p) == list(range(10))


def test_load_rebuilds_index_with_same_count_wrong_ids(tmp_path: Path) -> None:
    p = tmp_path / "c"
    col = _fresh(p, n=10)
    bad = faiss.IndexIDMap2(faiss.IndexFlatIP(DIM))
    mat = col.compressed.to_float32().copy()
    faiss.normalize_L2(mat)
    bad.add_with_ids(mat[:5], np.arange(5, dtype=np.int64))
    bad.add_with_ids(mat[:5], np.arange(5, dtype=np.int64))
    faiss.write_index(bad, str(p / "faiss.index"))

    loaded = FaissCollection.load(p)
    assert sorted(faiss.vector_to_array(loaded.index.id_map).tolist()) == list(range(10))


def test_clean_load_keeps_mmap_view(tmp_path: Path) -> None:
    p = tmp_path / "c"
    _fresh(p)
    loaded = FaissCollection.load(p)
    assert loaded.index.ntotal == 20
    hits = loaded.search(_vecs(20, 0)[4], top_k=1)
    assert hits[0][0] == 4
