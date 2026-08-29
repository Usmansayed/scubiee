"""Single shipped MCP: session-native locate toolkit."""

from __future__ import annotations

import pytest

PHASE_EXPECTED = {
    "gate",
    "map",
    "focus",
    "grep",
    "glob",
    "workspace",
    "expand",
    "status",
}
READ_EXPECTED = {"search", "read", "status"}


def _tool_names(mcp) -> set[str]:
    mgr = getattr(mcp, "_tool_manager", None)
    if mgr is not None:
        tools = getattr(mgr, "_tools", None) or getattr(mgr, "tools", None)
        if isinstance(tools, dict):
            return set(tools.keys())
    tools_attr = getattr(mcp, "_tools", None)
    if isinstance(tools_attr, dict):
        return set(tools_attr.keys())
    raise AssertionError("cannot introspect FastMCP tools")


def test_only_locate_mcp_is_shipped(monkeypatch, tmp_path):
    pytest.importorskip("mcp")
    monkeypatch.delenv("CTX_MCP_SURFACE", raising=False)
    monkeypatch.setattr("pipeline.mcp_locate._is_repo_managed", lambda: True)
    from pipeline.mcp_locate import create_mcp as create_locate
    from pipeline.mcp_server import create_mcp as create_compat

    locate = create_locate(name="test-locate")
    compat = create_compat()
    assert _tool_names(locate) == PHASE_EXPECTED
    assert _tool_names(compat) == PHASE_EXPECTED


def test_read_surface_still_available(monkeypatch):
    pytest.importorskip("mcp")
    monkeypatch.setenv("CTX_MCP_SURFACE", "read")
    monkeypatch.setattr("pipeline.mcp_locate._is_repo_managed", lambda: True)
    from pipeline.mcp_locate import create_mcp as create_locate

    locate = create_locate(name="test-locate-read")
    assert _tool_names(locate) == READ_EXPECTED | {"gate"}


def test_ensure_daemon_soft_skips_force_restart(monkeypatch):
    from pipeline import daemon as d

    monkeypatch.setattr(d, "is_running", lambda: False)
    monkeypatch.setattr(d, "_read_lock_pid", lambda: 424242)
    monkeypatch.setattr(d, "_pid_alive", lambda _pid: True)

    def _boom(*_a, **_k):
        raise AssertionError("force_restart should not run when force_if_hung=False")

    monkeypatch.setattr(d, "force_restart_daemon", _boom)
    out = d.ensure_daemon(force_if_hung=False)
    assert out.get("hung") is True
