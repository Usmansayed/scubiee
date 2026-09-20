"""D_channel_best ranking must stay exact; only the index structures change."""

from __future__ import annotations

import networkx as nx
import numpy as np

from conductor.architectures import MultiArchConductor
from conductor.bm25_index import BM25Index, tokenize
from conductor.conductor import ConductorConfig
from conductor.dense_index import DenseIndex
from conductor.graphify_retriever import ChunkSpan, GraphifyChunkRetriever


def _okapi_loop(idx: BM25Index, query: str) -> np.ndarray:
    """Independent copy of the original per-doc Okapi BM25 formula."""
    q_terms = tokenize(query)
    scores = np.zeros(idx.N, dtype=np.float64)
    if not q_terms or idx.N == 0:
        return scores
    for i, tf in enumerate(idx._tf):
        dl = idx.doc_len[i]
        denom_norm = idx.k1 * (1 - idx.b + idx.b * dl / max(idx.avgdl, 1e-9))
        s = 0.0
        for t in q_terms:
            if t not in tf:
                continue
            idf = idx.idf.get(t, 0.0)
            f = tf[t]
            s += idf * (f * (idx.k1 + 1)) / (f + denom_norm)
        scores[i] = s
    return scores


def _tiny_conductor(texts: list[str], files: list[str] | None = None) -> MultiArchConductor:
    files = files or [f"f{i}.py" for i in range(len(texts))]
    G = nx.Graph()
    spans: list[ChunkSpan] = []
    for i, f in enumerate(files):
        G.add_node(f"n{i}", source_file=f, source_location="L1")
        spans.append(ChunkSpan(index=i, file=f, start_line=1, end_line=2))
    dim = 8
    mat = np.eye(len(texts), dim, dtype=np.float32)
    return MultiArchConductor(
        files=files,
        bm25=BM25Index(texts),
        dense=DenseIndex(mat),
        graph=GraphifyChunkRetriever(G, spans, depth=1),
        config=ConductorConfig(),
    )


def test_bm25_score_all_matches_okapi_loop() -> None:
    corpus = [
        "def score_all query tokenize idf",
        "class BM25Index inverted postings",
        "dense matrix cosine retrieve_D_channel_best",
        "alpha alpha beta",
        "",
    ]
    idx = BM25Index(corpus)
    for q in ("score_all tokenize", "alpha alpha", "missingterm", "", "BM25Index postings"):
        got = idx.score_all(q)
        want = _okapi_loop(idx, q)
        assert got.shape == want.shape
        np.testing.assert_allclose(got, want, rtol=1e-12, atol=1e-12)


def test_bm25_builds_inverted_postings() -> None:
    idx = BM25Index(["alpha beta", "beta gamma", "delta"])
    assert hasattr(idx, "_postings")
    docs, freqs = idx._postings["beta"]
    assert set(int(i) for i in docs) == {0, 1}
    assert freqs.shape == docs.shape
    assert idx._denom.shape == (idx.N,)


def test_bm25_cache_load_rebuilds_postings(tmp_path) -> None:
    from pipeline.bm25_cache import load_or_build_bm25, save_bm25_cache, load_bm25_cache, chunks_fingerprint

    texts = ["graph affinity bm25 dense", "retrieve_D_channel_best hybrid"]
    (tmp_path / "chunks.jsonl").write_text("x\n", encoding="utf-8")
    idx = BM25Index(texts)
    save_bm25_cache(tmp_path, idx, fingerprint=chunks_fingerprint(tmp_path))
    loaded = load_bm25_cache(tmp_path, fingerprint=chunks_fingerprint(tmp_path))
    assert loaded is not None
    assert hasattr(loaded, "_postings")
    q = "bm25 dense retrieve"
    np.testing.assert_allclose(loaded.score_all(q), idx.score_all(q), rtol=1e-12, atol=1e-12)
    again, meta = load_or_build_bm25(tmp_path, texts)
    assert meta["source"] == "cache"
    np.testing.assert_allclose(again.score_all(q), idx.score_all(q), rtol=1e-12, atol=1e-12)


def test_channel_maps_does_not_call_search() -> None:
    cond = _tiny_conductor(["alpha token bm25", "bravo dense graph"])
    q = np.ones(8, dtype=np.float32)

    def _boom(*_a, **_k):
        raise AssertionError("search() must not rescan after score_all")

    cond.bm25.search = _boom  # type: ignore[method-assign]
    cond.dense.search = _boom  # type: ignore[method-assign]
    g_aff, b_all, d_all, hybrid, _seeds = cond._channel_maps("alpha token", q)
    assert g_aff.shape == b_all.shape == d_all.shape == hybrid.shape == (2,)
    assert np.isfinite(hybrid).all()
    assert float(b_all[0]) > float(b_all[1])


def test_channel_maps_reuses_process_pool() -> None:
    from conductor.channel_pool import channel_pool

    a = channel_pool()
    b = channel_pool()
    assert a is b
    cond = _tiny_conductor(["alpha", "bravo"])
    q = np.ones(8, dtype=np.float32)
    cond._channel_maps("alpha", q)
    cond._channel_maps("bravo", q)
    assert channel_pool() is a


def test_d_channel_best_file_order_from_full_scores() -> None:
    texts = [
        "def retrieve_D_channel_best fusion union leaders",
        "bm25 inverted postings score_all tokenize",
        "dense cosine matrix query_vec",
    ]
    files = [
        "packages/conductor/architectures.py",
        "packages/conductor/bm25_index.py",
        "packages/conductor/dense_index.py",
    ]
    cond = _tiny_conductor(texts, files)
    qvec = np.zeros(8, dtype=np.float32)
    qvec[1] = 1.0  # aligns with row 1 after L2 (eye row)
    hits = cond.retrieve_D_channel_best("bm25 inverted postings score_all", qvec, top_k=3)
    assert hits
    files_out = [h.file.replace("\\", "/") for h in hits]
    assert "packages/conductor/bm25_index.py" in files_out
