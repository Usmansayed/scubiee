"""CLI locate JSON is slim by default (pack text / chain / cold — not chrome)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from pipeline.locate_cli import emit_cli_json, slim_cli_payload  # noqa: E402


def test_slim_pack_keeps_bodies_drops_heatmap_chrome() -> None:
    fat = {
        "ok": True,
        "tool": "pack_context",
        "cli": "pack",
        "guide": "LEAN PACK — ignore me",
        "howto": "long howto",
        "ladder": "map → pack",
        "query_tip": "tip",
        "next_cli": "expand…",
        "next_actions": ["a"],
        "heatmap": [{"id": "a.py::f", "why": "CALLS:…", "score": 1.0}],
        "engine": "composite_v1",
        "n_nodes": 999,
        "budget_chars": 6000,
        "seed": {"id": "a.py::f", "file": "a.py", "symbol": "f", "extra": 1},
        "chain": [
            {
                "id": "a.py::f",
                "loc": "a.py:1-10",
                "edge": "seed",
                "why": "seed/flow",
                "score": 1.0,
            }
        ],
        "pack": [
            {
                "id": "a.py::f",
                "loc": "a.py:1-10",
                "text": "def f():\n    return 1\n",
                "why": "seed",
                "score": 1.0,
                "file": "a.py",
            }
        ],
        "cold": [
            {
                "id": "a.py::g",
                "loc": "a.py:12-20",
                "why": "CALLS:…",
                "rank": 2,
                "file": "a.py",
            }
        ],
    }
    slim = slim_cli_payload(fat)
    assert slim["ok"] is True
    assert slim["tool"] == "pack"
    assert set(slim.keys()) == {"ok", "tool", "seed", "chain", "pack", "cold"}
    assert slim["pack"] == [{"id": "a.py::f", "loc": "a.py:1-10", "text": "def f():\n    return 1\n"}]
    assert slim["cold"] == [{"id": "a.py::g", "loc": "a.py:12-20"}]
    assert "heatmap" not in slim
    assert "guide" not in slim


def test_slim_map_keeps_cards_and_seed() -> None:
    fat = {
        "ok": True,
        "tool": "map",
        "query": "q",
        "ladder": "…",
        "query_tip": "…",
        "latency_ms": 12,
        "cards": [
            {
                "rank": 1,
                "file": "packages/x.py",
                "score": 9.0,
                "why": "def foo",
                "role": "function",
                "chunk_id": 1,
                "loc": "packages/x.py:1-1",
                "symbol": "",
            }
        ],
        "suggested_seed": {
            "file": "packages/x.py",
            "symbol": "",
            "loc": "packages/x.py:1-1",
            "score": 9.0,
            "kind": "function",
        },
        "next": "scubiee pack …",
    }
    slim = slim_cli_payload(fat)
    assert slim["tool"] == "map"
    assert "chunk_id" not in slim["cards"][0]
    assert "ladder" not in slim
    assert slim["suggested_seed"]["file"] == "packages/x.py"
    assert slim["next"].startswith("scubiee pack")


def test_slim_expand_delta_and_bodies() -> None:
    fat = {
        "ok": True,
        "tool": "expand_context",
        "cli": "expand",
        "guide": "x",
        "howto": "y",
        "from": "a.py::f",
        "direction": "callees",
        "delta": [
            {
                "id": "a.py::g",
                "loc": "a.py:12-20",
                "why": "calls",
                "path": ["a.py::f", "a.py::g"],
            }
        ],
        "pack": [{"id": "a.py::g", "loc": "a.py:12-20", "text": "def g():\n    pass\n", "why": "x"}],
    }
    slim = slim_cli_payload(fat)
    assert set(slim.keys()) == {"ok", "tool", "from", "direction", "delta", "pack"}
    assert slim["delta"] == [{"id": "a.py::g", "loc": "a.py:12-20"}]
    assert slim["pack"][0] == {"id": "a.py::g", "loc": "a.py:12-20", "text": "def g():\n    pass\n"}


def test_emit_cli_json_default_is_compact_slim(capsys: pytest.CaptureFixture[str]) -> None:
    emit_cli_json(
        {
            "ok": True,
            "cli": "pack",
            "guide": "drop",
            "seed": {"id": "a.py::f", "file": "a.py", "symbol": "f"},
            "chain": [],
            "pack": [{"id": "a.py::f", "loc": "a.py:1-2", "text": "def f():\n    pass\n"}],
            "cold": [],
        }
    )
    out = capsys.readouterr().out.strip()
    assert "\n" not in out  # compact
    data = json.loads(out)
    assert "guide" not in data
    assert data["pack"][0]["text"].startswith("def f")


def test_emit_cli_json_full_keeps_chrome(capsys: pytest.CaptureFixture[str]) -> None:
    emit_cli_json(
        {"ok": True, "cli": "pack", "guide": "keep", "pack": [], "chain": [], "cold": [], "seed": {}},
        full=True,
    )
    data = json.loads(capsys.readouterr().out)
    assert data["guide"] == "keep"
