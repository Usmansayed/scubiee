"""semantic_tracer_v1 runs and uses sem_edge why tags."""

from __future__ import annotations

from trace_lab.cases import default_fixture_root, load_cases
from trace_lab.strategies import compile_bundle


def test_semantic_tracer_v1_registered_and_runs() -> None:
    root = default_fixture_root()
    nodes, graph, lex, tracers = compile_bundle(
        root, with_graphify=False, with_embed_power=True, require_real_embeds=False
    )
    assert "semantic_tracer_v1" in tracers
    cases = load_cases(root / "cases")
    case = next(c for c in cases if c.seed.id in nodes)
    hm = tracers["semantic_tracer_v1"](case, nodes, graph, lex)
    assert hm.strategy == "semantic_tracer_v1"
    assert hm.cells
    assert hm.extra.get("engine") == "semantic_tracer_v1"
    # At least seed should be present; deeper nodes often carry sem_edge
    assert any(c.node_id == case.seed.id for c in hm.cells)
    tagged = [c for c in hm.cells if c.node_id != case.seed.id]
    if tagged:
        assert any("sem_edge" in c.why or "sem_path" in c.why for c in tagged)
