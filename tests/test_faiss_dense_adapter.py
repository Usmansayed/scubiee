"""FAISS labels must map to positional conductor rows after incremental gaps."""

from __future__ import annotations

from types import SimpleNamespace

import networkx as nx
import numpy as np

from conductor.architectures import MultiArchConductor
from conductor.bm25_index import BM25Index
from conductor.conductor import ConductorConfig
from conductor.dense_index import DenseIndex
from conductor.graphify_retriever import ChunkSpan, GraphifyChunkRetriever
from pipeline.searcher import FaissDenseAdapter


class _FakeCol:
    def __init__(self, ids: list[int], matrix: np.ndarray):
        self.ids = ids
        self.compressed = SimpleNamespace(to_float32=lambda: matrix)
        self.meta = SimpleNamespace(dim=matrix.shape[1])
        self._hits: list[tuple[int, float, dict]] = []

    def search(self, _query, top_k: int = 50):
        return self._hits[:top_k]


def test_faiss_adapter_maps_gapped_ids_to_rows():
    mat = np.eye(3, 4, dtype=np.float32)
    col = _FakeCol(ids=[0, 1, 2772], matrix=mat)
    col._hits = [(2772, 0.91, {})]
    adapter = FaissDenseAdapter(col, n_chunks=3)
    hits = adapter.search(np.ones(4, dtype=np.float32), top_k=5)
    assert hits == [(2, 0.91)]


def test_channel_maps_skips_out_of_range_dense_ids():
    files = ["a.py", "b.py"]
    texts = ["alpha token", "bravo token"]
    G = nx.Graph()
    G.add_node("n0", source_file="a.py", source_location="L1")
    spans = [
        ChunkSpan(index=0, file="a.py", start_line=1, end_line=2),
        ChunkSpan(index=1, file="b.py", start_line=1, end_line=2),
    ]
    graph = GraphifyChunkRetriever(G, spans, depth=1)
    bm25 = BM25Index(texts)

    class _DenseOob(DenseIndex):
        def search(self, query_vec, top_k: int = 50):
            return [(2772, 0.99)]

    conductor = MultiArchConductor(
        files=files,
        bm25=bm25,
        dense=_DenseOob(np.eye(2, 4, dtype=np.float32)),
        graph=graph,
        config=ConductorConfig(),
    )
    q = np.ones(4, dtype=np.float32)
    g_aff, b_all, d_all, hybrid, _seeds = conductor._channel_maps("token", q)
    assert hybrid.shape == (2,)
    assert np.isfinite(hybrid).all()
    assert g_aff.shape == (2,)
    assert b_all.shape == (2,)
    assert d_all.shape == (2,)
