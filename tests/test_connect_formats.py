"""Connect formats: project-local MCP schemas + enrolled-repo fan-out."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.rules_installer import format_server_entry, install_tool, uninstall_tool
from pipeline.tool_registry import (
    ALL_SLUGS,
    TOOL_MAP,
    WORKSPACE_LOCAL_MCP_SLUGS,
    connect_restart_hint,
    get_tool,
    resolve_mcp_legacy_global_paths,
    resolve_mcp_project_paths,
    resolve_rule_project_path,
)

from conftest import write_machine_setup


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


def _enroll(repo: Path, pid: str, monkeypatch, tmp_path: Path) -> None:
    ce = repo / ".scubiee"
    ce.mkdir(exist_ok=True)
    (ce / "id.json").write_text(json.dumps({"project_id": pid}), encoding="utf-8")
    home = tmp_path / "ce-home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("CTX_HOME", str(home))
    write_machine_setup(home)
    from pipeline.project_id import save_registry

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


def test_connect_restart_hint_single_tool() -> None:
    assert (
        connect_restart_hint([{"ok": True, "tool": "Kiro"}])
        == "Restart Kiro to pick up MCP."
    )


def test_connect_restart_hint_multiple_tools() -> None:
    assert connect_restart_hint(
        [{"ok": True, "tool": "Cursor"}, {"ok": True, "tool": "Codex"}]
    ) == "Restart the coding tool you're using to pick up MCP."


def test_registry_has_priority_tools() -> None:
    for slug in ("codex", "claude-code", "kiro", "amp", "pi", "opencode", "copilot", "cursor", "devin-desktop"):
        assert slug in ALL_SLUGS


def test_windsurf_alias_resolves_to_devin_desktop() -> None:
    tool = get_tool("windsurf")
    assert tool is not None
    assert tool.slug == "devin-desktop"


def test_all_tools_have_project_mcp_paths(tmp_path: Path) -> None:
    assert len(WORKSPACE_LOCAL_MCP_SLUGS) == len(ALL_SLUGS)
    for slug in WORKSPACE_LOCAL_MCP_SLUGS:
        paths = resolve_mcp_project_paths(TOOL_MAP[slug], tmp_path)
        assert paths, slug
    for tool in TOOL_MAP.values():
        rule_proj = resolve_rule_project_path(tool, tmp_path)
        if tool.rule_format != "none" and tool.rule_user_path:
            assert rule_proj is not None
            assert rule_proj.is_relative_to(tmp_path)
        elif tool.slug == "devin-desktop":
            assert (tmp_path / ".devin" / "rules" / "scubiee.md") == rule_proj


def test_format_opencode_schema(tmp_path: Path) -> None:
    entry = format_server_entry(TOOL_MAP["opencode"], tmp_path, pin_repo=True)
    assert entry["type"] == "local"
    assert isinstance(entry["command"], list)
    assert "environment" in entry
    assert "env" not in entry


def _assert_no_workspace_token(value: object, *, where: str) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _assert_no_workspace_token(v, where=f"{where}.{k}")
        return
    if isinstance(value, list):
        for i, v in enumerate(value):
            _assert_no_workspace_token(v, where=f"{where}[{i}]")
        return
    if isinstance(value, str):
        assert "${workspaceFolder}" not in value, where
        assert "${" not in value, where


def test_format_global_entry_has_no_workspace_folder_token() -> None:
    from pipeline.rules_installer import _is_absolute_repo_pin

    for slug, tool in TOOL_MAP.items():
        entry = format_server_entry(tool, pin_repo=False)
        _assert_no_workspace_token(entry, where=slug)
        env = entry.get("env") or entry.get("environment") or {}
        ctx = str(env.get("CTX_REPO") or "")
        assert not _is_absolute_repo_pin(ctx), slug
        assert "CTX_REPO" not in env, slug
        cwd = str(entry.get("cwd") or "")
        assert not _is_absolute_repo_pin(cwd), slug
        assert "cwd" not in entry, slug


def test_install_cursor_project_local_only(
    fake_home: Path, tmp_path: Path, monkeypatch
) -> None:
    workspace = _git_repo(tmp_path / "ws")
    pid = "ce_cursor_local1234567890abcd"
    _enroll(workspace, pid, monkeypatch, tmp_path)

    report = install_tool(TOOL_MAP["cursor"], repo=workspace)
    assert report["ok"]
    assert report.get("scope") == "project-local"
    assert report["project_fan_out"]["repos"] == 1
    assert (workspace / ".cursor" / "mcp.json").is_file()
    assert not (fake_home / ".cursor" / "mcp.json").exists()


def test_cleanup_project_gate_rules_removes_legacy_pollution(tmp_path: Path) -> None:
    from pipeline.rules_installer import cleanup_project_gate_rules

    workspace = _git_repo(tmp_path / "ws")
    ce = workspace / ".scubiee"
    ce.mkdir()
    (ce / "id.json").write_text(json.dumps({"project_id": "ce_abc123"}), encoding="utf-8")
    cursor_rule = workspace / ".cursor" / "rules" / "scubiee.mdc"
    cursor_rule.parent.mkdir(parents=True)
    cursor_rule.write_text("<!-- scubiee:start -->\nGATE\n<!-- scubiee:end -->\n", encoding="utf-8")
    kiro_rule = workspace / ".kiro" / "steering" / "scubiee.md"
    kiro_rule.parent.mkdir(parents=True)
    kiro_rule.write_text("# kiro\n", encoding="utf-8")

    report = cleanup_project_gate_rules(workspace)
    assert report["ok"]
    assert not cursor_rule.exists()
    assert not kiro_rule.exists()


def test_install_codex_writes_project_mcp(
    fake_home: Path, tmp_path: Path, monkeypatch
) -> None:
    workspace = _git_repo(tmp_path / "ws")
    pid = "ce_codex_local1234567890abcd"
    _enroll(workspace, pid, monkeypatch, tmp_path)
    report = install_tool(TOOL_MAP["codex"], repo=workspace)
    assert report["ok"]
    project_text = (workspace / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert "[mcp_servers.scubiee]" in project_text
    assert "CTX_REPO" in project_text
    assert not (fake_home / ".codex" / "config.toml").exists()


def test_install_claude_code_project_mcp(
    fake_home: Path, tmp_path: Path, monkeypatch
) -> None:
    workspace = _git_repo(tmp_path / "ws")
    pid = "ce_claude_local1234567890abcd"
    _enroll(workspace, pid, monkeypatch, tmp_path)
    install_tool(TOOL_MAP["claude-code"], repo=workspace)
    assert (workspace / ".mcp.json").is_file()
    assert not (fake_home / ".claude.json").exists()


def test_install_devin_desktop_project_mcp(
    fake_home: Path, tmp_path: Path, monkeypatch
) -> None:
    workspace = _git_repo(tmp_path / "ws")
    pid = "ce_devin_local1234567890abcd"
    _enroll(workspace, pid, monkeypatch, tmp_path)
    install_tool(get_tool("windsurf"), repo=workspace)
    assert (workspace / ".devin" / "mcp_config.json").is_file()
    assert (workspace / ".devin" / "rules" / "scubiee.md").is_file()
    legacy = fake_home / ".codeium" / "windsurf" / "mcp_config.json"
    assert not legacy.exists()


def test_install_zed_project_mcp(fake_home: Path, tmp_path: Path, monkeypatch) -> None:
    workspace = _git_repo(tmp_path / "ws")
    pid = "ce_zed_local1234567890abcdef"
    _enroll(workspace, pid, monkeypatch, tmp_path)
    install_tool(TOOL_MAP["zed"], repo=workspace)
    zed_path = workspace / ".zed" / "settings.json"
    assert zed_path.is_file()
    zed = json.loads(zed_path.read_text(encoding="utf-8"))
    assert "scubiee" in zed["context_servers"]
    assert not (fake_home / ".config" / "zed" / "settings.json").exists()


def test_connect_removes_legacy_global_mcp(
    fake_home: Path, tmp_path: Path, monkeypatch
) -> None:
    workspace = _git_repo(tmp_path / "ws")
    pid = "ce_legacy_rm1234567890abcdef"
    _enroll(workspace, pid, monkeypatch, tmp_path)
    legacy = fake_home / ".cursor" / "mcp.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        json.dumps({"mcpServers": {"scubiee": {"command": "x", "args": []}}}),
        encoding="utf-8",
    )
    report = install_tool(TOOL_MAP["cursor"])
    assert report["ok"]
    assert str(legacy) in report.get("legacy_global_removed", [])
    assert not legacy.exists()


def test_uninstall_removes_project_mcp(fake_home: Path, tmp_path: Path, monkeypatch) -> None:
    workspace = _git_repo(tmp_path / "ws")
    pid = "ce_uninst1234567890abcdef"
    _enroll(workspace, pid, monkeypatch, tmp_path)
    install_tool(TOOL_MAP["opencode"])
    assert (workspace / "opencode.json").is_file()
    report = uninstall_tool(TOOL_MAP["opencode"], all_workspaces=True)
    assert report["ok"]
    assert report["mcp_removed"]
    assert not (workspace / "opencode.json").exists()


def test_disconnect_removes_project_mcp(fake_home: Path, tmp_path: Path, monkeypatch) -> None:
    workspace = _git_repo(tmp_path / "ws")
    pid = "ce_disc_one1234567890abcdef"
    _enroll(workspace, pid, monkeypatch, tmp_path)
    install_tool(TOOL_MAP["cursor"])
    legacy = workspace / ".cursor" / "mcp.json"
    assert legacy.is_file()
    report = uninstall_tool(TOOL_MAP["cursor"], repo=workspace, all_workspaces=False)
    assert report.get("project_surface", {}).get("mcp_removed") is True
    assert not legacy.exists()


def test_kiro_cli_dry_run_project_local(tmp_path: Path, monkeypatch, capsys) -> None:
    from pipeline.__main__ import main

    target = _git_repo(tmp_path / "workspace")
    monkeypatch.chdir(target)
    assert main(["connect", "--kiro", "--dry-run"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report[0]["scope"] == "project-local"


def test_legacy_global_paths_include_devin_cascade(fake_home: Path) -> None:
    tool = TOOL_MAP["devin-desktop"]
    paths = [str(p) for p, _s, _k in resolve_mcp_legacy_global_paths(tool)]
    assert str(fake_home / ".codeium" / "windsurf" / "mcp_config.json") in paths
    assert str(fake_home / "AppData" / "Roaming" / "devin" / "mcp_config.json") in paths
