"""Vectors reused across edits must not keep describing old chunk text.

Chunk diffs reuse a vector while the chunk key and the first 512 chars of its
text are unchanged, so an edit further down left the stored vector embedded
from the old text. Payload ``ehash`` names the text a vector came from, and
``reconcile_vector_store`` re-embeds any live chunk whose ``ehash`` drifted.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from pipeline.embedder import text_key, write_cache_snapshot
from pipeline.incremental import incremental_sync, reconcile_vector_store
from pipeline.store import ChunkRecord, PipelineStore, embed_hash, vector_payload
from pipeline.vectordb import CollectionMeta, FaissCollection, VectorDatabase

DIM = 32


def _fake_vec(text: str) -> np.ndarray:
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
    vec = np.random.default_rng(seed).normal(size=DIM).astype(np.float32)
    return vec / np.linalg.norm(vec)


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


class _Emb:
    dim = DIM

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed_many(self, texts, progress=None, *, is_query: bool = False):
        self.calls.append(list(texts))
        if not texts:
            return np.zeros((0, DIM), np.float32)
        return np.stack([_fake_vec(t) for t in texts])

    def embed_one(self, text, *, is_query: bool = False):
        return _fake_vec(text)

    @property
    def embedded(self) -> int:
        return sum(len(c) for c in self.calls)


def _chunk(cid: int, file: str, text: str, symbol: str | None = None) -> ChunkRecord:
    return ChunkRecord(
        id=cid, file=file, start_line=1, end_line=4, symbol=symbol, text=text,
        enriched=f"{file}\n{text}",
    )


def _stored(col: FaissCollection, cid: int) -> np.ndarray:
    row = col.ids.index(cid)
    return col.compressed.take_float32([row])[0]


LONG_HEAD = "    # " + "padding comment that keeps the digest prefix stable " * 12 + "\n"


def _long_fn(tail: str) -> str:
    return f"def long_fn(x):\n{LONG_HEAD}    y = x + 1\n    return {tail}\n"


@pytest.fixture()
def repo_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "long.py").write_text(_long_fn("y * 2"), encoding="utf-8")
    base = tmp_path / "store"
    vdb = VectorDatabase(tmp_path / "vdb")
    store = PipelineStore(repo, base_dir=base, vdb=vdb)
    store.save_meta({"dim": DIM, "bits": 8})
    (base / "graph.json").write_text(
        json.dumps({"nodes": [], "edges": [], "hyperedges": []}), encoding="utf-8"
    )
    emb = _Emb()
    monkeypatch.setattr("pipeline.engine.get_embedder", lambda *_a, **_k: emb)
    monkeypatch.setattr("pipeline.engine.clear_engines", lambda: None)
    first = incremental_sync(repo, base_dir=base, vdb=vdb)
    assert first.error is None, first.error
    return repo, base, vdb, store, emb


def _assert_all_fresh(store: PipelineStore, vdb: VectorDatabase) -> None:
    col = VectorDatabase(vdb.root).get_collection(store.collection_name)
    for c in store.load_chunks():
        assert col.payloads[c.id].get("ehash") == embed_hash(c), c.symbol
        assert _cos(_stored(col, c.id), _fake_vec(c.enriched)) > 0.99, c.symbol


def test_payloads_carry_ehash_after_index(repo_env) -> None:
    _repo, _base, vdb, store, _emb = repo_env
    assert store.load_chunks()
    _assert_all_fresh(store, vdb)


def _edit_tail(repo: Path) -> None:
    # A new function rewrites the file-wide "Functions:" line in every chunk's
    # enriched text while long_fn's own raw text (its digest) is unchanged.
    (repo / "pkg" / "long.py").write_text(
        _long_fn("y * 2") + "\n\nimport json\n\ndef added_helper(v):\n    return json.dumps(v)\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("hot", [False, True])
def test_edit_past_digest_prefix_is_reembedded(repo_env, hot: bool) -> None:
    repo, base, vdb, store, emb = repo_env
    before = {c.symbol: c.enriched for c in store.load_chunks()}
    _edit_tail(repo)
    result = incremental_sync(
        repo, base_dir=base, vdb=vdb, force_files=["pkg/long.py"],
        hot_lane=hot, capacity_wait_s=0.05,
    )
    assert result.error is None, result.error
    if callable(getattr(result, "vector_flush", None)):
        result.vector_flush()
    after = {c.symbol: c.enriched for c in store.load_chunks()}
    assert "added_helper" in after
    assert after["long_fn"] != before["long_fn"], "long_fn's enriched text must have drifted"
    if hot:
        # The hot lane keeps the reused vector for speed; the keeper's non-hot
        # catch-up for the same path makes it exact.
        catchup = incremental_sync(
            repo, base_dir=base, vdb=vdb, force_files=["pkg/long.py"], capacity_wait_s=0.05
        )
        assert catchup.error is None, catchup.error
    _assert_all_fresh(store, vdb)


def test_reconcile_repairs_known_drift_in_place(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    vdb = VectorDatabase(tmp_path / "vdb")
    store = PipelineStore(repo, base_dir=tmp_path / "store", vdb=vdb)
    old = [_chunk(i, f"f{i}.py", f"old text {i}") for i in range(6)]
    new = [_chunk(i, f"f{i}.py", f"new text {i}" if i in (1, 4) else f"old text {i}") for i in range(6)]
    store.save_chunks(new)
    store.save_meta({"dim": DIM, "bits": 8})
    col = vdb.create_collection(store.collection_name, dim=DIM, cwd=repo, bits=8)
    col.add(np.stack([_fake_vec(c.enriched) for c in old]), [c.id for c in old],
            [vector_payload(c) for c in old])
    col.save()
    emb = _Emb()
    monkeypatch.setattr("pipeline.engine.get_embedder", lambda *_a, **_k: emb)

    report = reconcile_vector_store(store)
    assert report["drifted"] == 2 and report["repaired"] == 2
    assert report["embedded"] == 0 and report["dropped"] == 0
    assert emb.calls == [[new[1].enriched, new[4].enriched]]
    _assert_all_fresh(store, vdb)
    assert reconcile_vector_store(store)["drifted"] == 0


def test_legacy_payload_verified_by_cache_without_reembed(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    vdb = VectorDatabase(tmp_path / "vdb")
    store = PipelineStore(repo, base_dir=tmp_path / "store", vdb=vdb)
    chunks = [_chunk(i, f"f{i}.py", f"text {i}") for i in range(5)]
    store.save_chunks(chunks)
    store.save_meta({"dim": DIM, "bits": 8})
    col = vdb.create_collection(store.collection_name, dim=DIM, cwd=repo, bits=8)
    # Chunk 2's vector came from older text; its payload predates ehash.
    vecs = [_fake_vec(c.enriched) for c in chunks]
    vecs[2] = _fake_vec("something older")
    col.add(np.stack(vecs), [c.id for c in chunks], [{"chunk_id": c.id} for c in chunks])
    col.save()
    # The embed cache holds the current text of every chunk.
    write_cache_snapshot(
        store.embed_cache, {text_key("d:" + c.enriched): _fake_vec(c.enriched) for c in chunks}
    )
    emb = _Emb()
    monkeypatch.setattr("pipeline.engine.get_embedder", lambda *_a, **_k: emb)

    report = reconcile_vector_store(store)
    assert report["verified"] == 4
    assert report["drifted"] == 1 and report["repaired"] == 1
    assert emb.calls == [[chunks[2].enriched]]
    _assert_all_fresh(store, vdb)
    again = reconcile_vector_store(store)
    assert again["verified"] == 0 and again["drifted"] == 0


def test_legacy_without_cache_is_reembedded(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    vdb = VectorDatabase(tmp_path / "vdb")
    store = PipelineStore(repo, base_dir=tmp_path / "store", vdb=vdb)
    chunks = [_chunk(i, f"f{i}.py", f"text {i}") for i in range(3)]
    store.save_chunks(chunks)
    store.save_meta({"dim": DIM, "bits": 8})
    col = vdb.create_collection(store.collection_name, dim=DIM, cwd=repo, bits=8)
    col.add(np.stack([_fake_vec(c.enriched) for c in chunks]), [c.id for c in chunks],
            [{"chunk_id": c.id} for c in chunks])
    col.save()
    emb = _Emb()
    monkeypatch.setattr("pipeline.engine.get_embedder", lambda *_a, **_k: emb)
    report = reconcile_vector_store(store)
    assert report["repaired"] == 3
    _assert_all_fresh(store, vdb)


def test_hot_reconcile_skips_legacy_and_cache_maintenance(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    vdb = VectorDatabase(tmp_path / "vdb")
    store = PipelineStore(repo, base_dir=tmp_path / "store", vdb=vdb)
    chunks = [_chunk(i, f"f{i}.py", f"text {i}") for i in range(3)]
    store.save_chunks(chunks)
    store.save_meta({"dim": DIM, "bits": 8})
    col = vdb.create_collection(store.collection_name, dim=DIM, cwd=repo, bits=8)
    col.add(np.stack([_fake_vec("stale") for _ in chunks]), [c.id for c in chunks],
            [{"chunk_id": c.id} for c in chunks])
    col.save()
    emb = _Emb()
    monkeypatch.setattr("pipeline.engine.get_embedder", lambda *_a, **_k: emb)
    called: list[int] = []
    monkeypatch.setattr("pipeline.incremental._maintain_embed_cache", lambda *_a: called.append(1))
    report = reconcile_vector_store(store, hot=True)
    assert report["drifted"] == 0 and emb.calls == [] and called == []


def test_drift_cap_bounds_one_pass(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    vdb = VectorDatabase(tmp_path / "vdb")
    store = PipelineStore(repo, base_dir=tmp_path / "store", vdb=vdb)
    chunks = [_chunk(i, f"f{i}.py", f"text {i}") for i in range(10)]
    store.save_chunks(chunks)
    store.save_meta({"dim": DIM, "bits": 8})
    col = vdb.create_collection(store.collection_name, dim=DIM, cwd=repo, bits=8)
    stale = [_chunk(c.id, c.file, "old " + c.text) for c in chunks]
    col.add(np.stack([_fake_vec(c.enriched) for c in stale]), [c.id for c in stale],
            [vector_payload(c) for c in stale])
    col.save()
    emb = _Emb()
    monkeypatch.setattr("pipeline.engine.get_embedder", lambda *_a, **_k: emb)
    assert reconcile_vector_store(store, drift_cap=4)["repaired"] == 4
    assert reconcile_vector_store(store, drift_cap=4)["repaired"] == 4
    assert reconcile_vector_store(store, drift_cap=4)["repaired"] == 2
    assert reconcile_vector_store(store, drift_cap=4)["drifted"] == 0
    _assert_all_fresh(store, vdb)


def test_reconcile_compacts_a_bloated_embed_cache(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    vdb = VectorDatabase(tmp_path / "vdb")
    store = PipelineStore(repo, base_dir=tmp_path / "store", vdb=vdb)
    chunks = [_chunk(i, f"f{i}.py", f"text {i}") for i in range(3)]
    store.save_chunks(chunks)
    store.save_meta({"dim": DIM, "bits": 8})
    col = vdb.create_collection(store.collection_name, dim=DIM, cwd=repo, bits=8)
    col.add(np.stack([_fake_vec(c.enriched) for c in chunks]), [c.id for c in chunks],
            [vector_payload(c) for c in chunks])
    col.save()
    live = {text_key("d:" + c.enriched): _fake_vec(c.enriched) for c in chunks}
    dead = {f"dead{i}": _fake_vec(f"dead{i}") for i in range(3000)}
    write_cache_snapshot(store.embed_cache, {**dead, **live})
    monkeypatch.setattr("pipeline.engine.get_embedder", lambda *_a, **_k: _Emb())
    monkeypatch.setattr("pipeline.engine._EMBEDDERS", {})

    reconcile_vector_store(store)
    with np.load(store.embed_cache.with_suffix(".npz"), allow_pickle=True) as data:
        keys = {str(k) for k in data["keys"].tolist()}
    assert set(live) <= keys
    assert len(keys) <= len(live) + 1024


# ---- FaissCollection.update_vectors ---------------------------------------


def _col(tmp_path: Path, n: int = 10) -> FaissCollection:
    col = FaissCollection(tmp_path / "c", CollectionMeta(name="t", cwd="", dim=DIM, bits=8))
    col.add(np.stack([_fake_vec(f"v{i}") for i in range(n)]), list(range(n)),
            [{"chunk_id": i} for i in range(n)])
    return col


def test_update_vectors_overwrites_rows_and_search(tmp_path: Path) -> None:
    col = _col(tmp_path)
    col.save()
    loaded = FaissCollection.load(tmp_path / "c")
    assert loaded._index_viewed in (True, False)
    target = _fake_vec("replacement")
    assert loaded.update_vectors(target.reshape(1, -1), [3], [{"chunk_id": 3, "ehash": "x"}]) == 1
    assert loaded.index.ntotal == 10
    assert loaded.search(target, top_k=1)[0][0] == 3
    assert loaded.payloads[3]["ehash"] == "x"
    assert _cos(_stored(loaded, 3), target) > 0.99
    assert _cos(_stored(loaded, 4), _fake_vec("v4")) > 0.99
    loaded.save()
    again = FaissCollection.load(tmp_path / "c")
    assert again.index.ntotal == 10
    assert again.search(target, top_k=1)[0][0] == 3


def test_update_vectors_skips_unknown_and_dead(tmp_path: Path) -> None:
    col = _col(tmp_path)
    col.delete([5])
    n = col.update_vectors(np.stack([_fake_vec("a"), _fake_vec("b"), _fake_vec("c")]), [5, 99, 2])
    assert n == 1
    assert col.index.ntotal == 9
    assert col.search(_fake_vec("c"), top_k=1)[0][0] == 2


def test_update_vectors_falls_back_to_rebuild(tmp_path: Path, monkeypatch) -> None:
    col = _col(tmp_path)

    class _Broken:
        def __init__(self, inner):
            self._inner = inner

        def remove_ids(self, _ids):
            raise RecursionError("broken wheel")

        def __getattr__(self, name):
            return getattr(self._inner, name)

    col.index = _Broken(col.index)
    target = _fake_vec("z")
    assert col.update_vectors(target.reshape(1, -1), [7]) == 1
    assert col.index.ntotal == 10
    assert col.search(target, top_k=1)[0][0] == 7


def test_update_vectors_validates(tmp_path: Path) -> None:
    col = _col(tmp_path)
    with pytest.raises(ValueError):
        col.update_vectors(np.zeros((2, DIM), np.float32), [1])
    with pytest.raises(ValueError):
        col.update_vectors(np.zeros((1, DIM + 1), np.float32), [1])
    assert col.update_vectors(np.zeros((0, DIM), np.float32), []) == 0


def test_vector_payload_ehash_semantics() -> None:
    c = _chunk(1, "a.py", "body")
    assert vector_payload(c)["ehash"] == embed_hash(c) == text_key("d:" + c.enriched)
    assert vector_payload(c, ehash="old")["ehash"] == "old"
    assert "ehash" not in vector_payload(c, ehash=None)
