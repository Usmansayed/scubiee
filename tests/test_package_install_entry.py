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
    assert "ctx" in py["project"]["scripts"]
    assert "scubiee" in py["project"]["scripts"]
    assert npm["bin"]["ctx"]
    assert npm["bin"]["scubiee"]
    assert "mcp" in str(py["project"]["dependencies"]).lower() or any(
        "mcp" in dep for dep in py["project"]["dependencies"]
    )
