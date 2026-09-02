"""Tests for optional MCP response trimming (reliability-first, opt-in only)."""

from __future__ import annotations

import pytest

from pipeline.mcp_response_lean import apply_lean_fields, attach_gate_lean, lean_echo_enabled


def test_lean_echo_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CTX_MCP_LEAN_ECHO", raising=False)
    monkeypatch.setenv("CTX_TOKEN_MODE", "savings")
    assert lean_echo_enabled() is False


def test_lean_echo_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_MCP_LEAN_ECHO", "1")
    assert lean_echo_enabled() is True


def test_apply_lean_fields_no_op_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CTX_MCP_LEAN_ECHO", raising=False)
    raw = {
        "ok": True,
        "unchanged": False,
        "truncated": False,
        "budget": "wide",
        "code": "x = 1",
    }
    out = apply_lean_fields(raw)
    assert out == raw


def test_apply_lean_fields_opt_in_drops_budget_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_MCP_LEAN_ECHO", "1")
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


def test_session_hint_on_every_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_MCP_LEAN_ECHO", "1")
    ctx = {
        "session_id": "cursor@conn-abc123",
        "source": "transport_conn",
        "shared_process_risk": True,
        "hint": "Session may be shared across parallel chats.",
    }

    first = attach_gate_lean({"ok": True, "tool": "map"}, gate_line=lambda **_: "1:ce_x", session_context=lambda: ctx)
    second = attach_gate_lean({"ok": True, "tool": "map"}, gate_line=lambda **_: "1:ce_x", session_context=lambda: ctx)

    assert first["session_hint"] == ctx["hint"]
    assert second["session_hint"] == ctx["hint"]
    assert first["session_source"] == "transport_conn"
    assert second["session_source"] == "transport_conn"


def test_attach_gate_integration_unchanged_semantics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_MCP_SESSION_ISOLATE", "1")
    monkeypatch.setenv("CTX_MCP_CLIENT", "copilot")
    monkeypatch.delenv("CTX_MCP_LEAN_ECHO", raising=False)
    from pipeline.mcp_locate import _attach_gate
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
    assert out["budget"] == "cap"
