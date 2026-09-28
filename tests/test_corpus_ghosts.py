"""Deleted-while-down files must not stay searchable (found while testing issue 2/4)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace


def _loop_with_store(tmp_path: Path, monkeypatch, rows: list[dict]):
    from pipeline.sync_loop import BackgroundSyncLoop

    repo = tmp_path / "repo"
    store = tmp_path / "store"
    (repo / "pkg").mkdir(parents=True)
    store.mkdir()
    (store / "chunks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    monkeypatch.setattr(
        "pipeline.project_id.peek_project",
        lambda _root: SimpleNamespace(store_dir=store, project_id="ce_x"),
    )
    fake = SimpleNamespace(repo=repo)
    return fake, repo, BackgroundSyncLoop


def test_corpus_ghosts_lists_only_files_missing_on_disk(tmp_path, monkeypatch):
    fake, repo, loop_cls = _loop_with_store(
        tmp_path,
        monkeypatch,
        [
            {"id": 0, "file": "pkg/live.py", "text": "x"},
            {"id": 1, "file": "pkg/zz_disksave_1.py", "text": "y"},
            {"id": 2, "file": "pkg/zz_disksave_1.py", "text": "z"},
            {"id": 3, "file": "pkg\\gone_windows.py", "text": "w"},
        ],
    )
    (repo / "pkg" / "live.py").write_text("x", encoding="utf-8")
    assert loop_cls._corpus_ghosts(fake) == ["pkg/gone_windows.py", "pkg/zz_disksave_1.py"]


def test_newcomer_scan_queues_ghosts_for_removal(tmp_path, monkeypatch):
    fake, repo, loop_cls = _loop_with_store(
        tmp_path, monkeypatch, [{"id": 0, "file": "pkg/ghost.py", "text": "x"}]
    )
    marked: list = []
    fake._corpus_ghosts = lambda: loop_cls._corpus_ghosts(fake)
    fake.dirty_ledger = SimpleNamespace(snapshot=lambda: {"paths": {}})
    fake.mark_dirty = lambda paths, **kw: marked.append((list(paths), kw.get("reason")))
    monkeypatch.setattr(
        "pipeline.root_probe.root_probe", lambda *_a, **_k: SimpleNamespace(added=[])
    )
    out = loop_cls._enqueue_newcomers(fake, now=1.0)
    assert out == ["pkg/ghost.py"]
    assert marked == [(["pkg/ghost.py"], "disk_poll")]


def test_forced_ghost_missing_from_merkle_is_removed(monkeypatch, tmp_path):
    """A chunk-only file (not on disk, not in the merkle) must be dropped.

    It used to be skipped: nothing was removed, root_probe re-reported it as a
    save every second, and that reset the hot-quiet window graph catch-ups
    wait for, so no catch-up ever ran (live: 7 held, last hot mark 0.9s ago).
    """
    import json as _json
    from unittest.mock import MagicMock

    import numpy as np

    import pipeline.incremental as incremental_module
    from pipeline.incremental import incremental_sync
    from pipeline.store import ChunkRecord, PipelineStore

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "keep.py").write_text("def keep():\n    return 1\n", encoding="utf-8")
    base = tmp_path / "store"
    base.mkdir()
    store = PipelineStore(repo, base_dir=base)

    def _rec(i, f):
        return ChunkRecord(id=i, file=f, start_line=1, end_line=2, symbol="s", text="x", enriched="x")

    store.save_chunks([_rec(1, "keep.py"), _rec(2, "pkg/zz_ghost.py")])
    store.save_meta({"chunks": 2, "dim": 4, "bits": 4})
    store.save_merkle({"keep.py": "aa"})  # the ghost is not in the merkle

    class _Emb:
        def embed_many(self, texts):
            return np.ones((len(texts), 4), dtype=np.float32)

    class _Col:
        ntotal = 2
        name = "code"

        def delete(self, ids):
            return len(list(ids))

        def add(self, vectors, ids, payloads=None):
            return len(list(ids))

    monkeypatch.setattr(incremental_module, "Embedder", lambda **_k: _Emb())
    monkeypatch.setattr("pipeline.engine.get_embedder", lambda *_a, **_k: _Emb())
    monkeypatch.setattr("pipeline.engine.clear_engines", lambda: None)
    monkeypatch.setattr(incremental_module, "_patch_capability_cards", lambda *_a, **_k: None)
    monkeypatch.setattr(incremental_module, "patch_and_save_graph", MagicMock())
    monkeypatch.setattr("pipeline.vectordb.VectorDatabase.save_collection", lambda *_a, **_k: None)
    monkeypatch.setattr(PipelineStore, "get_collection", lambda self: _Col())

    out = incremental_sync(repo, base_dir=base, force_files=["pkg/zz_ghost.py"], capacity_wait_s=0.05)
    assert out.chunks_removed == 1, (out.chunks_removed, out.error)
    files = [_json.loads(line)["file"] for line in store.chunks_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert files == ["keep.py"]


def test_indexed_subset_counts_file_merkle_and_chunk_only_paths(tmp_path, monkeypatch):
    """Gone paths the chunk merkle does not know are still indexed if the file
    merkle or chunks.jsonl names them (live: ghost completed unsynced forever)."""
    from pipeline.store import PipelineStore
    from pipeline.sync_loop import BackgroundSyncLoop

    repo = tmp_path / "repo"
    repo.mkdir()
    base = tmp_path / "store"
    base.mkdir()
    store = PipelineStore(repo, base_dir=base, resolve=False)
    store.base = base
    store.chunk_merkle_path = base / "chunk_merkle.json"
    store.chunks_path = base / "chunks.jsonl"
    store.merkle_path = base / "merkle.json"
    store.save_chunk_merkle({"pkg/known.py": {"k": "d"}})
    store.save_merkle({"pkg/in_file_merkle.py": "aa"})
    store.chunks_path.write_text(
        json.dumps({"id": 1, "file": "pkg/chunk_only.py", "text": "x"}) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        "pipeline.sync_loop.peek_project",
        lambda _root: SimpleNamespace(store_dir=base, project_id="ce_x"),
    )
    fake = SimpleNamespace(repo=repo)
    got = BackgroundSyncLoop._indexed_subset(
        fake, ["pkg/known.py", "pkg/in_file_merkle.py", "pkg/chunk_only.py", "pkg/never.py"]
    )
    assert got == {"pkg/known.py", "pkg/in_file_merkle.py", "pkg/chunk_only.py"}
