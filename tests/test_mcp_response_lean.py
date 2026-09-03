"""Tests for MCP response trimming (compact JSON + drop echoed budget)."""

from __future__ import annotations

import json

import pytest

from pipeline.mcp_response_lean import apply_lean_fields, attach_gate_lean, lean_echo_enabled


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


def test_apply_lean_fields_drops_budget_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CTX_MCP_ECHO_BUDGET", raising=False)
    raw = {
        "ok": True,
        "unchanged": False,
        "truncated": False,
        "has_more": False,
        "budget": "wide",
        "code": "x = 1",
    }
    out = apply_lean_fields(raw)
    assert "budget" not in out
    assert out["unchanged"] is False
    assert out["truncated"] is False
    assert out["has_more"] is False
    assert out["code"] == "x = 1"


def test_session_hint_once_flags_every_call(monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.mcp_response_lean import reset_session_hint_echo_cache

    monkeypatch.setenv("CTX_MCP_LEAN_ECHO", "1")
    reset_session_hint_echo_cache()
    ctx = {
        "session_id": "host@conn-abc123",
        "source": "transport_conn",
        "shared_process_risk": True,
        "hint": "Session may be shared across parallel chats.",
    }

    first = attach_gate_lean({"ok": True, "tool": "map"}, gate_line=lambda **_: "1:ce_x", session_context=lambda: ctx)
    second = attach_gate_lean({"ok": True, "tool": "map"}, gate_line=lambda **_: "1:ce_x", session_context=lambda: ctx)

    assert first["session_hint"] == ctx["hint"]
    assert "session_hint" not in second
    assert first["session_id"] == second["session_id"] == ctx["session_id"]
    assert first["session_shared_risk"] is True
    assert second["session_shared_risk"] is True
    assert first["session_source"] == "transport_conn"
    assert second["session_source"] == "transport_conn"


def test_session_hint_re_echoes_on_new_session_id(monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.mcp_response_lean import reset_session_hint_echo_cache

    reset_session_hint_echo_cache()
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
    a = attach_gate_lean({"ok": True}, gate_line=lambda **_: "1:ce_x", session_context=lambda: ctx_a)
    b = attach_gate_lean({"ok": True}, gate_line=lambda **_: "1:ce_x", session_context=lambda: ctx_b)
    assert a["session_hint"]
    assert b["session_hint"]
    assert a["session_id"] != b["session_id"]


def test_attach_gate_integration_unchanged_semantics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_MCP_SESSION_ISOLATE", "1")
    monkeypatch.setenv("CTX_MCP_CLIENT", "copilot")
    monkeypatch.delenv("CTX_MCP_ECHO_BUDGET", raising=False)
    from pipeline.mcp_locate import _attach_gate, _dumps
    from pipeline.session_isolation import bind_resolved_session, reset_resolved_session, resolve_session

    info = resolve_session("parallel-task-a")
    tok = bind_resolved_session(info)
    try:
        out = _attach_gate({"ok": True, "tool": "map", "unchanged": False, "budget": "cap"})
    finally:
        reset_resolved_session(tok)
    assert out["session_id"] == "parallel-task-a"
    assert out["session_source"] == "explicit"
    assert out["unchanged"] is False
    assert "budget" not in out
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
