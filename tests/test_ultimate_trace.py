"""Smoke tests for ultimate_trace v1."""

from __future__ import annotations

from pathlib import Path

from trace_lab.strategies import compile_bundle
from trace_lab.types import GoldCase, GoldRef


def test_ultimate_trace_runs_on_fixture_auth() -> None:
    root = Path(__file__).resolve().parents[1] / "fixtures" / "trace-lab"
    assert root.is_dir()
    nodes, graph, lex, tracers = compile_bundle(root, with_graphify=True, with_embed_power=False)
    assert "ultimate_trace" in tracers
    seed = GoldRef(file="app/middleware/auth.py", symbol="authenticate")
    # resolve symbol if AuthMiddleware method naming differs
    if seed.id not in nodes:
        candidates = [n for n in nodes.values() if n.file.endswith("middleware/auth.py") and n.kind in {"function", "method"}]
        assert candidates, "no auth seed"
        n0 = sorted(candidates, key=lambda n: n.start_line)[0]
        seed = GoldRef(file=n0.file, symbol=n0.symbol)
    case = GoldCase(
        id="auth",
        title="auth",
        query="How does JWT authentication verify bearer tokens and load the user?",
        seed=seed,
        must=[],
        should=[],
        must_not=[],
        gold_rank=[],
    )
    hm = tracers["ultimate_trace"](case, nodes, graph, lex)
    assert hm.strategy == "ultimate_trace"
    assert hm.cells
    assert hm.cells[0].score >= 0.9
    ids = {c.node_id for c in hm.cells}
    assert seed.id in ids
