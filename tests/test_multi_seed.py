"""Unit tests for adaptive multi-seed helpers (was a missing module)."""

from __future__ import annotations

from trace_lab.ast_graph import AstTraceGraph
from trace_lab.multi_seed import (
    light_seed_heatmap,
    merge_seed_heatmaps,
    multi_seed_adaptive_enabled,
    seed_covered_by_heatmap,
    seed_specs_from_args,
)
from trace_lab.types import HeatCell, Heatmap, TraceEdge, TraceNode


def _node(nid: str, file: str = "a.py", symbol: str | None = None) -> TraceNode:
    sym = symbol or nid.split("::")[-1]
    return TraceNode(
        id=nid,
        file=file,
        symbol=sym,
        kind="function",
        start_line=1,
        end_line=10,
        text="pass",
    )


def test_seed_specs_from_args_skips_empty_slots() -> None:
    specs = seed_specs_from_args(
        seed_file="pkg/a.py",
        seed_symbol="foo",
        seed2_file="",
        seed3_file="pkg/b.py",
        seed3_line=12,
    )
    assert len(specs) == 2
    assert specs[0]["file"] == "pkg/a.py"
    assert specs[0]["symbol"] == "foo"
    assert specs[1]["file"] == "pkg/b.py"
    assert specs[1]["line"] == 12


def test_multi_seed_adaptive_env(monkeypatch) -> None:
    monkeypatch.delenv("CTX_MULTI_SEED_ADAPTIVE", raising=False)
    assert multi_seed_adaptive_enabled() is True
    monkeypatch.setenv("CTX_MULTI_SEED_ADAPTIVE", "0")
    assert multi_seed_adaptive_enabled() is False


def test_seed_covered_and_light_merge() -> None:
    n1 = _node("a.py::one")
    n2 = _node("a.py::two")
    n3 = _node("a.py::three")
    nodes = {n.id: n for n in (n1, n2, n3)}
    edges = [
        TraceEdge(source=n1.id, target=n2.id, relation="calls", weight=1.0),
        TraceEdge(source=n2.id, target=n3.id, relation="calls", weight=1.0),
    ]
    g = AstTraceGraph(nodes, edges)

    hm1 = Heatmap(
        strategy="poly",
        cells=[HeatCell(node_id=n1.id, score=1.0, why="seed"), HeatCell(node_id=n2.id, score=0.5, why="hop")],
    )
    assert seed_covered_by_heatmap(hm1, n2.id) is True
    assert seed_covered_by_heatmap(hm1, n3.id) is False

    light = light_seed_heatmap(n2.id, g, hops=1)
    assert light.by_id()[n2.id].score == 1.0
    assert n1.id in light.by_id() or n3.id in light.by_id()

    merged = merge_seed_heatmaps([hm1, light], [n1.id, n2.id], g)
    assert merged.strategy == "multi_seed_v1"
    assert merged.extra.get("mode") == "agreement_corridor"
    assert n2.id in merged.by_id()
    # n2 appears on both maps → agreement boost above the weaker map score
    assert merged.by_id()[n2.id].score >= 0.5
