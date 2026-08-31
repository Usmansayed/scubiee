"""Installed-package MCP entry must not depend on a git checkout."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.mcp_install import server_entry, merge_mcp_json, write_cursor_mcp

from conftest import write_machine_setup


def test_server_entry_uses_module_invocation_without_source_pythonpath(
    tmp_path: Path, monkeypatch
) -> None:
    # Force module fallback so the assertion is stable whether or not scubiee-mcp
    # is on PATH in the developer environment.
    monkeypatch.setattr("shutil.which", lambda _name: None)
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
    assert "CTX_REPO" not in data["mcpServers"]["scubiee"]["env"]


def test_write_cursor_mcp_writes_project_and_user(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "app"
    project_root.mkdir()
    home = tmp_path / "home"
    user_mcp = home / ".cursor" / "mcp.json"
    user_mcp.parent.mkdir(parents=True, exist_ok=True)
    user_mcp.write_text(
        json.dumps({"mcpServers": {"scubiee": {"env": {}}}}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(project_root)
    monkeypatch.setattr(
        "pipeline.mcp_install.Path.home",
        lambda *_args, **_kwargs: home,
    )
    paths = write_cursor_mcp(project_root)
    project = json.loads(Path(paths["project"]).read_text(encoding="utf-8"))
    assert project["mcpServers"]["scubiee"]["env"]["CTX_REPO"]
    user = json.loads(user_mcp.read_text(encoding="utf-8"))
    assert "scubiee" not in user.get("mcpServers", {})


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
    assert "scubiee-mcp-bridge" in py["project"]["scripts"]
    assert npm["bin"]["scubiee"]
    assert "mcp" in str(py["project"]["dependencies"]).lower() or any(
        "mcp" in dep for dep in py["project"]["dependencies"]
    )


def test_kiro_connect_without_enrolled_repo_fans_out_zero(
    tmp_path: Path, monkeypatch
) -> None:
    from pipeline.rules_installer import install_tools

    project_root = tmp_path / "workspace"
    project_root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    ce_home = tmp_path / "ce-home"
    ce_home.mkdir()
    write_machine_setup(ce_home)
    monkeypatch.chdir(project_root)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("CTX_HOME", str(ce_home))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    reports = install_tools(["kiro"])

    assert reports[0]["ok"] is True
    assert reports[0]["scope"] == "project-local"
    assert reports[0]["project_fan_out"]["repos"] == 0
    assert not (home / ".kiro" / "settings" / "mcp.json").exists()
    assert not (project_root / ".kiro").exists()


def test_kiro_connect_fans_out_to_enrolled_git_repo(
    tmp_path: Path, monkeypatch
) -> None:
    from pipeline.rules_installer import install_tools

    project_root = tmp_path / "workspace"
    project_root.mkdir()
    (project_root / ".git").mkdir()
    ce = project_root / ".scubiee"
    ce.mkdir()
    pid = "ce_kiro_pkg1234567890abcdef"
    (ce / "id.json").write_text(json.dumps({"project_id": pid}), encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    ce_home = tmp_path / "ce-home"
    ce_home.mkdir()
    write_machine_setup(ce_home)
    monkeypatch.chdir(project_root)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("CTX_HOME", str(ce_home))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    from pipeline.project_id import save_registry

    save_registry(
        {
            "projects": {
                pid: {
                    "managed": True,
                    "root": str(project_root.resolve()),
                    "paths": [str(project_root.resolve())],
                }
            }
        }
    )

    reports = install_tools(["kiro"], repo=project_root)

    assert reports[0]["ok"] is True
    assert reports[0]["project_fan_out"]["repos"] == 1
    assert (project_root / ".kiro" / "settings" / "mcp.json").is_file()
    assert not (home / ".kiro" / "settings" / "mcp.json").exists()


def test_kiro_rules_cli_global_only_dry_run(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    from pipeline.__main__ import main

    target = tmp_path / "workspace"
    target.mkdir()
    (target / ".git").mkdir()
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)

    assert main(
        ["connect", "--kiro", "--repo", str(target), "--dry-run"]
    ) == 0

    report = json.loads(capsys.readouterr().out)
    assert report[0]["scope"] == "project-local"
    assert report[0].get("project_fan_out")


def test_uninstall_removes_mcp_entry_and_rule_file(tmp_path: Path, monkeypatch) -> None:
    """scubiee disconnect reverses scubiee connect for a JSON+md tool."""
    from pipeline.rules_installer import install_tool, uninstall_tool
    from pipeline.tool_registry import TOOL_MAP

    tool = TOOL_MAP["kiro"]
    workspace = tmp_path / "project"
    workspace.mkdir()
    (workspace / ".git").mkdir()
    ce = workspace / ".scubiee"
    ce.mkdir()
    pid = "ce_uninst_kiro1234567890abcd"
    (ce / "id.json").write_text(json.dumps({"project_id": pid}), encoding="utf-8")

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    ce_home = tmp_path / "ce-home"
    ce_home.mkdir()
    write_machine_setup(ce_home)
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("CTX_HOME", str(ce_home))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    from pipeline.project_id import save_registry

    save_registry(
        {
            "projects": {
                pid: {
                    "managed": True,
                    "root": str(workspace.resolve()),
                    "paths": [str(workspace.resolve())],
                }
            }
        }
    )

    install_tool(tool, repo=workspace)
    project_mcp = workspace / ".kiro" / "settings" / "mcp.json"
    assert project_mcp.is_file()

    report = uninstall_tool(tool, repo=workspace, all_workspaces=False)
    assert report["ok"] is True
    assert report["mcp_removed"] is True
    assert report.get("project_surface", {}).get("mcp_removed") is True
    assert not project_mcp.is_file()


def test_uninstall_removes_append_md_section(tmp_path: Path, monkeypatch) -> None:
    """Uninstall strips legacy CE sections from append-md rule files."""
    from pipeline.branding import MARKER_END, MARKER_START
    from pipeline.rules_installer import uninstall_tool
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

    rule_path = fake_home / ".claude" / "CLAUDE.md"
    rule_path.parent.mkdir(parents=True)
    rule_path.write_text(
        "# My Project\n\nSome instructions here.\n\n"
        f"{MARKER_START}\n**GATE 1:ce_legacy** — legacy rule\n{MARKER_END}\n",
        encoding="utf-8",
    )

    report = uninstall_tool(tool, repo=workspace)
    assert report["ok"] is True
    assert report["rule_removed"] is True
    remaining = rule_path.read_text(encoding="utf-8")
    assert MARKER_START not in remaining
    assert "# My Project" in remaining
    assert "Some instructions here." in remaining


def test_uninstall_dry_run_does_not_modify(tmp_path: Path, monkeypatch) -> None:
    """--dry-run reports what would be removed without changing files."""
    from pipeline.rules_installer import install_tool, uninstall_tool
    from pipeline.tool_registry import TOOL_MAP

    tool = TOOL_MAP["kiro"]
    workspace = tmp_path / "project"
    workspace.mkdir()
    (workspace / ".git").mkdir()
    ce = workspace / ".scubiee"
    ce.mkdir()
    pid = "ce_dryrun_kiro1234567890abcd"
    (ce / "id.json").write_text(json.dumps({"project_id": pid}), encoding="utf-8")
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    ce_home = tmp_path / "ce-home"
    ce_home.mkdir()
    write_machine_setup(ce_home)
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("CTX_HOME", str(ce_home))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    from pipeline.project_id import save_registry

    save_registry(
        {
            "projects": {
                pid: {
                    "managed": True,
                    "root": str(workspace.resolve()),
                    "paths": [str(workspace.resolve())],
                }
            }
        }
    )

    install_tool(tool, repo=workspace)
    project_mcp = workspace / ".kiro" / "settings" / "mcp.json"
    assert project_mcp.is_file()

    report = uninstall_tool(tool, repo=workspace, dry_run=True)
    assert report["dry_run"] is True
    assert report.get("would_remove_legacy_global") is not None

    assert "scubiee" in json.loads(project_mcp.read_text(encoding="utf-8")).get("mcpServers", {})


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
