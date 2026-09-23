"""multi_seed_v1 unit + dual-seed pack smoke."""

from __future__ import annotations

from pathlib import Path

import pytest

from trace_lab.multi_seed import merge_seed_heatmaps, seed_specs_from_args
from trace_lab.types import HeatCell, Heatmap

ROOT = Path(__file__).resolve().parents[1]


def test_seed_covered_by_heatmap_and_light() -> None:
    from trace_lab.multi_seed import light_seed_heatmap, seed_covered_by_heatmap

    hm = Heatmap(
        strategy="t1",
        cells=[
            HeatCell(node_id="packages/a.py::Foo", score=0.9, why="seed"),
            HeatCell(node_id="packages/b.py::Bar", score=0.4, why="hop"),
        ],
    )
    assert seed_covered_by_heatmap(hm, "packages/a.py::Foo") is True
    assert seed_covered_by_heatmap(hm, "packages/c.py::Other") is False
    light = light_seed_heatmap("packages/a.py::Foo", graph=None)
    assert light.strategy == "multi_seed_light"
    assert any(c.node_id == "packages/a.py::Foo" for c in light.cells)


def test_seed_specs_from_args_dedupes_and_caps() -> None:
    specs = seed_specs_from_args(
        seed_file="packages/a.py",
        seed_symbol="A",
        seed2_file="packages/b.py",
        seed2_symbol="B",
        seed3_file="packages/c.py",
        seed3_symbol="C",
    )
    assert len(specs) == 3
    specs2 = seed_specs_from_args(
        seed_file="packages/a.py",
        seed_symbol="A",
        seed2_file="packages/a.py",
        seed2_symbol="A",
    )
    assert len(specs2) == 1


def test_merge_agreement_boosts_shared_nodes() -> None:
    hm1 = Heatmap(
        strategy="t1",
        cells=[
            HeatCell(node_id="a::S1", score=0.9, why="seed"),
            HeatCell(node_id="bridge::X", score=0.5, why="hop"),
            HeatCell(node_id="only1::Y", score=0.8, why="side"),
        ],
    )
    hm2 = Heatmap(
        strategy="t2",
        cells=[
            HeatCell(node_id="b::S2", score=0.9, why="seed"),
            HeatCell(node_id="bridge::X", score=0.55, why="hop"),
            HeatCell(node_id="only2::Z", score=0.8, why="side"),
        ],
    )
    merged = merge_seed_heatmaps([hm1, hm2], ["a::S1", "b::S2"], graph=None)
    assert merged.strategy == "multi_seed_v1"
    by = {c.node_id: c.score for c in merged.cells}
    # Shared bridge should outrank single-island side nodes after agreement.
    assert by["bridge::X"] > by["only1::Y"]
    assert by["bridge::X"] > by["only2::Z"]
    assert "agree" in (next(c.why for c in merged.cells if c.node_id == "bridge::X"))


def test_pick_suggested_seeds_prefers_distinct_files() -> None:
    from pipeline.context_trace import pick_suggested_seeds

    cards = [
        {
            "file": "packages/pipeline/capability.py",
            "symbol": "CapabilityIndex",
            "kind": "class",
            "role": "class",
            "score": 20.0,
            "start_line": 425,
            "end_line": 464,
        },
        {
            "file": "packages/pipeline/engine.py",
            "symbol": "promotable_cards",
            "kind": "function",
            "role": "function",
            "score": 18.0,
            "start_line": 74,
            "end_line": 93,
        },
        {
            "file": "tests/test_capability_promotion.py",
            "symbol": "_index",
            "kind": "function",
            "role": "test",
            "score": 19.0,
            "start_line": 1,
            "end_line": 2,
        },
    ]
    seeds = pick_suggested_seeds(
        cards,
        query="CapabilityIndex locate promotable_cards packages/pipeline/capability.py engine",
        limit=3,
    )
    assert seeds
    assert seeds[0]["file"].endswith("capability.py")
    files = [s["file"] for s in seeds]
    assert len(files) == len(set(files))
    assert not any(f.startswith("tests/") for f in files)


def test_dual_seed_pack_uses_multi_seed_engine() -> None:
    from pipeline.context_trace import run_pack_context

    out = run_pack_context(
        ROOT,
        (
            "write_project_tool_surface mcp.json autoApprove permissions mcpAllowlist "
            "merge_cursor_permissions apply_permissions_to_repo_tool_surface "
            "packages/pipeline/rules_installer.py packages/pipeline/mcp_permissions.py"
        ),
        seed_file="packages/pipeline/rules_installer.py",
        seed_symbol="write_project_tool_surface",
        seed2_file="packages/pipeline/mcp_permissions.py",
        seed2_symbol="merge_cursor_permissions",
        mode="lean",
        policy="strict",
        include_bodies=False,
        k=16,
    )
    assert out.get("ok") is True
    assert out.get("seed2") is not None
    ms = out.get("multi_seed") or {}
    assert ms.get("engine") in {"multi_seed_v1", "multi_seed_v1_max"}
    ids = {c.get("id") or "" for c in (out.get("heatmap") or [])}
    assert any("write_project_tool_surface" in i for i in ids)
    assert any("merge_cursor_permissions" in i or "mcp_permissions" in i for i in ids)
