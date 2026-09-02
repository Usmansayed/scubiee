"""Repository lifecycle and durable identity contracts."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from pipeline.project_id import (
    _norm_path,
    git_common_dir,
    id_file_path,
    load_registry,
    projects_root,
    resolve_project,
    write_id_file,
)
from pipeline.repo_lifecycle import (
    initialize_repo,
    list_managed_repos,
    managed_state,
    never_index_repo,
    pause_repo,
    rebuild_repo,
    remove_repo,
    resume_repo,
    sync_now_repo,
    activate_repo,
)


def test_status_unmanaged_returns_enrolled_false(
    ce_home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from argparse import Namespace

    from pipeline.__main__ import cmd_status

    repo = tmp_path / "fresh"
    repo.mkdir()
    code = cmd_status(Namespace(path=str(repo), url=None, json=True))
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["enrolled"] is False
    assert data["state"] == "unmanaged"
    assert "hint" in data


@pytest.fixture
def ce_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    return home


def test_repeat_initialize_reconciles_without_forced_rebuild(
    ce_home: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    usable = [False, True, True]
    stats = MagicMock(chunks=3)
    sync = MagicMock()
    sync.refreshed = True
    sync.strategy = "incremental"
    sync.to_dict.return_value = {"refreshed": True, "files": ["a.py"], "error": None}

    with patch(
        "pipeline.repo_lifecycle.index_is_usable", side_effect=lambda _store: usable.pop(0)
    ), patch("pipeline.indexer.index_repo", return_value=stats) as index_repo, patch(
        "pipeline.incremental.incremental_sync", return_value=sync
    ) as incremental_sync, patch(
        "pipeline.rules_installer.apply_connected_tools_to_repo",
        return_value={"ok": True},
    ):
        first = initialize_repo(repo)
        second = initialize_repo(repo)

    assert first["project_id"] == second["project_id"]
    assert first["indexed"] is True
    assert second["reconciled"] is True
    assert second["already_initialized"] is False
    index_repo.assert_called_once()
    assert index_repo.call_args.kwargs["force"] is False
    incremental_sync.assert_called_once()


def test_repeat_initialize_reports_already_indexed_when_unchanged(
    ce_home: Path, tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    usable = [False, True, True]
    stats = MagicMock(chunks=3)
    sync = MagicMock()
    sync.refreshed = False
    sync.strategy = "none"
    sync.to_dict.return_value = {"refreshed": False, "strategy": "none", "files": []}

    with patch(
        "pipeline.repo_lifecycle.index_is_usable", side_effect=lambda _store: usable.pop(0)
    ), patch("pipeline.indexer.index_repo", return_value=stats), patch(
        "pipeline.incremental.incremental_sync", return_value=sync
    ), patch(
        "pipeline.rules_installer.apply_connected_tools_to_repo",
        return_value={"ok": True},
    ):
        initialize_repo(repo)
        second = initialize_repo(repo)

    assert second["already_initialized"] is True
    assert second["reconciled"] is True


def test_repeat_initialize_restores_missing_id_json(
    ce_home: Path, tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    first = initialize_repo(repo, index=False)
    pid = first["project_id"]
    id_path = id_file_path(repo)
    assert id_path.is_file()
    id_path.unlink()

    second = initialize_repo(repo, index=False)
    assert second["project_id"] == pid
    assert id_file_path(repo).is_file()


def test_symlink_aliases_share_durable_project_identity(
    ce_home: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(repo, target_is_directory=True)
    except OSError as exc:
        if sys.platform != "win32":
            pytest.skip(f"symlinks unavailable: {exc}")
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(alias), str(repo)],
            check=True,
            capture_output=True,
        )

    direct = initialize_repo(repo, index=False)
    through_alias = initialize_repo(alias, index=False)

    assert direct["project_id"] == through_alias["project_id"]
    assert len(load_registry()["projects"]) == 1


def test_moved_repository_reuses_in_repo_id(ce_home: Path, tmp_path: Path) -> None:
    original = tmp_path / "original"
    original.mkdir()
    first = initialize_repo(original, index=False)
    moved = tmp_path / "moved"
    shutil.move(str(original), moved)

    second = initialize_repo(moved, index=False)

    assert second["project_id"] == first["project_id"]
    old_entry = load_registry()["projects"][first["project_id"]]
    assert old_entry["paths"] == [_norm_path(moved)]

    original.mkdir()
    replacement = initialize_repo(original, index=False)
    assert replacement["project_id"] != first["project_id"]


def test_reverse_order_vacated_path_does_not_inherit_moved_id(
    ce_home: Path, tmp_path: Path
) -> None:
    """Stale registry alias must not identify a new checkout before the move updates."""
    original = tmp_path / "original"
    original.mkdir()
    first = initialize_repo(original, index=False)
    moved = tmp_path / "moved"
    shutil.move(str(original), moved)

    # Vacated path is recreated before the moved checkout refreshes the registry.
    assert _norm_path(original) in load_registry()["projects"][first["project_id"]]["paths"]
    original.mkdir()
    from pipeline.project_id import find_id_by_path, resolve_project

    assert find_id_by_path(str(original.resolve())) is None
    replacement = resolve_project(original)
    assert replacement.project_id != first["project_id"]

    relocated = initialize_repo(moved, index=False)
    assert relocated["project_id"] == first["project_id"]


def test_empty_context_engine_dir_does_not_inherit_moved_id(
    ce_home: Path, tmp_path: Path
) -> None:
    """Empty .context-engine/ on a vacated path must not unlock a stale alias."""
    original = tmp_path / "original"
    original.mkdir()
    first = initialize_repo(original, index=False)
    moved = tmp_path / "moved"
    shutil.move(str(original), moved)

    original.mkdir()
    (original / ".context-engine").mkdir()
    from pipeline.project_id import find_id_by_path, resolve_project

    assert find_id_by_path(str(original.resolve())) is None
    replacement = resolve_project(original)
    assert replacement.project_id != first["project_id"]

    relocated = initialize_repo(moved, index=False)
    assert relocated["project_id"] == first["project_id"]


def test_linked_worktrees_share_one_project_identity(
    ce_home: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "main"
    linked = tmp_path / "linked"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test User"], check=True
    )
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "a.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "seed"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", str(linked), "-b", "linked"],
        check=True,
        capture_output=True,
    )

    main = initialize_repo(repo, index=False)
    other = initialize_repo(linked, index=False)

    assert main["project_id"] == other["project_id"]
    assert Path(main["git_common_dir"]) == Path(other["git_common_dir"])
    assert git_common_dir(repo) == git_common_dir(linked)
    assert len(load_registry()["projects"]) == 1
    paths = load_registry()["projects"][main["project_id"]]["paths"]
    assert _norm_path(repo) in paths
    assert _norm_path(linked) in paths


def test_initialize_supersedes_preexisting_git_family_duplicate(
    ce_home: Path, tmp_path: Path,
) -> None:
    from pipeline.project_id import mint_project_id, projects_root, save_registry

    repo = tmp_path / "main"
    linked = tmp_path / "linked"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test User"], check=True
    )
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "a.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "seed"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", str(linked), "-b", "linked"],
        check=True,
        capture_output=True,
    )

    main_id = mint_project_id(repo)
    dup_id = mint_project_id(linked)
    write_id_file(repo, main_id)
    write_id_file(linked, dup_id)
    common = git_common_dir(repo)
    save_registry(
        {
            "projects": {
                main_id: {
                    "paths": [str(repo.resolve())],
                    "managed": True,
                    "git_common_dir": str(common),
                    "last_access_at": 100.0,
                },
                dup_id: {
                    "paths": [str(linked.resolve())],
                    "managed": True,
                    "git_common_dir": str(common),
                    "last_access_at": 1.0,
                },
            }
        }
    )
    (projects_root() / main_id).mkdir(parents=True, exist_ok=True)
    (projects_root() / dup_id).mkdir(parents=True, exist_ok=True)

    result = initialize_repo(linked, index=False)
    assert result["project_id"] == main_id
    assert load_registry()["projects"][dup_id]["superseded_by"] == main_id
    assert len(list_managed_repos()) == 1


def test_pause_resume_sync_rebuild_and_activate(
    ce_home: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    initialized = initialize_repo(repo, index=False)
    assert managed_state(repo) == "active"

    assert pause_repo(repo, reason="maintenance")["state"] == "paused"
    assert managed_state(repo) == "paused"
    paused_sync = sync_now_repo(repo)
    assert paused_sync["ok"] is False
    assert paused_sync["error"] == "paused"
    repeated = initialize_repo(repo, index=False)
    assert repeated["state"] == "paused"
    assert load_registry()["projects"][initialized["project_id"]]["pause_reason"] == "maintenance"
    assert resume_repo(repo)["state"] == "active"
    assert activate_repo(repo)["project_id"] == initialized["project_id"]

    sync = MagicMock()
    sync.to_dict.return_value = {"refreshed": True, "files": [], "error": None}
    with patch("pipeline.incremental.incremental_sync", return_value=sync):
        assert sync_now_repo(repo)["ok"] is True
    with patch("pipeline.indexer.index_repo", return_value=MagicMock(chunks=7)) as index:
        rebuilt = rebuild_repo(repo)
    assert rebuilt["chunks"] == 7
    assert index.call_args.kwargs["force"] is True


def test_never_index_takes_precedence(ce_home: Path, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    initialized = initialize_repo(repo, index=False)
    denied = never_index_repo(repo, reason="private")
    assert denied["state"] == "never_index"
    assert denied["initialized_at"] == initialized["initialized_at"]

    assert activate_repo(repo)["state"] == "never_index"
    assert resume_repo(repo)["state"] == "never_index"
    repeated = initialize_repo(repo, index=False)
    assert repeated["state"] == "never_index"
    assert repeated["ok"] is False
    assert repeated["error"] == "never_index"
    assert sync_now_repo(repo)["ok"] is False
    with patch("pipeline.indexer.index_repo") as index:
        assert rebuild_repo(repo)["ok"] is False
    index.assert_not_called()
    assert managed_state(repo) == "never_index"


def test_activate_unmanaged_requires_initialize_without_persisting(
    ce_home: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "unmanaged"
    repo.mkdir()

    result = activate_repo(repo)

    assert result["ok"] is False
    assert result["status"] == "requires_initialize"
    assert load_registry()["projects"] == {}
    assert not id_file_path(repo).exists()


def test_activate_legacy_registry_row_without_managed_flag(
    ce_home: Path, tmp_path: Path,
) -> None:
    """Path-only registry rows must activate (matches MCP managed default)."""
    from pipeline.project_id import save_registry, write_id_file

    repo = tmp_path / "legacy"
    repo.mkdir()
    project_id = "ce_legacy1234567890abcdef123456"
    write_id_file(repo, project_id)
    save_registry(
        {
            "projects": {
                project_id: {
                    "paths": [str(repo.resolve())],
                    "name": "legacy",
                }
            }
        }
    )

    result = activate_repo(repo)

    assert result["ok"] is True
    assert result["status"] == "activated"
    assert result["project_id"] == project_id
    assert load_registry()["projects"][project_id]["managed"] is True


def test_initialize_and_rebuild_return_indexer_errors(
    ce_home: Path, tmp_path: Path
) -> None:
    initial = tmp_path / "initial"
    initial.mkdir()
    with patch("pipeline.repo_lifecycle.index_is_usable", return_value=False), patch(
        "pipeline.indexer.index_repo", side_effect=RuntimeError("index exploded")
    ):
        failed_initialize = initialize_repo(initial)
    assert failed_initialize["ok"] is False
    assert failed_initialize["error"] == "index exploded"

    rebuild = tmp_path / "rebuild"
    rebuild.mkdir()
    initialize_repo(rebuild, index=False)
    with patch("pipeline.indexer.index_repo", side_effect=RuntimeError("rebuild exploded")):
        failed_rebuild = rebuild_repo(rebuild)
    assert failed_rebuild["ok"] is False
    assert failed_rebuild["error"] == "rebuild exploded"


def test_remove_keeps_or_deletes_store_and_list_reports_metadata(
    ce_home: Path, tmp_path: Path
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    one = initialize_repo(first, index=False)
    two = initialize_repo(second, index=False)
    Path(one["store_dir"], "marker").write_text("keep", encoding="utf-8")
    Path(two["store_dir"], "marker").write_text("delete", encoding="utf-8")

    listed = list_managed_repos()
    assert {item["project_id"] for item in listed} == {
        one["project_id"],
        two["project_id"],
    }
    assert all("initialized_at" in item and "last_access_at" in item for item in listed)

    kept = remove_repo(first, delete_store=False)
    deleted = remove_repo(second, delete_store=True)

    assert kept["store_deleted"] is False
    assert Path(one["store_dir"]).exists()
    assert deleted["store_deleted"] is True
    assert not Path(two["store_dir"]).exists()
    assert managed_state(first) == "unmanaged"
    assert list_managed_repos() == []


def test_cli_lifecycle_commands_return_json(
    ce_home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from pipeline.__main__ import main

    repo = tmp_path / "cli"
    repo.mkdir()
    assert main(["initialize", str(repo), "--no-index"]) == 0
    initialized = json.loads(capsys.readouterr().out)
    assert initialized["state"] == "active"

    assert main(["pause", str(repo), "--reason", "operator"]) == 0
    paused = json.loads(capsys.readouterr().out)
    assert paused["state"] == "paused"

    assert main(["list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed[0]["project_id"] == initialized["project_id"]


def test_cli_never_index_and_requires_initialize_exit_nonzero(
    ce_home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from pipeline.__main__ import main

    denied = tmp_path / "denied"
    denied.mkdir()
    assert main(["never-index", str(denied)]) == 0
    capsys.readouterr()
    assert main(["initialize", str(denied), "--no-index"]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "never_index"
    assert main(["sync-now", str(denied)]) == 1
    capsys.readouterr()
    assert main(["rebuild", str(denied)]) == 1
    capsys.readouterr()

    unmanaged = tmp_path / "unmanaged"
    unmanaged.mkdir()
    assert main(["activate", str(unmanaged)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "requires_initialize"
