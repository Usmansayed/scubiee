"""Installed-package MCP entry must not depend on a git checkout."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.mcp_install import server_entry, merge_mcp_json, write_cursor_mcp


def test_server_entry_uses_module_invocation_without_source_pythonpath(tmp_path: Path) -> None:
    entry = server_entry(tmp_path)
    assert entry["args"] == ["-u", "-m", "pipeline.mcp_locate"]
    env = entry["env"]
    assert env["CTX_MCP_SURFACE"] == "phase"
    assert "PYTHONPATH" not in env
    assert env["CTX_REPO"] == str(tmp_path.resolve()).replace("\\", "/")


def test_interpreter_preserves_venv_shim_not_cellar_realpath(monkeypatch, tmp_path: Path) -> None:
    """macOS venv python is a symlink into Homebrew; resolving it breaks imports."""
    import sys

    from pipeline import mcp_install

    venv_root = tmp_path / "scubiee"
    bin_dir = venv_root / "bin"
    bin_dir.mkdir(parents=True)
    shim = bin_dir / "python"
    shim.write_text("#!/bin/sh\n", encoding="utf-8")
    shim.chmod(0o755)
    monkeypatch.setattr(sys, "prefix", str(venv_root))
    monkeypatch.setattr(sys, "executable", str(shim))
    monkeypatch.delenv("CTX_PYTHON", raising=False)
    got = mcp_install.interpreter()
    assert got == str(shim).replace("\\", "/")
    assert "Cellar" not in got


def test_interpreter_honors_ctx_python_override(monkeypatch, tmp_path: Path) -> None:
    from pipeline import mcp_install

    custom = tmp_path / "custom-python"
    custom.write_text("", encoding="utf-8")
    monkeypatch.setenv("CTX_PYTHON", str(custom))
    assert mcp_install.interpreter() == str(custom).replace("\\", "/")


def test_user_level_entry_does_not_pin_a_repo(tmp_path: Path) -> None:
    entry = server_entry(None)
    assert "CTX_REPO" not in entry["env"]
    path = tmp_path / "mcp.json"
    merge_mcp_json(path, repo=None)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "CTX_REPO" not in data["mcpServers"]["context-engine"]["env"]


def test_write_cursor_mcp_writes_project_and_user(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "app"
    project_root.mkdir()
    home = tmp_path / "home"
    user_mcp = home / ".cursor" / "mcp.json"
    user_mcp.parent.mkdir(parents=True, exist_ok=True)
    user_mcp.write_text(
        json.dumps({"mcpServers": {"context-engine": {"env": {}}}}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(project_root)
    monkeypatch.setattr(
        "pipeline.mcp_install.Path.home",
        lambda *_args, **_kwargs: home,
    )
    paths = write_cursor_mcp(project_root)
    project = json.loads(Path(paths["project"]).read_text(encoding="utf-8"))
    assert project["mcpServers"]["context-engine"]["env"]["CTX_REPO"]
    user = json.loads(user_mcp.read_text(encoding="utf-8"))
    assert "context-engine" not in user.get("mcpServers", {})


def test_pyproject_and_npm_versions_match() -> None:
    import tomllib

    py = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    npm = json.loads(Path("npm/package.json").read_text(encoding="utf-8"))
    assert py["project"]["name"] == "scubiee"
    assert npm["name"] == "scubiee"
    assert py["project"]["version"] == npm["version"]
    deps = "\n".join(py["project"]["dependencies"])
    assert "mlx>=0.22" in deps
    assert "sys_platform == 'darwin'" in deps
    extras = py["project"]["optional-dependencies"]
    assert "macos" in extras
    assert "mlx" in extras
    assert "scubiee" in py["project"]["scripts"]
    assert "scubiee-mcp" in py["project"]["scripts"]
    assert npm["bin"]["scubiee"]
    assert "mcp" in str(py["project"]["dependencies"]).lower() or any(
        "mcp" in dep for dep in py["project"]["dependencies"]
    )


def test_kiro_rules_install_writes_global_entry_without_repo_pin(
    tmp_path: Path, monkeypatch
) -> None:
    from pipeline.rules_installer import install_tools

    project_root = tmp_path / "workspace"
    project_root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.chdir(project_root)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    reports = install_tools(["kiro"], repo=project_root)

    assert reports[0]["ok"] is True
    assert reports[0].get("repo_ignored") is True
    user = json.loads(
        (home / ".kiro" / "settings" / "mcp.json").read_text(encoding="utf-8")
    )
    assert "CTX_REPO" not in user["mcpServers"]["context-engine"]["env"]
    assert not (project_root / ".kiro").exists()
    assert reports[0]["mcp_path"] == str(home / ".kiro" / "settings" / "mcp.json")


def test_kiro_rules_cli_accepts_repo_but_ignores_for_global(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    from pipeline.__main__ import main

    target = tmp_path / "workspace"
    unrelated = tmp_path / "unrelated"
    target.mkdir()
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)

    assert main(
        ["connect", "--kiro", "--repo", str(target), "--dry-run"]
    ) == 0

    report = json.loads(capsys.readouterr().out)
    assert report[0]["scope"] == "global"
    assert report[0].get("repo_ignored") is True
    assert "would_write_workspace_mcp" not in report[0]
    assert report[0]["would_write_mcp"].endswith(
        str(Path(".kiro") / "settings" / "mcp.json")
    )


def test_uninstall_removes_mcp_entry_and_rule_file(tmp_path: Path, monkeypatch) -> None:
    """scubiee disconnect reverses scubiee connect for a JSON+md tool."""
    from pipeline.rules_installer import install_tool, uninstall_tool
    from pipeline.tool_registry import TOOL_MAP

    tool = TOOL_MAP["kiro"]
    workspace = tmp_path / "project"
    workspace.mkdir()

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    install_tool(tool, repo=workspace)
    user_mcp = fake_home / ".kiro" / "settings" / "mcp.json"
    rule_file = fake_home / ".kiro" / "steering" / "context-engine.md"
    assert user_mcp.is_file()
    assert rule_file.is_file()
    assert "context-engine" in json.loads(user_mcp.read_text(encoding="utf-8")).get("mcpServers", {})
    assert not (workspace / ".kiro").exists()

    report = uninstall_tool(tool, repo=workspace)
    assert report["ok"] is True
    assert report["mcp_removed"] is True
    assert report["rule_removed"] is True

    assert "context-engine" not in json.loads(user_mcp.read_text(encoding="utf-8")).get("mcpServers", {})
    assert not rule_file.is_file()


def test_uninstall_removes_append_md_section(tmp_path: Path, monkeypatch) -> None:
    """Uninstall strips the CE section from append-md rule files without deleting other content."""
    from pipeline.rules_installer import install_tool, uninstall_tool
    from pipeline.tool_registry import TOOL_MAP

    tool = TOOL_MAP["claude-code"]
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    # Pre-existing content in the rule file
    rule_path = fake_home / ".claude" / "CLAUDE.md"
    rule_path.parent.mkdir(parents=True)
    rule_path.write_text("# My Project\n\nSome instructions here.\n", encoding="utf-8")

    # Install appends section
    install_tool(tool, repo=workspace)
    content_after_install = rule_path.read_text(encoding="utf-8")
    assert "<!-- context-engine:start -->" in content_after_install
    assert "# My Project" in content_after_install

    # Uninstall strips only the CE section
    report = uninstall_tool(tool, repo=workspace)
    assert report["ok"] is True
    assert report["rule_removed"] is True
    remaining = rule_path.read_text(encoding="utf-8")
    assert "<!-- context-engine:start -->" not in remaining
    assert "# My Project" in remaining
    assert "Some instructions here." in remaining


def test_uninstall_dry_run_does_not_modify(tmp_path: Path, monkeypatch) -> None:
    """--dry-run reports what would be removed without changing files."""
    from pipeline.rules_installer import install_tool, uninstall_tool
    from pipeline.tool_registry import TOOL_MAP

    tool = TOOL_MAP["kiro"]
    workspace = tmp_path / "project"
    workspace.mkdir()
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    install_tool(tool, repo=workspace)
    user_mcp = fake_home / ".kiro" / "settings" / "mcp.json"
    assert user_mcp.is_file()

    # Dry-run uninstall
    report = uninstall_tool(tool, repo=workspace, dry_run=True)
    assert report["dry_run"] is True
    assert "would_remove_mcp" in report

    # Files are still intact
    assert "context-engine" in json.loads(user_mcp.read_text(encoding="utf-8")).get("mcpServers", {})


def test_uninstall_cli_entry_point(tmp_path: Path, monkeypatch, capsys) -> None:
    """scubiee disconnect --kiro --dry-run works through the CLI entry."""
    from pipeline.__main__ import main

    workspace = tmp_path / "project"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    assert main(["disconnect", "--kiro", "--dry-run"]) == 0
    out = capsys.readouterr().out
    report = json.loads(out)
    assert report[0]["slug"] == "kiro"
    assert report[0]["dry_run"] is True
