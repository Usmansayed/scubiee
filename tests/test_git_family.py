"""Tests for git worktree family deduplication."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from pipeline.git_family import reconcile_git_families
from pipeline.project_id import (
    detect_git_family_duplicates,
    git_common_dir,
    id_file_path,
    index_is_usable,
    load_registry,
    projects_root,
    read_id_file,
    resolve_project,
    save_registry,
)
from pipeline.repo_lifecycle import initialize_repo, list_managed_repos


@pytest.fixture
def ce_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    return home


def _git_worktrees(tmp_path: Path) -> tuple[Path, Path]:
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
    return repo, linked


def _force_duplicate_family(repo: Path, linked: Path) -> tuple[str, str]:
    from pipeline.project_id import mint_project_id, write_id_file

    pid1 = mint_project_id(repo)
    pid2 = mint_project_id(linked)
    write_id_file(repo, pid1)
    write_id_file(linked, pid2)
    common = git_common_dir(repo)
    reg = {
        "projects": {
            pid1: {
                "paths": [str(repo.resolve())],
                "managed": True,
                "git_common_dir": str(common),
                "last_access_at": 100.0,
            },
            pid2: {
                "paths": [str(linked.resolve())],
                "managed": True,
                "git_common_dir": str(common),
                "last_access_at": 1.0,
            },
        }
    }
    save_registry(reg)
    (projects_root() / pid1).mkdir(parents=True, exist_ok=True)
    (projects_root() / pid2).mkdir(parents=True, exist_ok=True)
    return pid1, pid2


def test_detect_and_reconcile_duplicate_git_family(
    ce_home: Path, tmp_path: Path
) -> None:
    repo, linked = _git_worktrees(tmp_path)
    main_id, duplicate_id = _force_duplicate_family(repo, linked)

    assert detect_git_family_duplicates()["needs_reconcile"] is True

    result = reconcile_git_families(prefer_root=repo)
    assert duplicate_id in result.superseded_project_ids
    assert read_id_file(linked) == main_id
    assert detect_git_family_duplicates()["needs_reconcile"] is False
    assert len(list_managed_repos()) == 1


def test_reconcile_promotes_usable_duplicate_store(
    ce_home: Path, tmp_path: Path
) -> None:
    repo, linked = _git_worktrees(tmp_path)
    main_id, duplicate_id = _force_duplicate_family(repo, linked)
    dup_store = projects_root() / duplicate_id
    (dup_store / "chunks.jsonl").write_text('{"id":0}\n', encoding="utf-8")
    (dup_store / "graph.json").write_text("{}", encoding="utf-8")
    (dup_store / "meta.json").write_text(
        json.dumps({"root": str(linked.resolve()), "chunks": 1}),
        encoding="utf-8",
    )
    result = reconcile_git_families(prefer_root=linked)
    assert result.groups_reconciled == 1
    canonical = read_id_file(linked)
    assert canonical is not None
    assert index_is_usable(projects_root() / canonical)


def test_initialize_auto_reconciles_git_family(
    ce_home: Path, tmp_path: Path
) -> None:
    repo, linked = _git_worktrees(tmp_path)
    main_id, dup_id = _force_duplicate_family(repo, linked)

    result = initialize_repo(linked, index=False)
    assert result["project_id"] == main_id
    assert len(list_managed_repos()) == 1
