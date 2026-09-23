"""Expand callers: reverse/lexical/cross-file/query over sibling noise."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _trace_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_TRACE_PARALLEL", "1")
    monkeypatch.setenv("CTX_TRACE_ENGINE", "composite_v1")


def test_rank_expand_delta_prefers_reverse_and_cross_file() -> None:
    from pipeline.context_trace import rank_expand_delta

    seed_file = "packages/pipeline/embedder.py"
    cards = [
        {
            "id": "packages/pipeline/embedder.py::Embedder._ollama_embed",
            "file": seed_file,
            "symbol": "Embedder._ollama_embed",
            "why": "CALLS:graphify Embedder.embed_one->Embedder._ollama_embed",
            "score": 0.9,
        },
        {
            "id": "packages/pipeline/accel.py::fastembed_cache_root",
            "file": "packages/pipeline/accel.py",
            "symbol": "fastembed_cache_root",
            "why": "CALLS:graphify Embedder._embed_cpu_backup->fastembed_cache_root",
            "score": 0.95,
        },
        {
            "id": "packages/pipeline/indexer.py::index_repo",
            "file": "packages/pipeline/indexer.py",
            "symbol": "index_repo",
            "why": "expand:text_call Embedder.embed_many<-index_repo",
            "score": 0.5,
            "evidence": "text_call",
        },
        {
            "id": "packages/pipeline/embedder.py::text_key",
            "file": seed_file,
            "symbol": "text_key",
            "why": "expand:called_by Embedder.embed_many->text_key",
            "score": 0.36,
            "evidence": "called_by",
        },
    ]
    ranked = rank_expand_delta(
        cards,
        seed_file=seed_file,
        query="index_repo engine callers of embed_many",
        direction="callers",
    )
    top = [c["symbol"] for c in ranked[:2]]
    assert "index_repo" in top
    assert ranked[0]["symbol"] == "index_repo"
    # Forward sibling noise should not beat reverse/text callers
    assert ranked[0]["symbol"] != "Embedder._ollama_embed"


def test_rank_expand_delta_callees_keep_direct_same_file_call() -> None:
    from pipeline.context_trace import rank_expand_delta

    seed_file = "packages/pipeline/context_trace.py"
    cards = [
        {
            "id": "packages/trace_lab/corpus.py::corpus_fingerprint",
            "file": "packages/trace_lab/corpus.py",
            "symbol": "corpus_fingerprint",
            "why": "USES:corpus run_pack_context->corpus_fingerprint",
            "score": 1.0,
        },
        {
            "id": "packages/pipeline/context_trace.py::resolve_seed_node",
            "file": seed_file,
            "symbol": "resolve_seed_node",
            "why": "expand:calls run_pack_context->resolve_seed_node",
            "score": 0.7,
        },
    ]
    ranked = rank_expand_delta(
        cards,
        seed_file=seed_file,
        query="run_pack_context callees",
        direction="callees",
        seed_symbol="run_pack_context",
    )
    assert ranked[0]["symbol"] == "resolve_seed_node"


def test_expand_callers_embed_many_surfaces_index_repo() -> None:
    from pipeline.context_trace import run_expand_context, run_pack_context

    q = "index_repo engine callers embed_many encode batch"
    pack = run_pack_context(
        ROOT,
        q,
        seed_file="packages/pipeline/embedder.py",
        seed_symbol="embed_many",
        mode="lean",
        include_bodies=False,
        k=12,
    )
    assert pack.get("ok") is True
    seed_id = pack["seed"]["id"]
    pack_ids = {c.get("id") for c in pack["_persist"]["cards"] if c.get("id")}
    out = run_expand_context(
        ROOT,
        seed_id,
        query=q,
        direction="callers",
        k=10,
        prior_ids=set(),
        pack_seen_ids=pack_ids,
    )
    assert out.get("ok") is True
    syms = [str(c.get("symbol") or "") for c in (out.get("delta") or [])]
    files = [str(c.get("file") or "") for c in (out.get("delta") or [])]
    assert any("index_repo" in s for s in syms) or any("indexer.py" in f for f in files)
    # Top half should not be dominated by same-file GPU helpers
    top5 = (out.get("delta") or [])[:5]
    helperish = sum(
        1
        for c in top5
        if any(
            x in str(c.get("symbol") or "").lower()
            for x in ("ollama", "coreml", "pad_embed", "fastembed_cache")
        )
    )
    assert helperish <= 2
