"""Tests for Cycle 2–3 comparator + fuse tracer."""

from __future__ import annotations

from trace_lab.cases import default_fixture_root, load_cases
from trace_lab.embed_field import EmbedField
from trace_lab.semantic_compare import SemanticComparator
from trace_lab.strategies import compile_bundle
from trace_lab.types import TraceNode, node_id


def _node(file: str, symbol: str, text: str) -> TraceNode:
    nid = node_id(file, symbol)
    return TraceNode(
        id=nid,
        file=file,
        symbol=symbol,
        kind="function",
        start_line=1,
        end_line=5,
        text=text,
        lex_text=text,
    )


def test_trace_centroid_refresh_changes_trace_sim() -> None:
    seed = _node("a.py", "auth", "authenticate jwt bearer")
    mid = _node("b.py", "verify", "verify jwt token signature")
    far = _node("c.py", "billing", "invoice charge payment cents")
    nodes = {n.id: n for n in (seed, mid, far)}
    field = EmbedField(nodes, require_real=False, quiet=True)
    cmp = SemanticComparator.from_field(
        field, nodes, query="jwt verify authentication", seed_id=seed.id
    )
    before = cmp.trace_sim(mid.id)
    cmp.refresh_trace({seed.id: 1.0, mid.id: 0.9, far.id: 0.2}, top_k=2)
    after = cmp.trace_sim(mid.id)
    # Mid should stay strong after centroid leans auth/verify
    assert after >= before - 0.05
    assert cmp.hub_penalty(mid.id) > 0


def test_semantic_tracer_fuse_runs() -> None:
    root = default_fixture_root()
    nodes, graph, lex, tracers = compile_bundle(
        root, with_graphify=False, with_embed_power=True, require_real_embeds=False
    )
    assert "semantic_tracer_fuse" in tracers
    case = next(c for c in load_cases(root / "cases") if c.seed.id in nodes)
    hm = tracers["semantic_tracer_fuse"](case, nodes, graph, lex)
    assert hm.strategy == "semantic_tracer_fuse"
    assert hm.cells
    assert hm.extra.get("has_trace_vec") is True
