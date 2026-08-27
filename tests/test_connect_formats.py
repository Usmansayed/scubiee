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
        rule_proj = resolve_rule_project_path(tool, tmp_path)
        if tool.rule_format != "none" and tool.rule_user_path:
            assert rule_proj is not None
            assert rule_proj.is_relative_to(tmp_path)
        else:
            assert rule_proj is None


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
    cli = format_server_entry(TOOL_MAP["copilot"], pin_repo=False, schema="copilot_cli")
    _assert_no_workspace_token(cli, where="copilot_cli")


def test_format_vscode_has_type_stdio() -> None:
    entry = format_server_entry(TOOL_MAP["copilot"], pin_repo=False)
    assert entry["type"] == "stdio"


def test_install_cursor_global_and_project_mcp(fake_home: Path, tmp_path: Path) -> None:
    """Cursor: omit unexpanded tokens from global; absolute pin in project MCP only."""
    workspace = _git_repo(tmp_path / "ws")
    ce = workspace / ".scubiee"
    ce.mkdir()
    pid = "ce_connect_test1234567890abcdef"
    (ce / "id.json").write_text(json.dumps({"project_id": pid}), encoding="utf-8")
    report = install_tool(TOOL_MAP["cursor"], repo=workspace)
    assert report["ok"]
    assert report.get("workspace_mcp_written") is True
    assert report.get("repo_ignored") is not True
    mcp = json.loads((fake_home / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    env = mcp["mcpServers"]["scubiee"]["env"]
    assert "CTX_REPO" not in env
    assert "CURSOR_PROJECT_DIR" not in env
    assert "CURSOR_CWD" not in env
    assert (fake_home / ".cursor" / "rules" / "scubiee.mdc").is_file()
    project_rule = workspace / ".cursor" / "rules" / "scubiee.mdc"
    assert project_rule.is_file()
    rule_text = project_rule.read_text(encoding="utf-8")
    assert "GATE" in rule_text
    assert pid in rule_text
    assert "project_id" in rule_text
    project = json.loads((workspace / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert project["mcpServers"]["scubiee"]["env"]["CTX_REPO"] == str(workspace).replace(
        "\\", "/"
    )
    assert not (report.get("notice") or "").strip()


def test_install_codex_project_toml_absolute_cwd(fake_home: Path, tmp_path: Path) -> None:
    workspace = _git_repo(tmp_path / "ws")
    report = install_tool(TOOL_MAP["codex"], repo=workspace)
    assert report["ok"]
    assert report.get("workspace_mcp_written") is True
    global_text = (fake_home / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert "${workspaceFolder}" not in global_text
    assert "cwd =" not in global_text.split("[mcp_servers.scubiee]", 1)[-1].split("[", 1)[0]
    project = (workspace / ".codex" / "config.toml").read_text(encoding="utf-8")
    repo_s = str(workspace.resolve()).replace("\\", "/")
    assert f'cwd = "{repo_s}"' in project
    assert f'CTX_REPO = "{repo_s}"' in project


def test_install_opencode_project_json(fake_home: Path, tmp_path: Path) -> None:
    workspace = _git_repo(tmp_path / "ws")
    report = install_tool(TOOL_MAP["opencode"], repo=workspace)
    assert report["ok"]
    assert report.get("workspace_mcp_written") is True
    path = fake_home / ".config" / "opencode" / "opencode.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "CTX_REPO" not in data["mcp"]["scubiee"]["environment"]
    assert "${workspaceFolder}" not in path.read_text(encoding="utf-8")
    project = json.loads((workspace / "opencode.json").read_text(encoding="utf-8"))
    entry = project["mcp"]["scubiee"]
    repo_s = str(workspace.resolve()).replace("\\", "/")
    assert entry["environment"]["CTX_REPO"] == repo_s
    assert entry.get("cwd") == repo_s


def test_install_amp_project_settings(fake_home: Path, tmp_path: Path) -> None:
    workspace = _git_repo(tmp_path / "ws")
    report = install_tool(TOOL_MAP["amp"], repo=workspace)
    assert report["ok"]
    assert report.get("workspace_mcp_written") is True
    project = json.loads((workspace / ".amp" / "settings.json").read_text(encoding="utf-8"))
    env = project["amp.mcpServers"]["scubiee"]["env"]
    assert env["CTX_REPO"] == str(workspace.resolve()).replace("\\", "/")
    assert not (report.get("notice") or "").strip()


def test_install_pi_project_mcp_json(fake_home: Path, tmp_path: Path) -> None:
    workspace = _git_repo(tmp_path / "ws")
    report = install_tool(TOOL_MAP["pi"], repo=workspace)
    assert report["ok"]
    assert report.get("workspace_mcp_written") is True
    project = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
    assert project["mcpServers"]["scubiee"]["env"]["CTX_REPO"] == str(
        workspace.resolve()
    ).replace("\\", "/")


def test_install_continue_project_mcp_servers_yaml(fake_home: Path, tmp_path: Path) -> None:
    workspace = _git_repo(tmp_path / "ws")
    report = install_tool(TOOL_MAP["continue"], repo=workspace)
    assert report["ok"]
    assert report.get("workspace_mcp_written") is True
    path = workspace / ".continue" / "mcpServers" / "scubiee.yaml"
    text = path.read_text(encoding="utf-8")
    repo_s = str(workspace.resolve()).replace("\\", "/")
    assert "schema: v1" in text
    assert f'CTX_REPO: "{repo_s}"' in text
    assert f'cwd: "{repo_s}"' in text


def test_install_kiro_global_and_workspace_mcp(fake_home: Path, tmp_path: Path) -> None:
    workspace = _git_repo(tmp_path / "ws")
    report = install_tool(TOOL_MAP["kiro"], repo=workspace)
    assert report["ok"]
    assert report.get("workspace_mcp_written") is True
    user = json.loads((fake_home / ".kiro" / "settings" / "mcp.json").read_text(encoding="utf-8"))
    assert "CTX_REPO" not in user["mcpServers"]["scubiee"]["env"]
    project = json.loads((workspace / ".kiro" / "settings" / "mcp.json").read_text(encoding="utf-8"))
    assert project["mcpServers"]["scubiee"]["env"]["CTX_REPO"] == str(workspace).replace("\\", "/")
    assert (fake_home / ".kiro" / "steering" / "scubiee.md").is_file()
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
    env = data["mcpServers"]["scubiee"]["env"]
    assert "CTX_REPO" not in env
    assert "WORKSPACE_FOLDER" not in env
    assert "<!-- scubiee:start -->" in (fake_home / ".claude" / "CLAUDE.md").read_text(
        encoding="utf-8"
    )
    assert not (workspace / ".mcp.json").exists()


def test_install_codex_toml_and_agents_md(fake_home: Path) -> None:
    install_tool(TOOL_MAP["codex"])
    text = (fake_home / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert "[mcp_servers.scubiee]" in text
    assert "${workspaceFolder}" not in text
    assert "CTX_REPO" not in text
    assert "cwd =" not in text.split("[mcp_servers.scubiee]", 1)[-1].split("[", 1)[0]
    assert (fake_home / ".codex" / "AGENTS.md").is_file()


def test_install_opencode_global_opencode_json(fake_home: Path, tmp_path: Path) -> None:
    # No repo= → global only
    install_tool(TOOL_MAP["opencode"])
    path = fake_home / ".config" / "opencode" / "opencode.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    entry = data["mcp"]["scubiee"]
    assert entry["type"] == "local"
    assert isinstance(entry["command"], list)
    assert "environment" in entry
    assert "CTX_REPO" not in entry["environment"]
    assert "OPENCODE_DEFAULT_PROJECT" not in entry["environment"]


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
    assert report["rule_written"] is True
    assert report.get("workspace_mcp_written") is True

    vscode_path = resolve_mcp_user_path(TOOL_MAP["copilot"])
    assert vscode_path is not None
    vscode = json.loads(vscode_path.read_text(encoding="utf-8"))
    assert vscode["servers"]["scubiee"]["type"] == "stdio"
    assert "CTX_REPO" not in vscode["servers"]["scubiee"]["env"]

    cli = json.loads((fake_home / ".copilot" / "mcp-config.json").read_text(encoding="utf-8"))
    entry = cli["mcpServers"]["scubiee"]
    assert entry["type"] == "local"
    assert entry["tools"] == ["*"]
    assert "CTX_REPO" not in entry["env"]

    proj_vscode = json.loads((workspace / ".vscode" / "mcp.json").read_text(encoding="utf-8"))
    assert proj_vscode["servers"]["scubiee"]["env"]["CTX_REPO"] == str(workspace).replace("\\", "/")
    root_mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
    assert root_mcp["mcpServers"]["scubiee"]["env"]["CTX_REPO"] == str(workspace).replace("\\", "/")

    instructions = (fake_home / ".copilot" / "copilot-instructions.md").read_text(encoding="utf-8")
    assert "<!-- scubiee:start -->" in instructions
    modular = (
        fake_home / ".copilot" / "instructions" / "scubiee.instructions.md"
    ).read_text(encoding="utf-8")
    assert "<!-- scubiee:start -->" in modular


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
        assert "scubiee" in data["mcpServers"]
    assert (fake_home / ".cline" / "rules" / "scubiee.md").is_file()


def test_install_pi_global(fake_home: Path) -> None:
    install_tool(TOOL_MAP["pi"])
    data = json.loads((fake_home / ".pi" / "agent" / "mcp.json").read_text(encoding="utf-8"))
    assert "CTX_REPO" not in data["mcpServers"]["scubiee"]["env"]


def test_install_windsurf_continue_zed_global_omit_workspace_token(fake_home: Path) -> None:
    """Global MCP launches Scubiee only — no folder tokens, no absolute pin."""
    install_tool(TOOL_MAP["windsurf"])
    windsurf = json.loads(
        (fake_home / ".codeium" / "windsurf" / "mcp_config.json").read_text(encoding="utf-8")
    )
    wenv = windsurf["mcpServers"]["scubiee"]["env"]
    assert "CTX_REPO" not in wenv
    assert "WORKSPACE_FOLDER" not in wenv

    install_tool(TOOL_MAP["continue"])
    cont = (fake_home / ".continue" / "config.yaml").read_text(encoding="utf-8")
    assert "${workspaceFolder}" not in cont
    assert "CTX_REPO:" not in cont

    install_tool(TOOL_MAP["zed"])
    zed_path = resolve_mcp_user_path(TOOL_MAP["zed"])
    assert zed_path is not None and zed_path.is_file()
    zed = json.loads(zed_path.read_text(encoding="utf-8"))
    zenv = zed["context_servers"]["scubiee"]["env"]
    assert "CTX_REPO" not in zenv
    assert "WORKSPACE_FOLDER" not in zenv


def test_uninstall_global(fake_home: Path) -> None:
    install_tool(TOOL_MAP["opencode"])
    install_tool(TOOL_MAP["codex"])
    assert uninstall_tool(TOOL_MAP["opencode"])["mcp_removed"]
    data = json.loads(
        (fake_home / ".config" / "opencode" / "opencode.json").read_text(encoding="utf-8")
    )
    assert "scubiee" not in data.get("mcp", {})
    assert uninstall_tool(TOOL_MAP["codex"])["mcp_removed"]
    assert "[mcp_servers.scubiee]" not in (
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


def _mock_os(monkeypatch: pytest.MonkeyPatch, os_name: str) -> None:
    """Force tool_registry path tokens onto Darwin / Windows / Linux."""
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
    """Copilot/Cline/Roo resolve under Library (Mac) vs AppData (Win) vs .config (Linux)."""
    _mock_os(monkeypatch, os_name)
    vscode_user = fake_home / vscode_user_rel

    copilot = resolve_mcp_user_paths(TOOL_MAP["copilot"])
    assert copilot[0] == vscode_user / "mcp.json"
    assert copilot[1] == fake_home / ".copilot" / "mcp-config.json"

    cline = resolve_mcp_user_paths(TOOL_MAP["cline"])
    assert cline[0] == (
        vscode_user
        / "globalStorage"
        / "saoudrizwan.claude-dev"
        / "settings"
        / "cline_mcp_settings.json"
    )
    assert cline[1] == (
        fake_home / ".cline" / "data" / "settings" / "cline_mcp_settings.json"
    )

    roo = resolve_mcp_user_paths(TOOL_MAP["roo-code"])
    assert roo == [
        vscode_user
        / "globalStorage"
        / "rooveterinaryinc.roo-cline"
        / "settings"
        / "mcp_settings.json"
    ]


@pytest.mark.parametrize(
    ("os_name", "zed_rel"),
    [
        ("Darwin", Path(".config") / "zed" / "settings.json"),
        ("Linux", Path(".config") / "zed" / "settings.json"),
        ("Windows", Path("AppData") / "Roaming" / "Zed" / "settings.json"),
    ],
)
def test_zed_global_mcp_path_respects_os(
    fake_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    os_name: str,
    zed_rel: Path,
) -> None:
    _mock_os(monkeypatch, os_name)
    assert resolve_mcp_user_path(TOOL_MAP["zed"]) == fake_home / zed_rel


@pytest.mark.parametrize("os_name", ["Darwin", "Windows", "Linux"])
def test_install_copilot_writes_os_specific_vscode_mcp(
    fake_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    os_name: str,
) -> None:
    """connect --copilot must create the VS Code user mcp.json for the mocked OS."""
    _mock_os(monkeypatch, os_name)
    workspace = _git_repo(tmp_path / "ws")
    report = install_tool(TOOL_MAP["copilot"], repo=workspace)
    assert report["ok"]

    vscode_path = resolve_mcp_user_path(TOOL_MAP["copilot"])
    assert vscode_path is not None
    assert vscode_path.is_file()
    if os_name == "Darwin":
        assert "Library/Application Support/Code/User" in vscode_path.as_posix()
    elif os_name == "Windows":
        assert "AppData/Roaming/Code/User" in vscode_path.as_posix()
    else:
        assert ".config/Code/User" in vscode_path.as_posix()

    data = json.loads(vscode_path.read_text(encoding="utf-8"))
    assert data["servers"]["scubiee"]["type"] == "stdio"
    assert "CTX_REPO" not in data["servers"]["scubiee"]["env"]
