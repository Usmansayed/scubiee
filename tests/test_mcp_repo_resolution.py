"""MCP repo resolution — enrolled identity beats stale CTX_REPO pins."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline import mcp_locate


def test_default_repo_uses_ctx_repo_env(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "app"
    repo.mkdir()
    unrelated = tmp_path / "cwd"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    monkeypatch.setenv("CTX_REPO", str(repo))
    monkeypatch.delenv("CONTEXT_ENGINE_REPO", raising=False)
    for key in (
        "CURSOR_PROJECT_DIR",
        "CTX_PROJECT_ID",
        "WORKSPACE_FOLDER",
        "CLAUDE_PROJECT_DIR",
        "CODEX_WORKSPACE_ROOT",
        "CURSOR_CWD",
    ):
        monkeypatch.delenv(key, raising=False)
    assert mcp_locate._default_repo() == repo.resolve()


def test_default_repo_ignores_unexpanded_workspace_folder_token(
    tmp_path: Path, monkeypatch
) -> None:
    """Hosts that don't expand ${workspaceFolder} must not poison resolution."""
    live = tmp_path / "live"
    live.mkdir()
    (live / ".context-engine").mkdir()
    (live / ".context-engine" / "id.json").write_text(
        json.dumps({"project_id": "ce_live"}), encoding="utf-8"
    )
    junk = tmp_path / "home"
    junk.mkdir()
    monkeypatch.chdir(live)
    monkeypatch.setenv("CTX_REPO", "${workspaceFolder}")
    monkeypatch.setenv("CURSOR_PROJECT_DIR", "${workspaceFolder}")
    monkeypatch.setenv("WORKSPACE_FOLDER", "${workspaceFolder}")
    monkeypatch.delenv("CTX_PROJECT_ID", raising=False)
    monkeypatch.delenv("CONTEXT_ENGINE_REPO", raising=False)
    for key in ("CLAUDE_PROJECT_DIR", "CODEX_WORKSPACE_ROOT", "CURSOR_CWD", "INIT_CWD"):
        monkeypatch.delenv(key, raising=False)
    assert mcp_locate._default_repo() == live.resolve()


def test_default_repo_prefers_workspace_folder_paths(
    tmp_path: Path, monkeypatch
) -> None:
    """Cursor injects WORKSPACE_FOLDER_PATHS; use first existing path."""
    opened = tmp_path / "cursor-ws"
    opened.mkdir()
    (opened / ".context-engine").mkdir()
    (opened / ".context-engine" / "id.json").write_text(
        json.dumps({"project_id": "ce_wfp"}), encoding="utf-8"
    )
    junk = tmp_path / "spawn-cwd"
    junk.mkdir()
    monkeypatch.chdir(junk)
    monkeypatch.setenv("WORKSPACE_FOLDER_PATHS", f"{opened},/nonexistent")
    monkeypatch.delenv("CTX_REPO", raising=False)
    monkeypatch.delenv("CTX_PROJECT_ID", raising=False)
    for key in (
        "CURSOR_PROJECT_DIR",
        "CURSOR_CWD",
        "WORKSPACE_FOLDER",
        "CLAUDE_PROJECT_DIR",
        "CODEX_WORKSPACE_ROOT",
        "INIT_CWD",
    ):
        monkeypatch.delenv(key, raising=False)
    assert mcp_locate._default_repo() == opened.resolve()


def test_default_repo_prefers_claude_project_dir(tmp_path: Path, monkeypatch) -> None:
    opened = tmp_path / "claude-ws"
    opened.mkdir()
    (opened / ".context-engine").mkdir()
    (opened / ".context-engine" / "id.json").write_text(
        json.dumps({"project_id": "ce_claude"}), encoding="utf-8"
    )
    junk = tmp_path / "spawn-cwd"
    junk.mkdir()
    monkeypatch.chdir(junk)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(opened))
    monkeypatch.delenv("CTX_REPO", raising=False)
    monkeypatch.delenv("CTX_PROJECT_ID", raising=False)
    for key in (
        "CURSOR_PROJECT_DIR",
        "CURSOR_CWD",
        "WORKSPACE_FOLDER",
        "CODEX_WORKSPACE_ROOT",
        "INIT_CWD",
        "WORKSPACE_FOLDER_PATHS",
    ):
        monkeypatch.delenv(key, raising=False)
    assert mcp_locate._default_repo() == opened.resolve()


def test_default_repo_prefers_codex_workspace_root(tmp_path: Path, monkeypatch) -> None:
    opened = tmp_path / "codex-ws"
    opened.mkdir()
    (opened / ".git").mkdir()
    junk = tmp_path / "spawn-cwd"
    junk.mkdir()
    monkeypatch.chdir(junk)
    monkeypatch.setenv("CODEX_WORKSPACE_ROOT", str(opened))
    monkeypatch.delenv("CTX_REPO", raising=False)
    monkeypatch.delenv("CTX_PROJECT_ID", raising=False)
    for key in (
        "CURSOR_PROJECT_DIR",
        "CURSOR_CWD",
        "CLAUDE_PROJECT_DIR",
        "WORKSPACE_FOLDER",
        "INIT_CWD",
    ):
        monkeypatch.delenv(key, raising=False)
    assert mcp_locate._default_repo() == opened.resolve()


