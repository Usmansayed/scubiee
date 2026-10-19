"""Pre-rename ``context-engine`` MCP entries that launch Scubiee are cleaned up."""

from __future__ import annotations

import json
from pathlib import Path

OURS = {"command": "/Users/u/.local/bin/scubiee-mcp", "args": [], "disabled": True}
THEIRS = {"command": "npx", "args": ["-y", "@acme/context-engine-mcp"]}


def test_strip_legacy_keys_only_removes_scubiee_entries() -> None:
    from pipeline.branding import strip_legacy_mcp_keys

    servers = {"context-engine": dict(OURS), "figma": {"url": "x"}}
    assert strip_legacy_mcp_keys(servers) is True
    assert servers == {"figma": {"url": "x"}}

    servers = {"context-engine": dict(THEIRS)}
    assert strip_legacy_mcp_keys(servers) is False
    assert servers == {"context-engine": THEIRS}


def test_wipe_drops_legacy_scubiee_entry_and_keeps_others(tmp_path: Path) -> None:
    from pipeline.wipe import _drop_mcp_server, _mcp_has_context_engine

    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {"context-engine": OURS, "figma": {"url": "x"}}}))
    assert _mcp_has_context_engine(cfg) is True
    out = _drop_mcp_server(cfg)
    assert out["removed"] is True and "context-engine" in out["name"]
    assert json.loads(cfg.read_text()) == {"mcpServers": {"figma": {"url": "x"}}}
    assert _mcp_has_context_engine(cfg) is False


def test_wipe_keeps_third_party_context_engine(tmp_path: Path) -> None:
    from pipeline.wipe import _drop_mcp_server, _mcp_has_context_engine

    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {"context-engine": THEIRS}}))
    assert _mcp_has_context_engine(cfg) is False
    assert _drop_mcp_server(cfg)["removed"] is False
    assert json.loads(cfg.read_text()) == {"mcpServers": {"context-engine": THEIRS}}


def test_claude_json_legacy_entry_removed_keeps_other_keys(tmp_path: Path) -> None:
    from pipeline.wipe import _drop_mcp_server

    cfg = tmp_path / ".claude.json"
    cfg.write_text(json.dumps({"numStartups": 3, "mcpServers": {"context-engine": OURS}}))
    assert _drop_mcp_server(cfg)["removed"] is True
    assert json.loads(cfg.read_text()) == {"numStartups": 3}


def test_tool_disconnect_removes_legacy_entry_from_global_configs(tmp_path: Path) -> None:
    from pipeline.rules_installer import remove_mcp_config
    from pipeline.tool_registry import get_tool

    tool = get_tool("copilot")
    cfg = tmp_path / "mcp-config.json"
    cfg.write_text(json.dumps({"mcpServers": {"context-engine": OURS, "figma": {"url": "x"}}}))
    assert remove_mcp_config(tool, cfg, schema="claude", key="mcpServers") is True
    assert json.loads(cfg.read_text()) == {"mcpServers": {"figma": {"url": "x"}}}

    cfg.write_text(json.dumps({"mcpServers": {"context-engine": THEIRS}}))
    assert remove_mcp_config(tool, cfg, schema="claude", key="mcpServers") is False
    assert json.loads(cfg.read_text()) == {"mcpServers": {"context-engine": THEIRS}}


def test_tool_disconnect_also_cleans_the_other_server_key(tmp_path: Path) -> None:
    from pipeline.rules_installer import remove_mcp_config
    from pipeline.tool_registry import get_tool
    from pipeline.wipe import _mcp_has_context_engine

    cfg = tmp_path / "mcp.json"
    cfg.write_text(
        json.dumps({"servers": {}, "mcpServers": {"context-engine": OURS, "acme": THEIRS}})
    )
    assert _mcp_has_context_engine(cfg) is True
    assert remove_mcp_config(get_tool("copilot"), cfg, schema="vscode", key="servers") is True
    assert json.loads(cfg.read_text()) == {"servers": {}, "mcpServers": {"acme": THEIRS}}
    assert _mcp_has_context_engine(cfg) is False
