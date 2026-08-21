"""MCP repo resolution — must not default to user home when daemon has a bind."""

from __future__ import annotations

from pathlib import Path

from pipeline import mcp_locate


def test_default_repo_uses_ctx_repo_env(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "app"
    repo.mkdir()
    monkeypatch.setenv("CTX_REPO", str(repo))
    monkeypatch.delenv("CONTEXT_ENGINE_REPO", raising=False)
    assert mcp_locate._default_repo() == repo.resolve()


def test_default_repo_does_not_use_daemon_bound_repo_without_workspace_identity(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("CTX_REPO", raising=False)
    monkeypatch.delenv("CONTEXT_ENGINE_REPO", raising=False)
    monkeypatch.chdir(tmp_path)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("repo resolution must not consult daemon health")

    monkeypatch.setattr("pipeline.client.EngineClient", FakeClient)
    assert mcp_locate._default_repo() == tmp_path.resolve()


def test_write_cursor_mcp_drops_user_duplicate(tmp_path: Path, monkeypatch) -> None:
    from pipeline.mcp_install import write_cursor_mcp

    project_root = tmp_path / "proj"
    project_root.mkdir()
    user_home = tmp_path / "home"
    user_home.mkdir()
    user_mcp = user_home / ".cursor" / "mcp.json"
    user_mcp.parent.mkdir(parents=True)
    user_mcp.write_text(
        '{"mcpServers": {"context-engine": {"command": "python", "args": []}}}\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(project_root)
    monkeypatch.setattr("pipeline.mcp_install.Path.home", lambda: user_home)

    write_cursor_mcp(project_root)

    data = __import__("json").loads(user_mcp.read_text(encoding="utf-8"))
    assert "context-engine" not in (data.get("mcpServers") or {})
    project_mcp = project_root / ".cursor" / "mcp.json"
    project = __import__("json").loads(project_mcp.read_text(encoding="utf-8"))
    env = project["mcpServers"]["context-engine"]["env"]
    assert "CTX_REPO" in env


def test_write_kiro_mcp_writes_workspace_entry_and_neutral_global(
    tmp_path: Path, monkeypatch
) -> None:
    from pipeline.mcp_install import write_kiro_mcp

    project_root = tmp_path / "workspace"
    project_root.mkdir()
    user_home = tmp_path / "home"
    user_home.mkdir()
    monkeypatch.chdir(project_root)
    monkeypatch.setattr("pipeline.mcp_install.Path.home", lambda: user_home)

    paths = write_kiro_mcp(project_root)

    user = __import__("json").loads(Path(paths["user"]).read_text(encoding="utf-8"))
    project = __import__("json").loads(Path(paths["project"]).read_text(encoding="utf-8"))
    user_env = user["mcpServers"]["context-engine"]["env"]
    project_env = project["mcpServers"]["context-engine"]["env"]

    assert "CTX_REPO" not in user_env
    assert project_env["CTX_REPO"] == str(project_root.resolve()).replace("\\", "/")
    assert Path(paths["project"]) == project_root / ".kiro" / "settings" / "mcp.json"


def test_kiro_workspace_entry_routes_from_an_unrelated_process_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    from pipeline import mcp_locate
    from pipeline.mcp_install import write_kiro_mcp

    project_root = tmp_path / "indexed-workspace"
    unrelated = tmp_path / "kiro-process-cwd"
    project_root.mkdir()
    unrelated.mkdir()
    user_home = tmp_path / "home"
    user_home.mkdir()
    monkeypatch.setattr("pipeline.mcp_install.Path.home", lambda: user_home)
    paths = write_kiro_mcp(project_root)
    project = __import__("json").loads(Path(paths["project"]).read_text(encoding="utf-8"))
    configured_repo = project["mcpServers"]["context-engine"]["env"]["CTX_REPO"]

    monkeypatch.chdir(unrelated)
    for key in (
        "CONTEXT_ENGINE_REPO",
        "CURSOR_PROJECT_DIR",
        "CURSOR_WORKSPACE",
        "VSCODE_CWD",
        "WORKSPACE_FOLDER",
        "INIT_CWD",
    ):
        monkeypatch.delenv(key, raising=False)
    # This is the environment Kiro supplies when it launches the workspace
    # scoped server entry; cwd alone must not decide the repository.
    monkeypatch.setenv("CTX_REPO", configured_repo)

    assert mcp_locate._default_repo() == project_root.resolve()
