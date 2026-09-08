"""Tests for semantic best-first expansion."""

from __future__ import annotations

from trace_lab.engine.frontier import build_frontier
from trace_lab.engine.semantic_best_first import semantic_best_first_expand
from trace_lab.facts import TypedEdge
from trace_lab.policy.intent import TraceSpec
from trace_lab.types import TraceNode, node_id


class _FakeCmp:
    def __init__(self, edge_prefs: dict[str, float], node_prefs: dict[str, float] | None = None):
        self.edge_prefs = edge_prefs
        self.node_prefs = node_prefs or {}

    def edge_sim(self, src_id: str, rel: str, dst_id: str) -> float:
        return float(self.edge_prefs.get(dst_id, 0.1))

    def node_sim(self, nid: str) -> float:
        return float(self.node_prefs.get(nid, 0.5))

    def path_sim(self, path: tuple[str, ...]) -> float:
        ids = [p for p in path[1:]] if path else []
        if not ids:
            return 1.0
        return sum(self.node_sim(n) for n in ids) / len(ids)


def _n(file: str, sym: str) -> TraceNode:
    return TraceNode(
        id=node_id(file, sym),
        file=file,
        symbol=sym,
        kind="function",
        start_line=1,
        end_line=2,
        text=sym,
        lex_text=sym,
    )


def test_higher_edge_sem_admits_preferred_child() -> None:
    seed = _n("a.py", "seed")
    good = _n("a.py", "verify")
    junk = _n("a.py", "logger")
    nodes = {seed.id: seed, good.id: good, junk.id: junk}
    edges = [
        TypedEdge(seed.id, good.id, "calls", 1.0, confidence="ast"),
        TypedEdge(seed.id, junk.id, "calls", 1.0, confidence="ast"),
    ]
    frontier = build_frontier(edges)
    spec = TraceSpec(mode="flow", user_query="verify jwt", hop_cap=4)
    cmp = _FakeCmp({good.id: 0.95, junk.id: 0.05}, {good.id: 0.9, junk.id: 0.1})
    scores, why, paths, _ = semantic_best_first_expand(
        seed.id, nodes, frontier, spec, cmp, floor=0.05
    )
    assert good.id in scores
    assert junk.id in scores
    assert scores[good.id] > scores[junk.id]
    assert "sem_edge" in why[good.id]
    assert "sem_path" in why[good.id]
    assert paths[good.id][0] == seed.id


def test_does_not_invent_edges() -> None:
    seed = _n("a.py", "seed")
    orphan = _n("b.py", "orphan")
    nodes = {seed.id: seed, orphan.id: orphan}
    frontier = build_frontier([])
    spec = TraceSpec(mode="flow", user_query="x", hop_cap=4)
    cmp = _FakeCmp({orphan.id: 1.0}, {orphan.id: 1.0})
    scores, _, _, _ = semantic_best_first_expand(seed.id, nodes, frontier, spec, cmp)
    assert set(scores) == {seed.id}
