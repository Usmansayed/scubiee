"""Cross-host MCP permission presets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.branding import MCP_SERVER_NAME
from pipeline.mcp_permissions import (
    PHASE_LOCATE_TOOLS,
    audit_permissions,
    enrich_server_entry_permissions,
    merge_claude_settings_permissions,
    merge_cursor_permissions,
    write_tool_permission_artifacts,
)
from pipeline.rules_installer import format_server_entry, write_project_tool_surface
from pipeline.tool_registry import TOOL_MAP


@pytest.mark.parametrize(
    "slug",
    ["cursor", "cline", "roo-code", "opencode", "claude-code", "kiro"],
)
def test_enrich_server_entry_adds_auto_approve(slug: str) -> None:
    tool = TOOL_MAP[slug]
    entry = format_server_entry(tool, pin_repo=False)
    enriched = enrich_server_entry_permissions(entry, slug)
    assert enriched.get("autoApprove") or enriched.get("alwaysAllow")
    approved = enriched.get("autoApprove") or enriched.get("alwaysAllow") or []
    if slug == "opencode":
        assert enriched.get("autoApprove")
    else:
        assert set(PHASE_LOCATE_TOOLS).issubset(set(approved))


def test_cursor_permissions_merge_preserves_existing(tmp_path: Path) -> None:
    path = tmp_path / ".cursor" / "permissions.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"mcpAllowlist": ["other-server:tool"], "autoRun": {}}),
        encoding="utf-8",
    )
    result = merge_cursor_permissions(path)
    assert result["ok"]
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "other-server:tool" in data["mcpAllowlist"]
    assert f"{MCP_SERVER_NAME}:*" in data["mcpAllowlist"]
    assert any(str(x).startswith("*:") for x in data["mcpAllowlist"])


def test_claude_settings_merge(tmp_path: Path) -> None:
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"permissions": {"allow": ["Read(*)"]}}), encoding="utf-8")
    merge_claude_settings_permissions(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    allow = data["permissions"]["allow"]
    assert "Read(*)" in allow
    assert any(str(x).startswith("mcp__scubiee__") for x in allow)


def test_write_cursor_sidecar(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    report = write_tool_permission_artifacts("cursor", repo)
    assert report["ok"]
    perm_path = repo / ".cursor" / "permissions.json"
    assert perm_path.is_file()
    manifest = repo / ".scubiee" / "mcp-permissions.json"
    assert manifest.is_file()


def test_write_project_tool_surface_includes_permissions(tmp_path: Path) -> None:
    repo = tmp_path / "ws"
    repo.mkdir()
    (repo / ".git").mkdir()
    tool = TOOL_MAP["cline"]
    report = write_project_tool_surface(repo, tool)
    assert report.get("permissions")
    mcp_path = repo / ".cline" / "mcp.json"
    blob = json.loads(mcp_path.read_text(encoding="utf-8"))
    entry = blob["mcpServers"][MCP_SERVER_NAME]
    assert entry.get("autoApprove")


def test_audit_permissions_detects_missing_cursor(tmp_path: Path, monkeypatch) -> None:
    from pipeline.connect_state import save_connected_tools

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    save_connected_tools(["cursor"])
    out = audit_permissions(repo)
    assert out["ok"] is False
    assert out["checks"][0]["slug"] == "cursor"
