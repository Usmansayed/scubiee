"""The chunk corpus and the vector store must address the same things.

These are the three ways a newly synced file used to stay invisible to search:

1. The dense channel was indexed by vector-store row while every other channel
   was indexed by chunk position, so a hit landed on the wrong chunk and tail
   chunks raised ``IndexError``.
2. A chunk could exist with no vector, and dense is the only channel that can
   admit a file into the result pool.
3. A no-delta batch never recorded the hashes it had just verified, so the same
   paths were re-reported and re-synced forever.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from conductor.architectures import _fit_channel
from pipeline.incremental import incremental_sync, reconcile_vector_store
from pipeline.merkle import canonical_relpath
from pipeline.searcher import FaissDenseAdapter
from pipeline.store import ChunkRecord, PipelineStore
from pipeline.vectordb import VectorDatabase

DIM = 8


def _unit(index: int) -> np.ndarray:
    vec = np.zeros(DIM, dtype=np.float32)
    vec[index % DIM] = 1.0
    return vec


def _chunk(cid: int, file: str, text: str) -> ChunkRecord:
    return ChunkRecord(
        id=cid,
        file=file,
        start_line=1,
        end_line=4,
        symbol=None,
        text=text,
        enriched=f"{file}\n{text}",
    )


def test_dense_adapter_maps_faiss_hits_to_chunk_positions(tmp_path: Path) -> None:
    """A FAISS hit must resolve to the chunk that owns the vector."""
    vdb = VectorDatabase(tmp_path / "vdb")
    col = vdb.create_collection("drift", dim=DIM, cwd=tmp_path, bits=8)

    # Durable ids with gaps, and vector insertion order that does NOT match the
    # chunk file order — exactly what incremental upsert/delete produces.
    col.add(
        np.stack([_unit(3), _unit(1), _unit(5), _unit(7)]),
        [500, 100, 900, 700],
        [{"chunk_id": cid} for cid in (500, 100, 900, 700)],
    )
    # A vector whose chunk is gone (deleted file that was never pruned).
    col.add(_unit(2).reshape(1, -1), [4242], [{"chunk_id": 4242}])

    chunks = [
        _chunk(100, "a.py", "alpha"),
        _chunk(700, "b.py", "bravo"),
        _chunk(500, "c.py", "charlie"),
        _chunk(900, "d.py", "delta"),
        # Chunk with no vector at all, at the tail — where new files land.
        _chunk(1234, "new.py", "november"),
    ]
    files = [c.file for c in chunks]
    chunk_ids = [c.id for c in chunks]

    adapter = FaissDenseAdapter(col, n_chunks=len(chunks), chunk_ids=chunk_ids)

    # One row per chunk, so indexing any chunk position is in range.
    assert adapter.matrix.shape[0] == len(chunks)
    assert adapter.score_all(_unit(1)).shape[0] == len(chunks)
    assert adapter.missing_vectors == 1

    # Each vector must score highest at its own chunk's position.
    for cid, axis in ((500, 3), (100, 1), (900, 5), (700, 7)):
        scores = adapter.score_all(_unit(axis))
        best = int(np.argmax(scores))
        assert chunk_ids[best] == cid, f"vector {cid} scored onto {chunk_ids[best]}"

    # search() returns chunk positions, and the file at that position is the
    # file the vector's own payload claims.
    for cid, axis in ((500, 3), (100, 1), (900, 5), (700, 7)):
        mapped = adapter.search(_unit(axis), top_k=1)
        assert mapped, f"no hit for vector {cid}"
        pos = mapped[0][0]
        assert 0 <= pos < len(files)
        assert chunk_ids[pos] == cid

    # The chunk-less vector must never surface as a chunk position.
    positions = {pos for pos, _ in adapter.search(_unit(2), top_k=5)}
    assert all(0 <= p < len(chunks) for p in positions)


def test_unaligned_adapter_would_index_out_of_bounds(tmp_path: Path) -> None:
    """Without chunk ids the score array is shorter than the corpus."""
    vdb = VectorDatabase(tmp_path / "vdb")
    col = vdb.create_collection("short", dim=DIM, cwd=tmp_path, bits=8)
    col.add(np.stack([_unit(1), _unit(2)]), [10, 20], [{}, {}])

    unaligned = FaissDenseAdapter(col, n_chunks=5)
    scores = unaligned.score_all(_unit(1))
    assert scores.shape[0] == 2
    with pytest.raises(IndexError):
        scores[4]

    # _fit_channel is the backstop: ranking never indexes past the end again.
    assert _fit_channel(scores, 5).shape[0] == 5
    assert _fit_channel(scores, 5)[4] == 0.0
    assert _fit_channel(np.zeros(9), 5).shape[0] == 5


def test_reconcile_embeds_orphan_chunks_and_drops_orphan_vectors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    base = tmp_path / "store"
    vdb = VectorDatabase(tmp_path / "vdb")
    store = PipelineStore(repo, base_dir=base, vdb=vdb)

    chunks = [_chunk(10, "keep.py", "kept"), _chunk(11, "fresh.py", "brand new")]
    store.save_chunks(chunks)
    store.save_meta({"dim": DIM, "bits": 8, "chunks": len(chunks)})

    col = vdb.create_collection(
        store.collection_name, dim=DIM, cwd=repo, bits=8
    )
    # id 10 has a vector; id 11 (the new file) does not; id 99 is a leftover.
    col.add(
        np.stack([_unit(1), _unit(4)]),
        [10, 99],
        [{"chunk_id": 10}, {"chunk_id": 99}],
    )
    col.save()

    class _Emb:
        dim = DIM

        def embed_many(self, texts):
            return np.stack([_unit(6) for _ in texts])

    monkeypatch.setattr("pipeline.engine.get_embedder", lambda *_a, **_k: _Emb())

    report = reconcile_vector_store(store)
    assert report["missing"] == 1
    assert report["embedded"] == 1
    assert report["stale"] == 1
    assert report["dropped"] == 1

    reloaded = VectorDatabase(vdb.root).get_collection(store.collection_name)
    live = {int(v) for v in reloaded.ids} - {int(v) for v in reloaded.meta.dead_ids}
    assert live == {10, 11}, "corpus and vectors must hold exactly the same ids"

    # Idempotent: a second pass has nothing left to do.
    assert reconcile_vector_store(store)["embedded"] == 0


def test_no_delta_batch_records_the_hashes_it_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A batch with nothing to embed must still stop re-reporting its paths."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "keep.py").write_text("def keep():\n    return 1\n", encoding="utf-8")
    base = tmp_path / "store"
    vdb = VectorDatabase(tmp_path / "vdb")
    store = PipelineStore(repo, base_dir=base, vdb=vdb)

    store.save_chunks([_chunk(10, "keep.py", "kept")])
    store.save_meta({"dim": DIM, "bits": 8, "chunks": 1})
    # A nested path that is in the Merkle but not on disk and never had a chunk —
    # the deleted-probe shape that used to loop forever. Nested matters: the
    # snapshot stores canonical keys, which on Windows use "\", so patching with
    # the posix spelling could never delete the entry.
    gone = "pkg/probe/gone.py"
    store.save_merkle({"keep.py": "deadbeef", gone: "cafebabe"})
    assert canonical_relpath(gone) in store.load_merkle()
    (base / "graph.json").write_text(
        json.dumps({"nodes": [], "edges": [], "hyperedges": []}), encoding="utf-8"
    )

    monkeypatch.setattr("pipeline.engine.clear_engines", lambda: None)

    result = incremental_sync(
        repo, base_dir=base, vdb=vdb, force_files=[gone], capacity_wait_s=0.05
    )

    assert result.strategy == "none"
    assert result.chunks_upserted == 0
    after = store.load_merkle()
    assert canonical_relpath(gone) not in after, (
        "a no-delta batch must drop the stale Merkle entry, otherwise the disk "
        "poller re-marks the path on every tick"
    )
    assert gone not in after
    assert canonical_relpath("keep.py") in after, "untouched paths must survive"


def _hot_lane_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A tiny indexed repo plus a fake embedder, ready for a real incremental_sync."""
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "keep.py").write_text("def keep():\n    return 1\n", encoding="utf-8")
    base = tmp_path / "store"
    vdb = VectorDatabase(tmp_path / "vdb")
    store = PipelineStore(repo, base_dir=base, vdb=vdb)

    store.save_chunks([_chunk(10, "pkg/keep.py", "kept")])
    store.save_meta({"dim": DIM, "bits": 8, "chunks": 1})
    col = vdb.create_collection(store.collection_name, dim=DIM, cwd=repo, bits=8)
    col.add(np.stack([_unit(1)]), [10], [{"chunk_id": 10}])
    col.save()
    graph = base / "graph.json"
    graph.write_text(
        json.dumps({"nodes": [], "edges": [], "hyperedges": []}), encoding="utf-8"
    )

    class _Emb:
        dim = DIM

        def embed_many(self, texts):
            return np.stack([_unit(6) for _ in texts]) if texts else np.zeros((0, DIM), np.float32)

        def embed_one(self, text, *, is_query: bool = False):
            return _unit(6)

    monkeypatch.setattr("pipeline.engine.get_embedder", lambda *_a, **_k: _Emb())
    monkeypatch.setattr("pipeline.engine.clear_engines", lambda: None)
    return repo, base, vdb, store, graph


