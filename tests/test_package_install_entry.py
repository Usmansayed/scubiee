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
    assert "ctx" in py["project"]["scripts"]
    assert "scubiee" in py["project"]["scripts"]
    assert npm["bin"]["ctx"]
    assert npm["bin"]["scubiee"]
    assert "mcp" in str(py["project"]["dependencies"]).lower() or any(
        "mcp" in dep for dep in py["project"]["dependencies"]
    )
