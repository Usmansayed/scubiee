"""MCP repo resolution — enrolled identity beats stale CTX_REPO pins."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
    (live / ".scubiee").mkdir()
    (live / ".scubiee" / "id.json").write_text(
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
    (opened / ".scubiee").mkdir()
    (opened / ".scubiee" / "id.json").write_text(
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
    (opened / ".scubiee").mkdir()
    (opened / ".scubiee" / "id.json").write_text(
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
    (live / ".scubiee").mkdir()
    (live / ".scubiee" / "id.json").write_text(
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
    (opened / ".scubiee").mkdir()
    (opened / ".scubiee" / "id.json").write_text(
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
    (moved / ".scubiee").mkdir()
    (moved / ".scubiee" / "id.json").write_text(
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
    fields = mcp_locate._managed_signal_fields(just_checked=True)
    assert fields["managed"] is False
    assert fields["should_retry_status"] is False
    assert fields["should_use_mcp"] is False
    assert fields["status_ttl_s"] == 300


def test_gate_line_unmanaged(tmp_path: Path, monkeypatch) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    monkeypatch.delenv("CTX_REPO", raising=False)
    assert mcp_locate._gate_line(just_checked=True) == "0"


def test_gate_line_managed_enrolled(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "app"
    repo.mkdir()
    sc = repo / ".scubiee"
    sc.mkdir()
    pid = "ce_gate_test1234567890abcdef"
    (sc / "id.json").write_text(
        json.dumps({"version": 1, "project_id": pid}),
        encoding="utf-8",
    )
    reg = tmp_path / "registry.json"
    reg.write_text(
        json.dumps(
            {
                "projects": {
                    pid: {
                        "managed": True,
                        "paths": [str(repo).replace("\\", "/")],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)
    monkeypatch.setenv("CTX_REPO", str(repo))
    monkeypatch.setattr("pipeline.project_id.registry_path", lambda: reg)
    line = mcp_locate._gate_line(just_checked=True)
    assert line == f"1:{pid}"


def test_status_detail_gate_skips_daemon(tmp_path: Path, monkeypatch) -> None:
    pytest.importorskip("mcp")
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    monkeypatch.delenv("CTX_REPO", raising=False)

    class Boom:
        def __init__(self, *a, **k):
            raise AssertionError("status(detail=gate) must not call daemon")

    monkeypatch.setattr("pipeline.daemon.ensure_daemon", Boom)
    monkeypatch.setattr("pipeline.client.EngineClient", Boom)

    from pipeline.mcp_locate import create_mcp

    mcp = create_mcp(name="test-gate-status")
    fn = mcp._tool_manager._tools["status"].fn
    assert fn(detail="gate") == "0"


def test_should_retry_status_after_ttl(tmp_path: Path, monkeypatch) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    monkeypatch.delenv("CTX_REPO", raising=False)
    monkeypatch.delenv("CTX_PROJECT_ID", raising=False)
    monkeypatch.setenv("CTX_STATUS_TTL_S", "120")
    ticks = iter([1_000.0, 1_120.0])
    monkeypatch.setattr(mcp_locate.time, "monotonic", lambda: next(ticks))
    fresh = mcp_locate._managed_signal_fields(just_checked=True)
    assert fresh["should_retry_status"] is False
    assert fresh["status_age_s"] == 0
    later = mcp_locate._managed_signal_fields(just_checked=False)
    assert later["should_retry_status"] is True
    assert later["status_ttl_s"] == 120


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
        '{"mcpServers": {"scubiee": {"command": "python", "args": []}}}\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(project_root)
    monkeypatch.setattr("pipeline.mcp_install.Path.home", lambda: user_home)

    write_cursor_mcp(project_root)

    data = __import__("json").loads(user_mcp.read_text(encoding="utf-8"))
    assert "scubiee" not in (data.get("mcpServers") or {})
    project_mcp = project_root / ".cursor" / "mcp.json"
    project = __import__("json").loads(project_mcp.read_text(encoding="utf-8"))
    env = project["mcpServers"]["scubiee"]["env"]
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
    user_env = user["mcpServers"]["scubiee"]["env"]
    project_env = project["mcpServers"]["scubiee"]["env"]

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
    configured_repo = project["mcpServers"]["scubiee"]["env"]["CTX_REPO"]

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
    (repo / ".scubiee").mkdir()
    (repo / ".scubiee" / "id.json").write_text(
        json.dumps({"project_id": "ce_pin"}), encoding="utf-8"
    )
    entry = server_entry(repo)
    assert "repo" in entry["env"]["CTX_REPO"]
    assert entry["env"]["CTX_PROJECT_ID"] == "ce_pin"


_CLEAR_IDE = (
    "CURSOR_PROJECT_DIR",
    "CURSOR_WORKSPACE",
    "CURSOR_CWD",
    "WORKSPACE_FOLDER_PATHS",
    "WORKSPACE_FOLDER",
    "CLAUDE_PROJECT_DIR",
    "CODEX_WORKSPACE_ROOT",
    "COPILOT_WORKSPACE_FOLDER",
    "COPILOT_WORKSPACE",
    "VSCODE_WORKSPACE_FOLDER",
    "VSCODE_CWD",
    "INIT_CWD",
    "OPENCODE_DEFAULT_PROJECT",
    "CONTEXT_ENGINE_REPO",
)


def _enroll_scubiee(repo: Path, project_id: str) -> None:
    ident = repo / ".scubiee"
    ident.mkdir(parents=True, exist_ok=True)
    (ident / "id.json").write_text(
        json.dumps({"project_id": project_id}), encoding="utf-8"
    )


def test_unenrolled_live_git_workspace_beats_enrolled_pin(
    tmp_path: Path, monkeypatch
) -> None:
    """Sidebar/other-folder: live .git workspace must not inherit the pin."""
    engine = tmp_path / "new-context-engine"
    engine.mkdir()
    _enroll_scubiee(engine, "ce_engine")
    (engine / ".git").mkdir()
    other = tmp_path / "web"
    other.mkdir()
    (other / ".git").mkdir()
    spawn = tmp_path / "mcp-cwd"
    spawn.mkdir()
    monkeypatch.chdir(spawn)
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    from pipeline.project_id import save_registry

    save_registry(
        {
            "projects": {
                "ce_engine": {
                    "managed": True,
                    "root": str(engine.resolve()),
                    "paths": [str(engine.resolve())],
                }
            }
        }
    )
    monkeypatch.setenv("CTX_REPO", str(engine))
    monkeypatch.setenv("CTX_PROJECT_ID", "ce_engine")
    monkeypatch.setenv("CURSOR_PROJECT_DIR", str(other))
    for key in _CLEAR_IDE:
        if key != "CURSOR_PROJECT_DIR":
            monkeypatch.delenv(key, raising=False)

    assert mcp_locate._default_repo() == other.resolve()
    assert mcp_locate._is_repo_managed() is False


def test_request_root_unenrolled_beats_pin(tmp_path: Path, monkeypatch) -> None:
    engine = tmp_path / "engine"
    engine.mkdir()
    _enroll_scubiee(engine, "ce_engine")
    (engine / ".git").mkdir()
    other = tmp_path / "neural-dust-cloud"
    other.mkdir()
    (other / ".git").mkdir()
    spawn = tmp_path / "cwd"
    spawn.mkdir()
    monkeypatch.chdir(spawn)
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    from pipeline.project_id import save_registry

    save_registry(
        {
            "projects": {
                "ce_engine": {
                    "managed": True,
                    "root": str(engine.resolve()),
                    "paths": [str(engine.resolve())],
                }
            }
        }
    )
    monkeypatch.setenv("CTX_REPO", str(engine))
    monkeypatch.setenv("CTX_PROJECT_ID", "ce_engine")
    for key in _CLEAR_IDE:
        monkeypatch.delenv(key, raising=False)

    with mcp_locate._bind_request_repo(root=str(other)):
        assert mcp_locate._default_repo() == other.resolve()
        assert mcp_locate._is_repo_managed() is False


def test_request_root_walks_to_enrolled_id(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "app"
    nested = repo / "packages" / "pkg"
    nested.mkdir(parents=True)
    _enroll_scubiee(repo, "ce_app")
    spawn = tmp_path / "cwd"
    spawn.mkdir()
    monkeypatch.chdir(spawn)
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    from pipeline.project_id import save_registry

    save_registry(
        {
            "projects": {
                "ce_app": {
                    "managed": True,
                    "root": str(repo.resolve()),
                    "paths": [str(repo.resolve())],
                }
            }
        }
    )
    monkeypatch.setenv("CTX_REPO", str(tmp_path / "other-pin"))
    (tmp_path / "other-pin").mkdir()
    monkeypatch.delenv("CTX_PROJECT_ID", raising=False)
    for key in _CLEAR_IDE:
        monkeypatch.delenv(key, raising=False)

    with mcp_locate._bind_request_repo(root=str(nested)):
        assert mcp_locate._default_repo() == repo.resolve()
        assert mcp_locate._is_repo_managed() is True


def test_blind_spawn_keeps_project_id_pin(tmp_path: Path, monkeypatch) -> None:
    """Mac Cursor: cwd is junk/home, no live workspace → pin still works."""
    engine = tmp_path / "engine"
    engine.mkdir()
    _enroll_scubiee(engine, "ce_engine")
    spawn = tmp_path / "cwd"
    spawn.mkdir()
    monkeypatch.chdir(spawn)
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    from pipeline.project_id import save_registry

    save_registry(
        {
            "projects": {
                "ce_engine": {
                    "managed": True,
                    "root": str(engine.resolve()),
                    "paths": [str(engine.resolve())],
                }
            }
        }
    )
    monkeypatch.setenv("CTX_PROJECT_ID", "ce_engine")
    monkeypatch.delenv("CTX_REPO", raising=False)
    for key in _CLEAR_IDE:
        monkeypatch.delenv(key, raising=False)

    assert mcp_locate._default_repo() == engine.resolve()
    assert mcp_locate._is_repo_managed() is True