def test_hot_lane_sync_defers_the_graph_and_hands_back_an_append_only_delta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real hot path: no whole-graph merge, and a delta the publisher can append.

    Exercised end to end on purpose — mocking ``incremental_sync`` hid a
    use-before-assignment in this exact branch, which only showed up live as
    ``cannot access local variable 'named_delta'`` and a 2s retry loop.
    """
    repo, base, vdb, store, graph = _hot_lane_repo(tmp_path, monkeypatch)
    graph_before = graph.read_text(encoding="utf-8")

    new_rel = "pkg/probe_hot.py"
    (repo / new_rel).write_text(
        "def probe_hot(payload):\n    return payload\n", encoding="utf-8"
    )

    result = incremental_sync(
        repo,
        base_dir=base,
        vdb=vdb,
        force_files=[new_rel],
        hot_lane=True,
        capacity_wait_s=0.05,
    )

    assert result.error is None, result.error
    assert result.refreshed is True
    assert result.chunks_upserted >= 1
    assert result.chunks_removed == 0

    # Graph work is deferred, not done, and the file is recorded as owed.
    assert graph.read_text(encoding="utf-8") == graph_before, "hot save must not merge the graph"
    assert result.graph_pending == [new_rel]
    assert store.load_meta().get("graph_pending") == [new_rel]

    # Stage timings exist so a missed SLA can name its stage.
    assert result.stages and result.stages["parse_ms"] >= 0.0
    assert "embed_ms" in result.stages and "write_ms" in result.stages

    # The delta is append-only and row-aligned with the appended records.
    delta = result.hot_delta
    assert delta is not None and delta.append_only is True
    assert delta.removed_ids == []
    assert delta.base_chunk_count == 1, "one pre-existing chunk (pkg/keep.py)"
    assert [r.file for r in delta.records] == [new_rel] * len(delta.records)
    assert delta.matrix.shape == (len(delta.records), DIM)

    # Corpus grew by exactly the appended records.
    corpus = store.load_chunks()
    assert len(corpus) == 1 + len(delta.records)
    assert [c.id for c in corpus[1:]] == [r.id for r in delta.records]

    # The collection save is deferred past the publish; the keeper runs this
    # flush right after. Until then disk lags, and after it every chunk has a
    # vector on disk.
    assert callable(result.vector_flush), "hot lane must hand back the deferred save"
    on_disk = VectorDatabase(vdb.root).get_collection(store.collection_name)
    assert {int(v) for v in on_disk.ids} == {10}, "save really was deferred"
    result.vector_flush()
    col = VectorDatabase(vdb.root).get_collection(store.collection_name)
    live = {int(v) for v in col.ids} - {int(v) for v in col.meta.dead_ids}
    assert live == {c.id for c in corpus}


def test_non_hot_sync_carries_the_deferred_graph_and_clears_the_debt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base, vdb, store, graph = _hot_lane_repo(tmp_path, monkeypatch)
    new_rel = "pkg/probe_hot.py"
    (repo / new_rel).write_text(
        "def probe_hot(payload):\n    return payload\n", encoding="utf-8"
    )
    incremental_sync(
        repo, base_dir=base, vdb=vdb, force_files=[new_rel], hot_lane=True, capacity_wait_s=0.05
    )
    assert store.load_meta().get("graph_pending") == [new_rel]

    patched: list[list[str] | None] = []
    real_patch = __import__("pipeline.incremental", fromlist=["x"]).patch_and_save_graph

    def _spy(extraction, root, out_json, *, prune_sources=None):
        patched.append(sorted({n.get("source_file") for n in extraction.get("nodes", [])}))
        return real_patch(extraction, root, out_json, prune_sources=prune_sources)

    monkeypatch.setattr("pipeline.incremental.patch_and_save_graph", _spy)

    # A later, unrelated non-hot sync must carry the owed file into the graph.
    (repo / "pkg" / "other.py").write_text("def other():\n    return 2\n", encoding="utf-8")
    result = incremental_sync(
        repo,
        base_dir=base,
        vdb=vdb,
        force_files=["pkg/other.py"],
        capacity_wait_s=0.05,
    )

    assert result.error is None, result.error
    assert patched, "non-hot sync must patch the graph"
    assert any(new_rel in (sources or []) for sources in patched), (
        f"deferred file never reached the graph: {patched}"
    )
    assert not store.load_meta().get("graph_pending"), "debt must be cleared"
    assert result.graph_pending is None


def test_catchup_with_no_chunk_delta_still_clears_the_graph_debt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The catch-up for an owed file usually has nothing to re-embed.

    That branch used to return before saving meta, so ``graph_pending`` grew
    forever even though the graph merge had run.
    """
    repo, base, vdb, store, graph = _hot_lane_repo(tmp_path, monkeypatch)
    new_rel = "pkg/probe_hot.py"
    (repo / new_rel).write_text("def probe_hot(payload):\n    return payload\n", encoding="utf-8")
    hot = incremental_sync(
        repo, base_dir=base, vdb=vdb, force_files=[new_rel], hot_lane=True, capacity_wait_s=0.05
    )
    hot.vector_flush()
    assert store.load_meta().get("graph_pending") == [new_rel]

    # The keeper's catch-up: same file, non-hot, nothing changed since the save.
    result = incremental_sync(
        repo, base_dir=base, vdb=vdb, force_files=[new_rel], capacity_wait_s=0.05
    )

    assert result.error is None, result.error
    assert result.strategy == "none", "no chunk delta on the catch-up"
    assert not store.load_meta().get("graph_pending"), "debt must be cleared"
    nodes = json.loads(graph.read_text(encoding="utf-8")).get("nodes") or []
    assert any(new_rel in str(n.get("source_file") or "") for n in nodes), (
        "the catch-up must have merged the file into graph.json"
    )
