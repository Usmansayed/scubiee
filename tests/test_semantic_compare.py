"""Tests for semantic comparators."""

from __future__ import annotations

from trace_lab.embed_field import EmbedField
from trace_lab.semantic_compare import SemanticComparator, edge_text
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


def test_edge_text_format() -> None:
    assert edge_text("a", "calls", "b") == "a --calls--> b"


def test_node_sim_blend_and_path() -> None:
    seed = _node("a.py", "auth", "authenticate bearer jwt token verify")
    good = _node("b.py", "verify", "verify jwt token signature claims")
    junk = _node("c.py", "log", "logger info debug print metrics")
    nodes = {n.id: n for n in (seed, good, junk)}
    field = EmbedField(nodes, require_real=False, quiet=True)
    cmp = SemanticComparator.from_field(
        field,
        nodes,
        query="verify jwt authentication token",
        seed_id=seed.id,
    )
    assert cmp.node_sim(seed.id) >= cmp.node_sim(junk.id)
    # path mean excludes seed
    ps = cmp.path_sim((seed.id, good.id))
    assert abs(ps - cmp.node_sim(good.id)) < 1e-9
    assert cmp.path_sim((seed.id,)) == 1.0


def test_edge_sim_cached_and_positive() -> None:
    seed = _node("a.py", "auth", "authenticate")
    dst = _node("b.py", "verify", "verify jwt")
    nodes = {seed.id: seed, dst.id: dst}
    field = EmbedField(nodes, require_real=False, quiet=True)
    cmp = SemanticComparator.from_field(
        field, nodes, query="jwt verify", seed_id=seed.id
    )
    a = cmp.edge_sim(seed.id, "calls", dst.id)
    b = cmp.edge_sim(seed.id, "calls", dst.id)
    assert a == b
    assert 0.0 <= a <= 1.0
