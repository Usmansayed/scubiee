"""Tests for MCP response trimming (compact JSON + drop chrome)."""

from __future__ import annotations

import json

import pytest

from pipeline.mcp_response_lean import (
    apply_lean_fields,
    attach_gate_lean,
    echo_guidance_enabled,
    echo_session_enabled,
    lean_echo_enabled,
    reset_session_hint_echo_cache,
)


def test_lean_echo_on_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CTX_MCP_ECHO_BUDGET", raising=False)
    monkeypatch.delenv("CTX_MCP_LEAN_ECHO", raising=False)
    assert lean_echo_enabled() is True


def test_echo_budget_opt_in_keeps_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_MCP_ECHO_BUDGET", "1")
    assert lean_echo_enabled() is False
    raw = {"ok": True, "budget": "wide", "code": "x = 1", "unchanged": False}
    out = apply_lean_fields(raw)
    assert out["budget"] == "wide"
    assert out["code"] == "x = 1"


def test_apply_lean_fields_drops_budget_and_guidance_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CTX_MCP_ECHO_BUDGET", raising=False)
    monkeypatch.delenv("CTX_MCP_ECHO_GUIDANCE", raising=False)
    monkeypatch.delenv("CTX_MCP_ECHO_SESSION", raising=False)
    raw = {
        "ok": True,
        "unchanged": False,
        "truncated": False,
        "has_more": False,
        "budget": "wide",
        "code": "x = 1",
        "next": "Edit cited lines.",
        "usage_hint": "do this then that",
        "locate_action": "edit_or_continue",
        "chars_returned": 99,
        "lines_returned": "1-10 of 10",
        "session_source": "explicit",
        "session_shared_risk": True,
        "session_hint": "long prose",
    }
    out = apply_lean_fields(raw)
    assert "budget" not in out
    assert "next" not in out
    assert "usage_hint" not in out
    assert "locate_action" not in out
    assert "chars_returned" not in out
    assert "lines_returned" not in out
    assert "session_source" not in out
    assert "session_shared_risk" not in out
    assert "session_hint" not in out
    assert out["unchanged"] is False
    assert out["truncated"] is False
    assert out["code"] == "x = 1"


