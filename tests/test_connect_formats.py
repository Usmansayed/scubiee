"""Global connect: MCP schemas + Win/Mac paths; no per-repo MCP pins."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.rules_installer import format_server_entry, install_tool, uninstall_tool
from pipeline.tool_registry import (
    ALL_SLUGS,
    LEGACY_WORKSPACE_MCP_SLUGS,
    TOOL_MAP,
    WORKSPACE_LOCAL_MCP_SLUGS,
    connect_restart_hint,
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
    for slug in ("codex", "claude-code", "kiro", "amp", "pi", "opencode", "copilot", "cursor"):
        assert slug in ALL_SLUGS


def test_connect_does_not_write_workspace_mcp(tmp_path: Path) -> None:
    assert WORKSPACE_LOCAL_MCP_SLUGS == frozenset()
    for tool in TOOL_MAP.values():
        assert not resolve_mcp_project_paths(tool, tmp_path) or tool.slug not in WORKSPACE_LOCAL_MCP_SLUGS
        rule_proj = resolve_rule_project_path(tool, tmp_path)
        if tool.rule_format != "none" and tool.rule_user_path:
            assert rule_proj is not None
            assert rule_proj.is_relative_to(tmp_path)
        else:
            assert rule_proj is None


def test_legacy_project_paths_for_disconnect_cleanup(tmp_path: Path) -> None:
    for slug in LEGACY_WORKSPACE_MCP_SLUGS:
        paths = resolve_mcp_project_paths(TOOL_MAP[slug], tmp_path)
        assert paths, slug


def test_format_opencode_schema(tmp_path: Path) -> None:
    entry = format_server_entry(TOOL_MAP["opencode"], tmp_path, pin_repo=True)
    # pin_repo True only for unit shape test; install always uses False
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
    cursor_env = format_server_entry(TOOL_MAP["cursor"], pin_repo=False)["env"]
    assert "CURSOR_PROJECT_DIR" not in cursor_env
    assert "CURSOR_CWD" not in cursor_env
    assert cursor_env.get("CTX_MCP_SESSION_ISOLATE") == "1"
    assert cursor_env.get("CTX_MCP_CLIENT") == "cursor"
    codex_env = format_server_entry(TOOL_MAP["codex"], pin_repo=False).get("env") or {}
    assert codex_env.get("CTX_MCP_CLIENT") == "codex"
    cli = format_server_entry(TOOL_MAP["copilot"], pin_repo=False, schema="copilot_cli")
    _assert_no_workspace_token(cli, where="copilot_cli")


def test_format_vscode_has_type_stdio() -> None:
    entry = format_server_entry(TOOL_MAP["copilot"], pin_repo=False)
    assert entry["type"] == "stdio"


def test_install_cursor_global_only(fake_home: Path, tmp_path: Path) -> None:
    workspace = _git_repo(tmp_path / "ws")
    ce = workspace / ".scubiee"
    ce.mkdir()
    pid = "ce_connect_test1234567890abcdef"
    (ce / "id.json").write_text(json.dumps({"project_id": pid}), encoding="utf-8")
    legacy = workspace / ".cursor" / "mcp.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        json.dumps({"mcpServers": {"scubiee": {"command": "x", "env": {}}}}),
        encoding="utf-8",
    )
    report = install_tool(TOOL_MAP["cursor"], repo=workspace)
    assert report["ok"]
    assert report.get("scope") == "global"
    assert not report.get("workspace_mcp_written")
    assert not legacy.exists()
    mcp = json.loads((fake_home / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    env = mcp["mcpServers"]["scubiee"]["env"]
    assert "CTX_REPO" not in env
    assert not (fake_home / ".cursor" / "rules" / "scubiee.mdc").exists()
    assert not (workspace / ".cursor" / "rules" / "scubiee.mdc").exists()
    assert not (workspace / ".cursor" / "mcp.json").exists()


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


def test_install_codex_global_only(fake_home: Path, tmp_path: Path) -> None:
    workspace = _git_repo(tmp_path / "ws")
    report = install_tool(TOOL_MAP["codex"], repo=workspace)
    assert report["ok"]
    assert not report.get("workspace_mcp_written")
    global_text = (fake_home / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert "${workspaceFolder}" not in global_text
    assert "cwd =" not in global_text.split("[mcp_servers.scubiee]", 1)[-1].split("[", 1)[0]
    assert not (workspace / ".codex" / "config.toml").exists()


def test_install_opencode_global_only(fake_home: Path, tmp_path: Path) -> None:
    workspace = _git_repo(tmp_path / "ws")
    report = install_tool(TOOL_MAP["opencode"], repo=workspace)
    assert report["ok"]
    assert not report.get("workspace_mcp_written")
    path = fake_home / ".config" / "opencode" / "opencode.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "CTX_REPO" not in data["mcp"]["scubiee"]["environment"]
    assert not (workspace / "opencode.json").exists()


def test_install_amp_global_only(fake_home: Path, tmp_path: Path) -> None:
    workspace = _git_repo(tmp_path / "ws")
    report = install_tool(TOOL_MAP["amp"], repo=workspace)
    assert report["ok"]
    assert not report.get("workspace_mcp_written")
    assert not (workspace / ".amp" / "settings.json").exists()


def test_install_pi_global_only(fake_home: Path, tmp_path: Path) -> None:
    workspace = _git_repo(tmp_path / "ws")
    report = install_tool(TOOL_MAP["pi"], repo=workspace)
    assert report["ok"]
    assert not report.get("workspace_mcp_written")
    assert not (workspace / ".mcp.json").exists()


def test_install_continue_global_only(fake_home: Path, tmp_path: Path) -> None:
    workspace = _git_repo(tmp_path / "ws")
    report = install_tool(TOOL_MAP["continue"], repo=workspace)
    assert report["ok"]
    assert not report.get("workspace_mcp_written")
    assert not (workspace / ".continue" / "mcpServers" / "scubiee.yaml").exists()


def test_install_kiro_global_only(fake_home: Path, tmp_path: Path) -> None:
    workspace = _git_repo(tmp_path / "ws")
    report = install_tool(TOOL_MAP["kiro"], repo=workspace)
    assert report["ok"]
    assert not report.get("workspace_mcp_written")
    user = json.loads((fake_home / ".kiro" / "settings" / "mcp.json").read_text(encoding="utf-8"))
    assert "CTX_REPO" not in user["mcpServers"]["scubiee"]["env"]
    assert not (workspace / ".kiro" / "settings" / "mcp.json").exists()
    assert not (fake_home / ".kiro" / "steering" / "scubiee.md").exists()


def test_install_claude_code_global(fake_home: Path, tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    install_tool(TOOL_MAP["claude-code"], repo=workspace)
    data = json.loads((fake_home / ".claude.json").read_text(encoding="utf-8"))
    env = data["mcpServers"]["scubiee"]["env"]
    assert "CTX_REPO" not in env
    assert not (fake_home / ".claude" / "CLAUDE.md").exists()
    assert not (workspace / ".mcp.json").exists()


def test_install_codex_toml_and_agents_md(fake_home: Path) -> None:
    install_tool(TOOL_MAP["codex"])
    text = (fake_home / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert "[mcp_servers.scubiee]" in text
    assert "${workspaceFolder}" not in text
    assert "CTX_REPO" not in text
    assert not (fake_home / ".codex" / "AGENTS.md").exists()


def test_install_opencode_global_opencode_json(fake_home: Path, tmp_path: Path) -> None:
    install_tool(TOOL_MAP["opencode"])
    path = fake_home / ".config" / "opencode" / "opencode.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    entry = data["mcp"]["scubiee"]
    assert entry["type"] == "local"
    assert "CTX_REPO" not in entry["environment"]


def test_install_amp_dotted_key(fake_home: Path) -> None:
    install_tool(TOOL_MAP["amp"])
    data = json.loads((fake_home / ".config" / "amp" / "settings.json").read_text(encoding="utf-8"))
    assert "amp.mcpServers" in data
    env = data["amp.mcpServers"]["scubiee"].get("env", {})
    assert "CTX_REPO" not in env


def test_install_copilot_user_profile_and_cli(fake_home: Path, tmp_path: Path) -> None:
    workspace = _git_repo(tmp_path / "ws")
    report = install_tool(TOOL_MAP["copilot"], repo=workspace)
    assert report["ok"]
    assert report["rule_written"] is None
    assert not report.get("workspace_mcp_written")

    vscode_path = resolve_mcp_user_path(TOOL_MAP["copilot"])
    assert vscode_path is not None
    vscode = json.loads(vscode_path.read_text(encoding="utf-8"))
    assert vscode["servers"]["scubiee"]["type"] == "stdio"
    assert "CTX_REPO" not in vscode["servers"]["scubiee"]["env"]

    cli = json.loads((fake_home / ".copilot" / "mcp-config.json").read_text(encoding="utf-8"))
    entry = cli["mcpServers"]["scubiee"]
    assert entry["type"] == "local"
    assert "CTX_REPO" not in entry["env"]

    assert not (workspace / ".vscode" / "mcp.json").exists()
    assert not (workspace / ".mcp.json").exists()


def test_format_copilot_cli_schema() -> None:
    entry = format_server_entry(TOOL_MAP["copilot"], pin_repo=False, schema="copilot_cli")
    assert entry["type"] == "local"
    assert entry["tools"] == ["*"]


def test_install_cline_writes_vscode_and_cli(fake_home: Path) -> None:
    paths = resolve_mcp_user_paths(TOOL_MAP["cline"])
    assert len(paths) == 2
    install_tool(TOOL_MAP["cline"])
    for p in paths:
        data = json.loads(p.read_text(encoding="utf-8"))
        assert "scubiee" in data["mcpServers"]


def test_install_pi_global(fake_home: Path) -> None:
    install_tool(TOOL_MAP["pi"])
    data = json.loads((fake_home / ".pi" / "agent" / "mcp.json").read_text(encoding="utf-8"))
    assert "CTX_REPO" not in data["mcpServers"]["scubiee"]["env"]


def test_install_windsurf_continue_zed_global_omit_workspace_token(fake_home: Path) -> None:
    install_tool(TOOL_MAP["windsurf"])
    windsurf = json.loads(
        (fake_home / ".codeium" / "windsurf" / "mcp_config.json").read_text(encoding="utf-8")
    )
    wenv = windsurf["mcpServers"]["scubiee"]["env"]
    assert "CTX_REPO" not in wenv

    install_tool(TOOL_MAP["continue"])
    cont = (fake_home / ".continue" / "config.yaml").read_text(encoding="utf-8")
    assert "CTX_REPO:" not in cont

    install_tool(TOOL_MAP["zed"])
    zed_path = resolve_mcp_user_path(TOOL_MAP["zed"])
    assert zed_path is not None and zed_path.is_file()
    zed = json.loads(zed_path.read_text(encoding="utf-8"))
    zenv = zed["context_servers"]["scubiee"]["env"]
    assert "CTX_REPO" not in zenv


def test_uninstall_global(fake_home: Path) -> None:
    install_tool(TOOL_MAP["opencode"])
    install_tool(TOOL_MAP["codex"])
    assert uninstall_tool(TOOL_MAP["opencode"])["mcp_removed"]
    assert uninstall_tool(TOOL_MAP["codex"])["mcp_removed"]


def test_disconnect_removes_legacy_workspace_mcp(fake_home: Path, tmp_path: Path) -> None:
    workspace = _git_repo(tmp_path / "ws")
    legacy = workspace / ".cursor" / "mcp.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        json.dumps({"mcpServers": {"scubiee": {"command": "x", "env": {"CTX_REPO": "/x"}}}}),
        encoding="utf-8",
    )
    report = uninstall_tool(TOOL_MAP["cursor"], repo=workspace)
    assert report.get("workspace_mcp_removed") is True
    assert not legacy.exists()


def test_kiro_cli_dry_run_global(tmp_path: Path, monkeypatch, capsys) -> None:
    from pipeline.__main__ import main

    target = _git_repo(tmp_path / "workspace")
    monkeypatch.chdir(target)
    assert main(["connect", "--kiro", "--dry-run"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report[0]["scope"] == "global"
    assert not report[0].get("would_write_workspace_mcp_paths")


def _mock_os(monkeypatch: pytest.MonkeyPatch, os_name: str) -> None:
    from pipeline import tool_registry as tr

    monkeypatch.setattr(tr, "_is_windows", lambda: os_name == "Windows")
    monkeypatch.setattr(tr, "_is_darwin", lambda: os_name == "Darwin")


@pytest.mark.parametrize(
    ("os_name", "vscode_user_rel"),
    [
        ("Darwin", Path("Library") / "Application Support" / "Code" / "User"),
        ("Windows", Path("AppData") / "Roaming" / "Code" / "User"),
        ("Linux", Path(".config") / "Code" / "User"),
    ],
)
def test_vscode_family_global_mcp_paths_respect_os(
    fake_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    os_name: str,
    vscode_user_rel: Path,
) -> None:
    _mock_os(monkeypatch, os_name)
    vscode_user = fake_home / vscode_user_rel
    copilot = resolve_mcp_user_paths(TOOL_MAP["copilot"])
    assert copilot[0] == vscode_user / "mcp.json"


@pytest.mark.parametrize("os_name", ["Darwin", "Windows", "Linux"])
def test_install_copilot_writes_os_specific_vscode_mcp(
    fake_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    os_name: str,
) -> None:
    _mock_os(monkeypatch, os_name)
    workspace = _git_repo(tmp_path / "ws")
    report = install_tool(TOOL_MAP["copilot"], repo=workspace)
    assert report["ok"]
    vscode_path = resolve_mcp_user_path(TOOL_MAP["copilot"])
    assert vscode_path is not None and vscode_path.is_file()
