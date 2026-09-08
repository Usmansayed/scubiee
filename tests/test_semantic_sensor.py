"""Unit tests for composite semantic sensor (Phase 0)."""

from __future__ import annotations

from trace_lab.semantic_sensor import (
    ALPHA_DEFAULT,
    SEM_GATE_FACTOR,
    TAU_DEFAULT,
    W_QUERY,
    W_SEED,
    apply_additive,
    apply_gate,
    blend_sem,
    is_spine_protected,
)
from trace_lab.types import HeatCell, Heatmap


def test_blend_sem_weights() -> None:
    assert abs(blend_sem(1.0, 0.0) - W_QUERY) < 1e-9
    assert abs(blend_sem(0.0, 1.0) - W_SEED) < 1e-9
    assert abs(blend_sem(0.5, 0.5) - 0.5) < 1e-9


def test_additive_clamps_and_tags() -> None:
    hm = Heatmap(
        strategy="composite_v1",
        cells=[
            HeatCell("a.py::seed", 1.0, "seed", path=("a.py::seed",)),
            HeatCell("a.py::hot", 0.5, "calls", path=("a.py::seed", "a.py::hot")),
        ],
    )
    out = apply_additive(
        hm,
        {"a.py::seed": 0.9, "a.py::hot": 1.0},
        alpha=0.15,
        strategy="composite_semantic_add",
    )
    assert {c.node_id for c in out.cells} == {"a.py::seed", "a.py::hot"}
    by = out.by_id()
    assert by["a.py::hot"].score == min(1.0, 0.5 + 0.15 * 1.0)
    assert "sem_add" in by["a.py::hot"].why
    assert out.strategy == "composite_semantic_add"
    assert out.extra.get("semantic_mode") == "add"
    assert out.extra.get("alpha") == ALPHA_DEFAULT or out.extra.get("alpha") == 0.15


def test_gate_demotes_low_sem() -> None:
    hm = Heatmap(
        strategy="composite_v1",
        cells=[
            HeatCell("a.py::seed", 1.0, "seed", path=("a.py::seed",)),
            HeatCell("a.py::noise", 0.6, "calls", path=("a.py::seed", "a.py::noise")),
        ],
    )
    # path depth 2 but struct 0.6 >= 0.45 → spine protected; use shallow path + low struct
    hm2 = Heatmap(
        strategy="composite_v1",
        cells=[
            HeatCell("a.py::seed", 1.0, "seed", path=("a.py::seed",)),
            HeatCell("a.py::noise", 0.3, "calls", path=("a.py::noise",)),
        ],
    )
    out = apply_gate(
        hm2,
        {"a.py::seed": 0.9, "a.py::noise": 0.1},
        tau=TAU_DEFAULT,
        factor=SEM_GATE_FACTOR,
        seed_id="a.py::seed",
        strategy="composite_semantic_gate",
    )
    by = out.by_id()
    assert by["a.py::seed"].score == 1.0
    assert by["a.py::noise"].score == round(0.3 * SEM_GATE_FACTOR, 4)
    assert "sem_gate" in by["a.py::noise"].why


def test_gate_never_demotes_seed() -> None:
    hm = Heatmap(
        strategy="composite_v1",
        cells=[HeatCell("a.py::seed", 1.0, "seed", path=("a.py::seed",))],
    )
    out = apply_gate(
        hm,
        {"a.py::seed": 0.0},
        tau=0.99,
        factor=0.1,
        seed_id="a.py::seed",
    )
    assert out.by_id()["a.py::seed"].score == 1.0
    assert "sem_gate" not in out.by_id()["a.py::seed"].why


def test_spine_protection_dfg_and_path() -> None:
    dfg = HeatCell("a.py::x", 0.5, "calls|dfg_boost", path=("a.py::s", "a.py::x"))
    assert is_spine_protected(dfg, seed_id="a.py::s") is True
    deep = HeatCell("a.py::y", 0.5, "calls", path=("a.py::s", "a.py::y"))
    assert is_spine_protected(deep, seed_id="a.py::s") is True
    shallow_low = HeatCell("a.py::z", 0.3, "calls", path=("a.py::z",))
    assert is_spine_protected(shallow_low, seed_id="a.py::s") is False