def test_echo_guidance_keeps_next(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_MCP_ECHO_GUIDANCE", "1")
    assert echo_guidance_enabled() is True
    out = apply_lean_fields({"ok": True, "code": "x", "next": "edit"})
    assert out["next"] == "edit"


def test_session_chrome_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_session_hint_echo_cache()
    monkeypatch.delenv("CTX_MCP_ECHO_SESSION", raising=False)
    assert echo_session_enabled() is False
    ctx = {
        "session_id": "host@conn-abc123",
        "source": "transport_conn",
        "shared_process_risk": True,
        "hint": "Session may be shared across parallel chats.",
    }
    out = attach_gate_lean(
        {"ok": True, "tool": "map"},
        gate_line=lambda **_: "1:ce_x",
        session_context=lambda: ctx,
    )
    assert out["session_id"] == ctx["session_id"]
    assert "session_hint" not in out
    assert "session_shared_risk" not in out
    assert "session_source" not in out
    assert out["g"] == "1:ce_x"


def test_session_chrome_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_session_hint_echo_cache()
    monkeypatch.setenv("CTX_MCP_ECHO_SESSION", "1")
    ctx = {
        "session_id": "host@conn-abc123",
        "source": "transport_conn",
        "shared_process_risk": True,
        "hint": "Session may be shared across parallel chats.",
    }
    first = attach_gate_lean(
        {"ok": True, "tool": "map"},
        gate_line=lambda **_: "1:ce_x",
        session_context=lambda: ctx,
    )
    second = attach_gate_lean(
        {"ok": True, "tool": "map"},
        gate_line=lambda **_: "1:ce_x",
        session_context=lambda: ctx,
    )
    assert first["session_hint"] == ctx["hint"]
    assert "session_hint" not in second
    assert first["session_shared_risk"] is True
    assert first["session_source"] == "transport_conn"


def test_session_hint_re_echoes_on_new_session_id(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_session_hint_echo_cache()
    monkeypatch.setenv("CTX_MCP_ECHO_SESSION", "1")
    ctx_a = {
        "session_id": "claude@chat-1",
        "source": "host_env",
        "shared_process_risk": False,
        "hint": "Pass session_id on later calls.",
    }
    ctx_b = {
        "session_id": "claude@chat-2",
        "source": "host_env",
        "shared_process_risk": False,
        "hint": "Pass session_id on later calls.",
    }
    a = attach_gate_lean(
        {"ok": True}, gate_line=lambda **_: "1:ce_x", session_context=lambda: ctx_a
    )
    b = attach_gate_lean(
        {"ok": True}, gate_line=lambda **_: "1:ce_x", session_context=lambda: ctx_b
    )
    assert a["session_hint"]
    assert b["session_hint"]
    assert a["session_id"] != b["session_id"]


def test_attach_gate_integration_unchanged_semantics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_MCP_SESSION_ISOLATE", "1")
    monkeypatch.setenv("CTX_MCP_CLIENT", "copilot")
    monkeypatch.delenv("CTX_MCP_ECHO_BUDGET", raising=False)
    monkeypatch.delenv("CTX_MCP_ECHO_SESSION", raising=False)
    monkeypatch.delenv("CTX_MCP_ECHO_GUIDANCE", raising=False)
    from pipeline.mcp_locate import _attach_gate, _dumps
    from pipeline.session_isolation import (
        bind_resolved_session,
        reset_resolved_session,
        resolve_session,
    )

    info = resolve_session("parallel-task-a")
    tok = bind_resolved_session(info)
    try:
        out = _attach_gate(
            {
                "ok": True,
                "tool": "map",
                "unchanged": False,
                "budget": "cap",
                "next": "x",
            }
        )
    finally:
        reset_resolved_session(tok)
    assert out["session_id"] == "parallel-task-a"
    assert "session_source" not in out
    assert out["unchanged"] is False
    assert "budget" not in out
    # Ladder ``next`` is preserved on map (MCP steer); not stripped as chrome.
    assert out.get("next") == "x"
    dumped = _dumps(out)
    assert "\n" not in dumped
    assert json.loads(dumped)["unchanged"] is False


def test_dumps_strips_budget_even_if_card_still_has_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CTX_MCP_ECHO_BUDGET", raising=False)
    from pipeline.mcp_locate import _dumps

    dumped = _dumps(
        {
            "ok": True,
            "tool": "focus",
            "code": "x = 1",
            "budget": "cap",
            "truncated": False,
        }
    )
    parsed = json.loads(dumped)
    assert "budget" not in parsed
    assert parsed["code"] == "x = 1"
    assert parsed["truncated"] is False


def test_dumps_keeps_budget_when_echo_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CTX_MCP_ECHO_BUDGET", "1")
    from pipeline.mcp_locate import _dumps

    parsed = json.loads(_dumps({"ok": True, "budget": "wide", "code": "x"}))
    assert parsed["budget"] == "wide"
    assert parsed["code"] == "x"


def test_apply_lean_strips_card_coaching(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CTX_MCP_ECHO_GUIDANCE", raising=False)
    raw = {
        "ok": True,
        "tool": "focus",
        "cards": [
            {
                "file": "a.py",
                "start_line": 1,
                "end_line": 2,
                "needs_outline": True,
                "span_hint": "use focus",
                "follow_up": "grep x",
            }
        ],
    }
    out = apply_lean_fields(raw)
    assert "needs_outline" not in out["cards"][0]
    assert "span_hint" not in out["cards"][0]
    assert "follow_up" not in out["cards"][0]


def test_pack_context_slim_heatmap_only_no_bodies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CTX_MCP_ECHO_GUIDANCE", raising=False)
    monkeypatch.delenv("CTX_MCP_FULL_LOCATE", raising=False)
    monkeypatch.delenv("CTX_MCP_PACK_BODIES", raising=False)
    raw = {
        "ok": True,
        "tool": "pack_context",
        "guide": "LEAN PACK — ignore",
        "howto": "howto",
        "ladder": "map → pack",
        "next_actions": [{"tool": "expand_context"}],
        "heatmap": [
            {
                "id": "a.py::f",
                "symbol": "f",
                "why": "CALLS:long",
                "score": 1.0,
                "loc": "a.py:1-2",
            },
            {
                "id": "a.py::g",
                "symbol": "g",
                "score": 0.8,
                "loc": "a.py:3-4",
            },
        ],
        "engine": "composite_v1",
        "n_nodes": 100,
        "budget_chars": 6000,
        "query": "q",
        "mode": "lean",
        "policy": "strict",
        "include_bodies": False,
        "seed": {"id": "a.py::f", "file": "a.py", "symbol": "f"},
        "chain": [
            {"id": "a.py::f", "loc": "a.py:1-2", "edge": "seed", "why": "seed", "score": 1.0}
        ],
        "pack": [],
        "cold": [
            {
                "id": "a.py::g",
                "loc": "a.py:3-4",
                "score": 0.8,
                "why": "CALLS:…",
                "file": "a.py",
                "symbol": "g",
            }
        ],
        "session_id": "cursor@conn-1",
        "g": "1:ce_x",
    }
    out = apply_lean_fields(raw)
    assert out["tool"] == "pack_context"
    assert "pack" not in out
    assert "cold" not in out
    assert "chain" not in out
    assert "guide" not in out
    assert "next_actions" not in out
    assert "engine" not in out
    assert out["read"]["top"] == 5
    assert out["heatmap"][0]["heat"] == "hot"
    assert out["heatmap"][0]["loc"] == "a.py:1-2"
    assert out["heatmap"][0]["s"] == "f"
    g = next(h for h in out["heatmap"] if h.get("id") == "a.py::g")
    # 0.8 is above the hot threshold. "cold" in the raw payload only meant
    # this row did not receive a body.
    assert g["heat"] == "hot"
    assert g["sc"] == 0.8
    assert not any("def f" in str(v) for v in out.get("heatmap", []))
    assert out["g"] == "1:ce_x"
    assert out["session_id"] == "cursor@conn-1"
    assert "next" in out
    assert "Native-Read" in out["next"]
    assert "BAN whole-file" in out["next"]


def test_mcp_map_keeps_ladder_next(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CTX_MCP_ECHO_GUIDANCE", raising=False)
    monkeypatch.delenv("CTX_MCP_FULL_LOCATE", raising=False)
    raw = {
        "ok": True,
        "tool": "map",
        "cards": [
            {
                "rank": 1,
                "file": "packages/pipeline/foo.py",
                "symbol": "bar",
                "score": 1.0,
                "start_line": 10,
                "end_line": 20,
            }
        ],
        "suggested_seed": {
            "file": "packages/pipeline/foo.py",
            "symbol": "bar",
            "start_line": 10,
            "end_line": 20,
        },
        "next": "Refine query with suggested_seed file+symbol, then pack_context(mode=lean).",
    }
    out = apply_lean_fields(raw)
    assert out["tool"] == "map"
    assert "pack_context" in out["next"]
    assert out["cards"][0]["loc"] == "packages/pipeline/foo.py:10-20"
    assert out["suggested_seed"]["loc"] == "packages/pipeline/foo.py:10-20"


def test_map_lean_keeps_suggested_seeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CTX_MCP_ECHO_GUIDANCE", raising=False)
    monkeypatch.delenv("CTX_MCP_FULL_LOCATE", raising=False)
    raw = {
        "ok": True,
        "tool": "map",
        "cards": [
            {
                "rank": 1,
                "file": "packages/pipeline/a.py",
                "symbol": "A",
                "score": 2.0,
                "loc": "packages/pipeline/a.py:1-2",
            }
        ],
        "suggested_seed": {
            "file": "packages/pipeline/a.py",
            "symbol": "A",
            "loc": "packages/pipeline/a.py:1-2",
        },
        "suggested_seeds": [
            {"file": "packages/pipeline/a.py", "symbol": "A", "loc": "packages/pipeline/a.py:1-2"},
            {"file": "packages/pipeline/b.py", "symbol": "B", "loc": "packages/pipeline/b.py:3-4"},
        ],
        "next": "ENRICH pack query … seed2_file=packages/pipeline/b.py",
    }
    out = apply_lean_fields(raw)
    assert len(out.get("suggested_seeds") or []) == 2
    assert out["suggested_seeds"][1]["symbol"] == "B"


def test_map_lean_keeps_dense_d_channel_signals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CTX_MCP_ECHO_GUIDANCE", raising=False)
    monkeypatch.delenv("CTX_MCP_FULL_LOCATE", raising=False)
    raw = {
        "ok": True,
        "tool": "map",
        "dense": True,
        "retrieve_mode": "D_channel_best",
        "timings": {"dense": True, "retrieve_mode": "D_channel_best", "embed_ms": 12.0},
        "cards": [
            {
                "rank": 1,
                "file": "packages/pipeline/a.py",
                "symbol": "A",
                "score": 2.0,
                "source": "D_channel_best:bm25+dense",
                "loc": "packages/pipeline/a.py:1-2",
            }
        ],
        "suggested_seed": {
            "file": "packages/pipeline/a.py",
            "symbol": "A",
            "loc": "packages/pipeline/a.py:1-2",
        },
    }
    out = apply_lean_fields(raw)
    assert out.get("dense") is True
    assert out.get("retrieve_mode") == "D_channel_best"
    assert (out.get("timings") or {}).get("dense") is True
    assert out["cards"][0].get("source", "").startswith("D_channel_best")


def test_pack_lean_keeps_multi_seed_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CTX_MCP_ECHO_GUIDANCE", raising=False)
    monkeypatch.delenv("CTX_MCP_FULL_LOCATE", raising=False)
    monkeypatch.delenv("CTX_MCP_PACK_BODIES", raising=False)
    raw = {
        "ok": True,
        "tool": "pack_context",
        "include_bodies": False,
        "seed": {"id": "packages/a.py::A", "file": "packages/a.py", "symbol": "A"},
        "seed2": {"id": "packages/b.py::B", "file": "packages/b.py", "symbol": "B"},
        "seeds": [
            {"id": "packages/a.py::A", "file": "packages/a.py", "symbol": "A"},
            {"id": "packages/b.py::B", "file": "packages/b.py", "symbol": "B"},
        ],
        "multi_seed": {"engine": "multi_seed_v1", "extra": {"mode": "agreement_corridor"}},
        "heatmap": [
            {
                "id": "packages/a.py::A",
                "file": "packages/a.py",
                "symbol": "A",
                "score": 1.1,
                "loc": "packages/a.py:1-2",
            }
        ],
        "thin": False,
    }
    out = apply_lean_fields(raw)
    assert out["seed2"]["symbol"] == "B"
    assert out["multi_seed"]["engine"] == "multi_seed_v1"
    assert len(out.get("seeds") or []) == 2


def test_collect_hot_empty_bodies_keeps_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CTX_MCP_ECHO_GUIDANCE", raising=False)
    monkeypatch.delenv("CTX_MCP_FULL_LOCATE", raising=False)
    raw = {
        "ok": True,
        "tool": "collect_hot_context",
        "bodies": [],
        "count": 0,
        "empty_bodies": True,
        "hint": "No bodies collected — pass ids=",
        "next": "Native-Read heatmap loc spans",
    }
    out = apply_lean_fields(raw)
    assert out["empty_bodies"] is True
    assert out["pack"] == []
    assert "hint" in out
    assert "ids=" in out["hint"]
    assert "next" in out


def test_pack_heatmap_synthesizes_missing_loc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CTX_MCP_ECHO_GUIDANCE", raising=False)
    monkeypatch.delenv("CTX_MCP_FULL_LOCATE", raising=False)
    monkeypatch.delenv("CTX_MCP_PACK_BODIES", raising=False)
    raw = {
        "ok": True,
        "tool": "pack_context",
        "include_bodies": False,
        "seed": {"id": "a.py::f", "file": "a.py", "symbol": "f"},
        "chain": [
            {
                "id": "a.py::f",
                "file": "a.py",
                "symbol": "f",
                "start_line": 1,
                "end_line": 4,
                "edge": "seed",
                "score": 1.0,
            }
        ],
        "pack": [],
        "cold": [],
    }
    out = apply_lean_fields(raw)
    assert out["heatmap"][0]["loc"] == "a.py:1-4"
    assert "next" in out


def test_pack_context_bodies_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CTX_MCP_FULL_LOCATE", raising=False)
    monkeypatch.setenv("CTX_MCP_PACK_BODIES", "1")
    raw = {
        "ok": True,
        "tool": "pack_context",
        "include_bodies": True,
        "seed": {"id": "a.py::f", "file": "a.py", "symbol": "f"},
        "chain": [],
        "pack": [
            {
                "id": "a.py::f",
                "loc": "a.py:1-2",
                "text": "def f():\n    return 1\n",
            }
        ],
        "cold": [],
    }
    out = apply_lean_fields(raw)
    assert out["pack"] == [
        {"id": "a.py::f", "loc": "a.py:1-2", "text": "def f():\n    return 1\n"}
    ]


def test_pack_context_full_locate_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_MCP_FULL_LOCATE", "1")
    raw = {
        "ok": True,
        "tool": "pack_context",
        "guide": "keep",
        "heatmap": [{"id": "a.py::f"}],
        "pack": [],
        "chain": [],
        "cold": [],
        "seed": {},
    }
    out = apply_lean_fields(raw)
    assert out["guide"] == "keep"
    assert "heatmap" in out
