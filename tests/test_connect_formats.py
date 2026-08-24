"""Global connect: MCP schemas + Win/Mac paths; workspace-local for 4 hosts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.rules_installer import format_server_entry, install_tool, uninstall_tool
from pipeline.tool_registry import (
    ALL_SLUGS,
    TOOL_MAP,
    WORKSPACE_LOCAL_MCP_SLUGS,
    resolve_mcp_project_paths,
    resolve_mcp_user_path,
    resolve_mcp_user_paths,
    resolve_rule_project_path,
)


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    return home


def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()
    return path


def test_registry_has_priority_tools() -> None:
    for slug in ("codex", "claude-code", "kiro", "amp", "pi", "opencode", "copilot", "cursor"):
        assert slug in ALL_SLUGS


def test_project_paths_only_for_workspace_local_tools(tmp_path: Path) -> None:
    for tool in TOOL_MAP.values():
        paths = resolve_mcp_project_paths(tool, tmp_path)
        if tool.slug in WORKSPACE_LOCAL_MCP_SLUGS:
            assert paths
        else:
            assert paths == []
        assert resolve_rule_project_path(tool, tmp_path) is None


def test_format_opencode_schema(tmp_path: Path) -> None:
    entry = format_server_entry(TOOL_MAP["opencode"], tmp_path, pin_repo=True)
    # pin_repo True only for unit shape test; install always uses False
    assert entry["type"] == "local"
    assert isinstance(entry["command"], list)
    assert "environment" in entry
    assert "env" not in entry


def test_format_global_entry_has_no_ctx_repo() -> None:
    for slug in ("cursor", "claude-code", "codex", "kiro", "opencode", "amp", "copilot"):
        entry = format_server_entry(TOOL_MAP[slug], pin_repo=False)
        blob = json.dumps(entry)
        assert "CTX_REPO" not in blob


def test_format_vscode_has_type_stdio() -> None:
    entry = format_server_entry(TOOL_MAP["copilot"], pin_repo=False)
    assert entry["type"] == "stdio"


def test_install_cursor_global_mcp_and_rules(fake_home: Path, tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    report = install_tool(TOOL_MAP["cursor"], repo=workspace)
    assert report["ok"]
    assert report.get("repo_ignored") is True
    mcp = json.loads((fake_home / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert "CTX_REPO" not in mcp["mcpServers"]["context-engine"]["env"]
    assert (fake_home / ".cursor" / "rules" / "context-agent.mdc").is_file()
    # Must not touch the project
    assert not (workspace / ".cursor").exists()


def test_install_kiro_global_and_workspace_mcp(fake_home: Path, tmp_path: Path) -> None:
    workspace = _git_repo(tmp_path / "ws")
    report = install_tool(TOOL_MAP["kiro"], repo=workspace)
    assert report["ok"]
    assert report.get("workspace_mcp_written") is True
    user = json.loads((fake_home / ".kiro" / "settings" / "mcp.json").read_text(encoding="utf-8"))
    assert "CTX_REPO" not in user["mcpServers"]["context-engine"]["env"]
    project = json.loads((workspace / ".kiro" / "settings" / "mcp.json").read_text(encoding="utf-8"))
    assert project["mcpServers"]["context-engine"]["env"]["CTX_REPO"] == str(workspace).replace("\\", "/")
    assert (fake_home / ".kiro" / "steering" / "context-engine.md").is_file()
    assert report.get("notice")


def test_install_kiro_skips_workspace_without_git(
    fake_home: Path, tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "plain"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    report = install_tool(TOOL_MAP["kiro"])
    assert report["ok"]
    assert report.get("workspace_mcp_skipped") is True
    assert not (workspace / ".kiro").exists()


def test_install_claude_code_global(fake_home: Path, tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    install_tool(TOOL_MAP["claude-code"], repo=workspace)
    data = json.loads((fake_home / ".claude.json").read_text(encoding="utf-8"))
    assert "CTX_REPO" not in data["mcpServers"]["context-engine"]["env"]
    assert "<!-- context-engine:start -->" in (fake_home / ".claude" / "CLAUDE.md").read_text(
        encoding="utf-8"
    )
    assert not (workspace / ".mcp.json").exists()


def test_install_codex_toml_and_agents_md(fake_home: Path) -> None:
    install_tool(TOOL_MAP["codex"])
    text = (fake_home / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert "[mcp_servers.context-engine]" in text
    assert "CTX_REPO" not in text
    assert (fake_home / ".codex" / "AGENTS.md").is_file()


def test_install_opencode_global_opencode_json(fake_home: Path, tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    install_tool(TOOL_MAP["opencode"], repo=workspace)
    path = fake_home / ".config" / "opencode" / "opencode.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    entry = data["mcp"]["context-engine"]
    assert entry["type"] == "local"
    assert isinstance(entry["command"], list)
    assert "environment" in entry
    assert "CTX_REPO" not in entry["environment"]
    assert not (workspace / "opencode.json").exists()


def test_install_amp_dotted_key(fake_home: Path) -> None:
    install_tool(TOOL_MAP["amp"])
    data = json.loads((fake_home / ".config" / "amp" / "settings.json").read_text(encoding="utf-8"))
    assert "amp.mcpServers" in data
    assert "CTX_REPO" not in data["amp.mcpServers"]["context-engine"].get("env", {})


def test_install_copilot_user_profile_and_cli(fake_home: Path, tmp_path: Path) -> None:
    workspace = _git_repo(tmp_path / "ws")
    report = install_tool(TOOL_MAP["copilot"], repo=workspace)
    assert report["ok"]
    assert report["rule_written"] is True
    assert report.get("workspace_mcp_written") is True

    vscode_path = resolve_mcp_user_path(TOOL_MAP["copilot"])
    assert vscode_path is not None
    vscode = json.loads(vscode_path.read_text(encoding="utf-8"))
    assert vscode["servers"]["context-engine"]["type"] == "stdio"
    assert "CTX_REPO" not in vscode["servers"]["context-engine"]["env"]

    cli = json.loads((fake_home / ".copilot" / "mcp-config.json").read_text(encoding="utf-8"))
    entry = cli["mcpServers"]["context-engine"]
    assert entry["type"] == "local"
    assert entry["tools"] == ["*"]
    assert "CTX_REPO" not in entry["env"]

    proj_vscode = json.loads((workspace / ".vscode" / "mcp.json").read_text(encoding="utf-8"))
    assert proj_vscode["servers"]["context-engine"]["env"]["CTX_REPO"] == str(workspace).replace("\\", "/")
    root_mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
    assert root_mcp["mcpServers"]["context-engine"]["env"]["CTX_REPO"] == str(workspace).replace("\\", "/")

    instructions = (fake_home / ".copilot" / "copilot-instructions.md").read_text(encoding="utf-8")
    assert "<!-- context-engine:start -->" in instructions
    modular = (
        fake_home / ".copilot" / "instructions" / "context-engine.instructions.md"
    ).read_text(encoding="utf-8")
    assert "<!-- context-engine:start -->" in modular


def test_format_copilot_cli_schema() -> None:
    entry = format_server_entry(TOOL_MAP["copilot"], pin_repo=False, schema="copilot_cli")
    assert entry["type"] == "local"
    assert entry["tools"] == ["*"]
    assert "command" in entry and "args" in entry


def test_install_cline_writes_vscode_and_cli(fake_home: Path) -> None:
    paths = resolve_mcp_user_paths(TOOL_MAP["cline"])
    assert len(paths) == 2
    assert "saoudrizwan.claude-dev" in str(paths[0])
    assert str(paths[1]).endswith(str(Path(".cline") / "data" / "settings" / "cline_mcp_settings.json"))
    install_tool(TOOL_MAP["cline"])
    for p in paths:
        data = json.loads(p.read_text(encoding="utf-8"))
        assert "context-engine" in data["mcpServers"]
    assert (fake_home / ".cline" / "rules" / "context-engine.md").is_file()


def test_install_pi_global(fake_home: Path) -> None:
    install_tool(TOOL_MAP["pi"])
    data = json.loads((fake_home / ".pi" / "agent" / "mcp.json").read_text(encoding="utf-8"))
    assert "CTX_REPO" not in data["mcpServers"]["context-engine"]["env"]


def test_uninstall_global(fake_home: Path) -> None:
    install_tool(TOOL_MAP["opencode"])
    install_tool(TOOL_MAP["codex"])
    assert uninstall_tool(TOOL_MAP["opencode"])["mcp_removed"]
    data = json.loads(
        (fake_home / ".config" / "opencode" / "opencode.json").read_text(encoding="utf-8")
    )
    assert "context-engine" not in data.get("mcp", {})
    assert uninstall_tool(TOOL_MAP["codex"])["mcp_removed"]
    assert "[mcp_servers.context-engine]" not in (
        fake_home / ".codex" / "config.toml"
    ).read_text(encoding="utf-8")


def test_kiro_cli_dry_run_global(tmp_path: Path, monkeypatch, capsys) -> None:
    from pipeline.__main__ import main

    target = _git_repo(tmp_path / "workspace")
    monkeypatch.chdir(target)
    assert main(["connect", "--kiro", "--dry-run"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report[0]["scope"] == "global+workspace"
    assert report[0].get("would_write_workspace_mcp_paths")
    assert str(target / ".kiro" / "settings" / "mcp.json") in report[0][
        "would_write_workspace_mcp_paths"
    ]
