"""Lean pack must keep seeds hot/front — map-reuse must not demote score=1.0 seeds."""
from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.mcp_locate import _lean_pack_fallback_heatmap, _lean_pack_seed_card
from pipeline.mcp_response_lean import _pack_heatmap_only, apply_lean_fields


def test_pack_heatmap_promotes_seed_over_high_score_neighbors() -> None:
    lean = _pack_heatmap_only(
        {
            "ok": True,
            "tool": "pack_context",
            "seed": {
                "id": "packages/pipeline/live_reflect_beacon.py::scubiee_live_reflect_beacon_zulu9917",
                "file": "packages/pipeline/live_reflect_beacon.py",
                "symbol": "scubiee_live_reflect_beacon_zulu9917",
            },
            "heatmap": [
                {
                    "id": "packages/pipeline/sync_loop.py:581-621",
                    "loc": "packages/pipeline/sync_loop.py:581-621",
                    "score": 40.0,
                },
                {
                    "id": "packages/pipeline/live_reflect_beacon.py::scubiee_live_reflect_beacon_zulu9917",
                    "loc": "packages/pipeline/live_reflect_beacon.py:6-10",
                    "symbol": "scubiee_live_reflect_beacon_zulu9917",
                    "score": 1.0,
                },
            ],
            "include_bodies": False,
        },
        tool_name="pack_context",
    )
    assert lean["heatmap"][0]["id"].endswith("scubiee_live_reflect_beacon_zulu9917")
    assert lean["heatmap"][0]["heat"] == "hot"
    assert lean["heatmap"][0]["r"] == 1


def test_pack_heatmap_keeps_seed2_hot() -> None:
    lean = _pack_heatmap_only(
        {
            "seed": {"id": "a.py::f", "file": "a.py", "symbol": "f"},
            "seed2": {"id": "b.py::g", "file": "b.py", "symbol": "g"},
            "heatmap": [
                {"id": "c.py:1-2", "loc": "c.py:1-2", "score": 99.0},
                {"id": "a.py::f", "loc": "a.py:1-2", "symbol": "f", "score": 1.0},
                {"id": "b.py::g", "loc": "b.py:3-4", "symbol": "g", "score": 1.0},
            ],
        },
        tool_name="pack_context",
    )
    tops = [h["id"] for h in lean["heatmap"][:2]]
    assert tops == ["a.py::f", "b.py::g"]
    assert all(h["heat"] == "hot" for h in lean["heatmap"][:2])


def test_apply_lean_fields_preserves_seed_first_rank(monkeypatch) -> None:
    monkeypatch.delenv("CTX_MCP_ECHO_GUIDANCE", raising=False)
    monkeypatch.delenv("CTX_MCP_FULL_LOCATE", raising=False)
    monkeypatch.delenv("CTX_MCP_PACK_BODIES", raising=False)
    out = apply_lean_fields(
        {
            "ok": True,
            "tool": "pack_context",
            "include_bodies": False,
            "seed": {"id": "beacon.py::zulu", "file": "beacon.py", "symbol": "zulu"},
            "heatmap": [
                {"id": "noise.py:1-2", "loc": "noise.py:1-2", "score": 38.0},
                {
                    "id": "beacon.py::zulu",
                    "loc": "beacon.py:1-3",
                    "symbol": "zulu",
                    "score": 1.0,
                },
            ],
            "g": "1:ce_x",
            "session_id": "t",
        }
    )
    assert out["heatmap"][0]["id"] == "beacon.py::zulu"
    assert out["heatmap"][0]["heat"] == "hot"


def test_lean_pack_seed_card_boost() -> None:
    card = _lean_pack_seed_card(
        file="packages/pipeline/live_reflect_beacon.py",
        symbol="scubiee_live_reflect_beacon_zulu9917",
        line=6,
        score=110.0,
    )
    assert card is not None
    assert card["score"] == 110.0
    assert card["heat"] == "hot"
    assert "zulu9917" in card["id"]


def test_second_lean_pass_keeps_rank_scores() -> None:
    """MCP formats a pack twice. The second pass must keep sc and rank order."""
    raw = {
        "ok": True,
        "tool": "pack_context",
        "include_bodies": False,
        "hot_threshold": 0.65,
        "seed": {
            "id": "a.py::run_pack_context",
            "file": "a.py",
            "symbol": "run_pack_context",
        },
        "heatmap": [
            {
                "id": "a.py::run_pack_context",
                "symbol": "run_pack_context",
                "score": 1.05,
                "loc": "a.py:1-20",
            },
            {
                "id": "a.py::run_map_context",
                "symbol": "run_map_context",
                "score": 0.9902,
                "loc": "a.py:30-80",
            },
            {
                "id": "a.py::build_call_chain",
                "symbol": "build_call_chain",
                "score": 0.45,
                "loc": "a.py:90-100",
            },
        ],
        "cold": [
            {
                "id": "a.py::run_map_context",
                "symbol": "run_map_context",
                "score": 0,
                "loc": "a.py:30-80",
            }
        ],
    }
    once = apply_lean_fields(raw)
    twice = apply_lean_fields(once)
    symbols = [row["s"] for row in twice["heatmap"]]
    assert symbols[:2] == ["run_pack_context", "run_map_context"]
    assert twice["heatmap"][1]["sc"] == 0.9902
    assert twice["heatmap"][1]["heat"] == "hot"
    assert twice["heatmap"][2]["sc"] == 0.45
    assert twice["heatmap"][2]["heat"] != "hot"


