"""Full local e2e: index mini-repo → FAISS collection on disk → search → reload."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from pipeline.indexer import index_repo
from pipeline.searcher import search_repo
from pipeline.store import PipelineStore
from pipeline.vectordb import VectorDatabase


MINI = ROOT / "fixtures" / "mini-repo"


@pytest.mark.skipif(not MINI.exists(), reason="mini-repo fixture missing")
def test_full_pipeline_stores_in_faiss_collection(
    tmp_path: Path, cpu_accel_profile: Path, monkeypatch: pytest.MonkeyPatch
):
    del cpu_accel_profile
    import numpy as np

    def _fake_embed_many(self, texts, progress=None):
        return np.ones((len(texts), 768), dtype=np.float32)

    monkeypatch.setattr("pipeline.embedder.Embedder.embed_many", _fake_embed_many)
    monkeypatch.delenv("CTX_SEARCH_URL", raising=False)
    monkeypatch.delenv("CTX_ENGINE_URL", raising=False)
    vdb_root = tmp_path / "vectordb"
    index_base = tmp_path / "indexes" / "mini"
    vdb = VectorDatabase(root=vdb_root)

    stats = index_repo(MINI, force=True, bits=4, base_dir=index_base, vdb=vdb)
    assert stats.chunks >= 3
    assert stats.vector_stats.get("faiss_ntotal", 0) == stats.chunks
    assert stats.vector_stats.get("compressed_bytes", 0) > 0

    store = PipelineStore(MINI, base_dir=index_base, vdb=vdb)
    col = store.get_collection()
    assert col is not None
    assert col.ntotal == stats.chunks

    cdir = vdb_root / "collections" / col.name
    assert (cdir / "faiss.index").is_file()
    assert (cdir / "turboquant.npz").is_file()
    assert (cdir / "payloads.jsonl").is_file()
    meta = json.loads((cdir / "meta.json").read_text(encoding="utf-8"))
    assert meta["cwd"] == str(MINI.resolve())
    assert meta["ntotal"] == stats.chunks

    catalog = json.loads((vdb_root / "catalog.json").read_text(encoding="utf-8"))
    assert any(c["name"] == col.name for c in catalog["collections"])

    hits = search_repo(
        MINI,
        "login validatePassword",
        base_dir=index_base,
        vdb=vdb,
        use_server=False,
    )
    assert len(hits) >= 1
    files = {h.file for h in hits}
    assert any("login" in f or "validate" in f for f in files)

    cold = VectorDatabase(root=vdb_root)
    col2 = cold.get_collection(col.name)
    assert col2.ntotal == stats.chunks

    q = col2.compressed.to_float32()[0]
    direct = col2.search(q, top_k=1)
    assert len(direct) == 1
    assert direct[0][0] in set(range(stats.chunks))