def test_default_repo_ignores_missing_ctx_repo_pin(tmp_path: Path, monkeypatch) -> None:
    live = tmp_path / "live"
    live.mkdir()
    (live / ".context-engine").mkdir()
    (live / ".context-engine" / "id.json").write_text(
        json.dumps({"project_id": "ce_live"}), encoding="utf-8"
    )
    missing = tmp_path / "gone-old-path"
    monkeypatch.chdir(live)
    monkeypatch.setenv("CTX_REPO", str(missing))
    monkeypatch.delenv("CTX_PROJECT_ID", raising=False)
    for key in ("CURSOR_PROJECT_DIR", "WORKSPACE_FOLDER", "INIT_CWD"):
        monkeypatch.delenv(key, raising=False)
    assert mcp_locate._default_repo() == live.resolve()
    assert mcp_locate._ctx_repo_stale(missing.resolve()) is True


def test_default_repo_prefers_ide_enrolled_over_stale_pin(
    tmp_path: Path, monkeypatch
) -> None:
    opened = tmp_path / "opened"
    opened.mkdir()
    (opened / ".context-engine").mkdir()
    (opened / ".context-engine" / "id.json").write_text(
        json.dumps({"project_id": "ce_open"}), encoding="utf-8"
    )
    pinned = tmp_path / "old-pin"
    pinned.mkdir()
    (pinned / ".git").mkdir()
    junk = tmp_path / "ide-install"
    junk.mkdir()
    monkeypatch.chdir(junk)
    monkeypatch.setenv("CURSOR_PROJECT_DIR", str(opened))
    monkeypatch.setenv("CTX_REPO", str(pinned))
    monkeypatch.delenv("CTX_PROJECT_ID", raising=False)
    assert mcp_locate._default_repo() == opened.resolve()


def test_default_repo_resolves_ctx_project_id_from_registry(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    moved = tmp_path / "renamed-repo"
    moved.mkdir()
    (moved / ".context-engine").mkdir()
    (moved / ".context-engine" / "id.json").write_text(
        json.dumps({"project_id": "ce_moved"}), encoding="utf-8"
    )
    from pipeline.project_id import save_registry

    save_registry(
        {
            "projects": {
                "ce_moved": {
                    "managed": True,
                    "root": str(moved.resolve()),
                    "paths": [str(moved.resolve())],
                }
            }
        }
    )
    junk = tmp_path / "cwd"
    junk.mkdir()
    monkeypatch.chdir(junk)
    monkeypatch.delenv("CTX_REPO", raising=False)
    monkeypatch.setenv("CTX_PROJECT_ID", "ce_moved")
    for key in ("CURSOR_PROJECT_DIR", "WORKSPACE_FOLDER", "INIT_CWD"):
        monkeypatch.delenv(key, raising=False)
    assert mcp_locate._default_repo() == moved.resolve()


def test_managed_signal_fields_unmanaged(tmp_path: Path, monkeypatch) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    monkeypatch.delenv("CTX_REPO", raising=False)
    monkeypatch.delenv("CTX_PROJECT_ID", raising=False)
    for key in ("CURSOR_PROJECT_DIR", "WORKSPACE_FOLDER"):
        monkeypatch.delenv(key, raising=False)
    fields = mcp_locate._managed_signal_fields()
    assert fields["managed"] is False
    assert fields["should_retry_status"] is True
    assert fields["should_use_mcp"] is False


def test_default_repo_does_not_use_daemon_bound_repo_without_workspace_identity(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("CTX_REPO", raising=False)
    monkeypatch.delenv("CONTEXT_ENGINE_REPO", raising=False)
    monkeypatch.delenv("CTX_PROJECT_ID", raising=False)
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
        "CTX_PROJECT_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    # This is the environment Kiro supplies when it launches the workspace
    # scoped server entry; cwd alone must not decide the repository.
    monkeypatch.setenv("CTX_REPO", configured_repo)

    assert mcp_locate._default_repo() == project_root.resolve()


def test_server_entry_pins_project_id_when_enrolled(tmp_path: Path, monkeypatch) -> None:
    from pipeline.mcp_install import server_entry

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".context-engine").mkdir()
    (repo / ".context-engine" / "id.json").write_text(
        json.dumps({"project_id": "ce_pin"}), encoding="utf-8"
    )
    entry = server_entry(repo)
    assert "repo" in entry["env"]["CTX_REPO"]
    assert entry["env"]["CTX_PROJECT_ID"] == "ce_pin"