def test_missing_seed_is_not_a_map_replay(
    monkeypatch, tmp_path: Path
) -> None:
    """A missing seed stays an error. Last-map cards are not a successful pack."""
    pytest.importorskip("mcp")
    import json

    from pipeline.mcp_ship_check import parse_tool_json, tool_fn
    from pipeline.project_id import save_registry

    repo = tmp_path / "packfb"
    repo.mkdir()
    (repo / ".git").mkdir()
    ce = repo / ".scubiee"
    ce.mkdir()
    pid = "ce_preprod_fallback1234567890ab"
    (ce / "id.json").write_text(json.dumps({"project_id": pid}), encoding="utf-8")
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    save_registry(
        {
            "projects": {
                pid: {
                    "managed": True,
                    "root": str(repo.resolve()),
                    "paths": [str(repo.resolve())],
                }
            }
        }
    )
    monkeypatch.setenv("CTX_REPO", str(repo.resolve()))
    monkeypatch.chdir(repo)
    monkeypatch.setattr("pipeline.mcp_locate._is_repo_managed", lambda: True)
    monkeypatch.setattr("pipeline.context_trace.ast_cache_ready", lambda *_a, **_k: True)
    monkeypatch.setattr("pipeline.context_trace.load_trace", lambda *a, **k: {})
    monkeypatch.setattr("pipeline.context_trace.persist_trace", lambda *a, **k: None)

    def _missing_seed(*_a, **_k):
        return {
            "ok": False,
            "error": "seed not found: file='new.py' symbol='fresh' line=0",
            "hint": "Pass seed_file + seed_symbol",
            "tool": "pack_context",
        }

    monkeypatch.setattr("pipeline.context_trace.run_pack_context", _missing_seed)
    monkeypatch.setattr(
        "pipeline.map_result_cache.get_recent_map_cards",
        lambda **_k: [
            {
                "file": "other.py",
                "symbol": "noise",
                "start_line": 1,
                "end_line": 2,
                "score": 20.0,
                "loc": "other.py:1-2",
            }
        ],
    )

    from pipeline.mcp_locate import create_mcp

    mcp = create_mcp(name="preprod-pack-fb")
    out = parse_tool_json(
        tool_fn(mcp, "pack_context")(
            query="fresh new.py seed",
            seed_file="new.py",
            seed_symbol="fresh",
            mode="lean",
            policy="strict",
            root=str(repo),
        )
    )
    assert out.get("ok") is False
    assert "seed not found" in str(out.get("error") or "").lower()
    assert "noise" not in str(out)


def test_lean_pack_fallback_boosts_seed_above_map_cards(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "pipeline.map_result_cache.get_recent_map_cards",
        lambda **_k: [
            {
                "file": "packages/pipeline/sync_loop.py",
                "symbol": "keeper_tick",
                "start_line": 649,
                "end_line": 757,
                "score": 38.3,
                "loc": "packages/pipeline/sync_loop.py:649-757",
                "why": "map",
            },
            {
                "file": "packages/pipeline/live_reflect_beacon.py",
                "symbol": "scubiee_live_reflect_beacon_zulu9917",
                "start_line": 6,
                "end_line": 10,
                "score": 34.0,
                "loc": "packages/pipeline/live_reflect_beacon.py:6-10",
                "why": "map",
            },
        ],
    )
    heat, seed, tag = _lean_pack_fallback_heatmap(
        query="beacon zulu",
        seed_file="packages/pipeline/live_reflect_beacon.py",
        seed_symbol="scubiee_live_reflect_beacon_zulu9917",
        seed2_file="packages/pipeline/live_reflect_beacon.py",
        seed2_symbol="scubiee_live_reflect_helper_yankee4482",
        k=16,
        repo=tmp_path,
        session_id="unit",
        search_fn=lambda *_a, **_k: [],
    )
    assert tag == "map_reuse"
    assert seed is not None
    assert heat[0]["symbol"] == "scubiee_live_reflect_beacon_zulu9917"
    assert heat[0]["score"] >= 48.0  # max_map(38.3) + 10
    assert heat[0]["loc"] == "packages/pipeline/live_reflect_beacon.py:6-10"
    symbols = [h.get("symbol") for h in heat]
    assert "scubiee_live_reflect_helper_yankee4482" in symbols
    assert "keeper_tick" in symbols

    slim = _pack_heatmap_only(
        {
            "seed": seed,
            "seed2": next(
                h
                for h in heat
                if h.get("symbol") == "scubiee_live_reflect_helper_yankee4482"
            ),
            "heatmap": heat,
            "include_bodies": False,
        },
        tool_name="pack_context",
    )
    assert slim["heatmap"][0]["s"] == "scubiee_live_reflect_beacon_zulu9917"
    assert slim["heatmap"][0]["heat"] == "hot"
