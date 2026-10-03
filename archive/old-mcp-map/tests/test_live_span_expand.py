"""Collect/expand must read the current file, not a stale AST bake."""
from __future__ import annotations

from pathlib import Path

from pipeline.context_trace import ensure_seeds_on_heatmap, live_symbol_span, refresh_node_from_disk
from pipeline.mcp_locate import (
    _collect_hot_from_card_locs,
    _expand_heatmap_ref,
    _lean_pack_fallback_heatmap,
)
from trace_lab.types import TraceNode


def test_live_symbol_span_follows_edit(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    path = pkg / "beacon.py"
    path.write_text(
        "def outcome_beacon_zulu():\n    return 'OUTCOME_ZULU_9917'\n",
        encoding="utf-8",
    )
    span = live_symbol_span(tmp_path, "pkg/beacon.py", "outcome_beacon_zulu")
    assert span is not None
    assert span[0] == 1
    assert "OUTCOME_ZULU_9917" in span[2]

    path.write_text(
        "\n\ndef outcome_beacon_zulu():\n    return 'OUTCOME_ZULU_9917_V2'\n",
        encoding="utf-8",
    )
    moved = live_symbol_span(tmp_path, "pkg/beacon.py", "outcome_beacon_zulu", near_line=1)
    assert moved is not None
    assert moved[0] == 3
    assert "OUTCOME_ZULU_9917_V2" in moved[2]
    assert "9917'\n" not in moved[2] or "V2" in moved[2]


def test_refresh_node_replaces_stale_text(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "beacon.py").write_text(
        "def outcome_beacon_zulu():\n    return 'NOW'\n",
        encoding="utf-8",
    )
    stale = TraceNode(
        id="pkg/beacon.py::outcome_beacon_zulu",
        file="pkg/beacon.py",
        symbol="outcome_beacon_zulu",
        kind="function",
        start_line=10,
        end_line=12,
        text="def outcome_beacon_zulu():\n    return 'OLD'\n",
    )
    nodes = {stale.id: stale}
    fresh = refresh_node_from_disk(tmp_path, nodes, stale)
    assert fresh.start_line == 1
    assert "NOW" in fresh.text
    assert "OLD" not in fresh.text
    assert nodes[stale.id] is fresh


def test_expand_heatmap_id_reads_disk(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "beacon.py").write_text(
        "def outcome_beacon_zulu():\n    return 'NOW'\n",
        encoding="utf-8",
    )
    out = _expand_heatmap_ref(tmp_path, "pkg/beacon.py::outcome_beacon_zulu", 2000)
    assert out is not None
    assert out["ok"] is True
    assert out["start_line"] == 1
    assert "NOW" in out["text"]

    line = _expand_heatmap_ref(tmp_path, "pkg/beacon.py:1-2", 2000)
    assert line is not None
    assert "outcome_beacon_zulu" in line["text"]


def test_cold_collect_reads_symbol_not_file_header(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "beacon.py").write_text(
        '"""MODULE_HEADER_SHOULD_NOT_BE_THE_BODY"""\n'
        + ("x = 1\n" * 40)
        + "def outcome_beacon_zulu():\n    return 'BODY_ZULU'\n"
        + "def other_symbol():\n    return 'OTHER'\n",
        encoding="utf-8",
    )
    out = _collect_hot_from_card_locs(
        tmp_path,
        [],
        threshold=0.0,
        max_chars=4000,
        skip_ids=set(),
        only_ids={"pkg/beacon.py::outcome_beacon_zulu", "pkg/beacon.py::other_symbol"},
        prefer_ids={"pkg/beacon.py::outcome_beacon_zulu", "pkg/beacon.py::other_symbol"},
    )
    bodies = out["bodies"]
    assert len(bodies) == 2
    by_sym = {b["symbol"]: b for b in bodies}
    assert "MODULE_HEADER_SHOULD_NOT_BE_THE_BODY" not in by_sym["outcome_beacon_zulu"]["text"]
    assert by_sym["outcome_beacon_zulu"]["text"].lstrip().startswith("def outcome_beacon_zulu")
    assert "BODY_ZULU" in by_sym["outcome_beacon_zulu"]["text"]
    assert by_sym["other_symbol"]["text"].lstrip().startswith("def other_symbol")
    assert ":" in str(by_sym["outcome_beacon_zulu"]["loc"]).split("beacon.py", 1)[-1]


def test_injected_seed_loc_follows_disk(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "beacon.py").write_text(
        '"""header"""\n' + ("x = 1\n" * 20) + "def outcome_beacon_zulu():\n    return 'BODY'\n",
        encoding="utf-8",
    )
    stale = TraceNode(
        id="pkg/beacon.py::outcome_beacon_zulu",
        file="pkg/beacon.py",
        symbol="outcome_beacon_zulu",
        kind="function",
        start_line=1,
        end_line=2,
        text="def outcome_beacon_zulu():\n    return 'OLD'\n",
    )
    cards, _cov, injected = ensure_seeds_on_heatmap(
        [],
        [{"id": stale.id, "file": stale.file, "symbol": stale.symbol}],
        {stale.id: stale},
        root=tmp_path,
    )
    assert injected == [stale.id]
    assert cards[0]["loc"] == "pkg/beacon.py:22-23"
    assert cards[0]["start_line"] == 22


def test_cold_pack_seed_loc_comes_from_disk(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "beacon.py").write_text(
        '"""header"""\n' + ("x = 1\n" * 20) + "def outcome_beacon_zulu():\n    return 'BODY'\n",
        encoding="utf-8",
    )
    heat, seed, _tag = _lean_pack_fallback_heatmap(
        query="outcome beacon zulu pack seed",
        seed_file="pkg/beacon.py",
        seed_symbol="outcome_beacon_zulu",
        k=8,
        repo=tmp_path,
        session_id="cold-span",
        search_fn=lambda *_a, **_k: [],
    )
    assert seed is not None
    assert heat[0]["loc"] == "pkg/beacon.py:22-23"
    assert heat[0]["start_line"] == 22
    assert heat[0]["end_line"] == 23


def test_expand_disk_delta_reads_callees_missing_from_graph(tmp_path: Path) -> None:
    from pipeline.context_trace import _expand_disk_delta

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text(
        "def prewarm_pack_graph():\n"
        "    from trace_lab.composite_v1 import ensure_composite_edges\n"
        "    hydrate_ast_bundle()\n"
        "    ensure_composite_edges()\n",
        encoding="utf-8",
    )
    lib = tmp_path / "packages" / "trace_lab"
    lib.mkdir(parents=True)
    (lib / "composite_v1.py").write_text(
        "def ensure_composite_edges():\n    return None\n",
        encoding="utf-8",
    )
    hydrate = TraceNode(
        id="pkg/mod.py::hydrate_ast_bundle",
        file="pkg/mod.py",
        symbol="hydrate_ast_bundle",
        kind="function",
        start_line=10,
        end_line=20,
        text="pass",
    )
    nodes = {hydrate.id: hydrate}
    out = _expand_disk_delta(
        tmp_path,
        nodes,
        "pkg/mod.py::prewarm_pack_graph",
        direction="callees",
        k=8,
    )
    assert out is not None
    assert out["ok"] is True
    assert out["source"] == "disk"
    symbols = [c["symbol"] for c in out["delta"]]
    assert "hydrate_ast_bundle" in symbols
    assert "ensure_composite_edges" in symbols
    imported = next(c for c in out["delta"] if c["symbol"] == "ensure_composite_edges")
    assert imported["file"] == "packages/trace_lab/composite_v1.py"
    callers = _expand_disk_delta(
        tmp_path,
        nodes,
        "pkg/mod.py::prewarm_pack_graph",
        direction="callers",
        k=8,
    )
    assert callers is not None
    assert callers["ok"] is True
    assert callers["delta"] == []
