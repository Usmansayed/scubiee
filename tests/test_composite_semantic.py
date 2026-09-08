"""Membership identity: composite_semantic island == composite_v1 island."""

from __future__ import annotations

from trace_lab.cases import default_fixture_root, load_cases
from trace_lab.composite_semantic import bind_composite_semantic
from trace_lab.embed_field import EmbedField
from trace_lab.strategies import compile_bundle


def test_composite_semantic_same_membership_as_composite_v1() -> None:
    root = default_fixture_root()
    nodes, graph, lex, tracers = compile_bundle(
        root, with_graphify=False, with_embed_power=False
    )
    field = EmbedField(
        nodes,
        cache_path=root / ".embed_cache" / "semantic_sensor_test.jsonl",
        require_real=False,
        quiet=True,
    )
    from trace_lab.lsp_index import build_lsp_index

    lsp = build_lsp_index(root, nodes, graph)
    tracers["composite_semantic_add"] = bind_composite_semantic(
        root, lsp, field, mode="add"
    )
    tracers["composite_semantic_gate"] = bind_composite_semantic(
        root, lsp, field, mode="gate"
    )

    cases = load_cases(root / "cases")
    case = next(c for c in cases if c.seed.id in nodes)
    struct = tracers["composite_v1"](case, nodes, graph, lex)
    add_hm = tracers["composite_semantic_add"](case, nodes, graph, lex)
    gate_hm = tracers["composite_semantic_gate"](case, nodes, graph, lex)

    struct_ids = {c.node_id for c in struct.cells}
    assert {c.node_id for c in add_hm.cells} == struct_ids
    assert {c.node_id for c in gate_hm.cells} == struct_ids
    assert add_hm.strategy == "composite_semantic_add"
    assert gate_hm.strategy == "composite_semantic_gate"
    assert any("sem_add" in c.why for c in add_hm.cells)
    assert add_hm.extra.get("semantic_mode") == "add"
    assert gate_hm.extra.get("semantic_mode") == "gate"
    # Additive should not shrink scores below structural (same alpha>0)
    s_by = struct.by_id()
    for c in add_hm.cells:
        assert c.score + 1e-9 >= s_by[c.node_id].score
