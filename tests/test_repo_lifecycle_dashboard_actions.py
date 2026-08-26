"""Safe dashboard lifecycle action boundaries."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import pipeline.project_id as project_identity
from pipeline.project_id import (
    _norm_path,
    load_registry,
    read_id_file,
    save_registry,
    update_registry,
    write_id_file,
)
from pipeline.repo_lifecycle import (
    clear_index_repo,
    forget_repo,
    initialize_repo,
    list_managed_repos,
    locate_repo,
)


@pytest.fixture
def ce_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    return home


def test_clear_index_keeps_registry_and_repository_identity(
    ce_home: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    initialized = initialize_repo(repo, index=False)
    project_id = initialized["project_id"]
    store = Path(initialized["store_dir"])
    (store / "chunks.jsonl").write_text("{}\n", encoding="utf-8")

    result = clear_index_repo(project_id=project_id)

    assert result["ok"] is True
    assert result["store_deleted"] is True
    assert not store.exists()
    assert project_id in load_registry()["projects"]
    assert read_id_file(repo) == project_id


def test_clear_index_by_missing_path_does_not_create_identity(
    ce_home: Path, tmp_path: Path
) -> None:
    missing = tmp_path / "never-existed"

    result = clear_index_repo(root=missing)

    assert result["ok"] is False
    assert result["error"] == "unknown_project"
    assert load_registry()["projects"] == {}
    assert not (missing / ".context-engine" / "id.json").exists()


def test_locate_reattaches_only_path_with_matching_durable_id(
    ce_home: Path, tmp_path: Path
) -> None:
    original = tmp_path / "original"
    original.mkdir()
    initialized = initialize_repo(original, index=False)
    project_id = initialized["project_id"]
    moved = tmp_path / "moved"
    shutil.move(str(original), moved)

    result = locate_repo(project_id, moved)

    assert result["ok"] is True
    assert _norm_path(result["root"]) == _norm_path(moved)
    assert load_registry()["projects"][project_id]["paths"] == [_norm_path(moved)]

    replacement = tmp_path / "replacement"
    replacement.mkdir()
    other = initialize_repo(replacement, index=False)
    rejected = locate_repo(project_id, replacement)
    assert rejected["ok"] is False
    assert rejected["error"] == "project_id_mismatch"
    assert rejected["actual_project_id"] == other["project_id"]


def test_locate_rejects_missing_path_without_creating_identity(
    ce_home: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    project_id = initialize_repo(repo, index=False)["project_id"]
    missing = tmp_path / "missing"

    result = locate_repo(project_id, missing)

    assert result["ok"] is False
    assert result["error"] == "path_missing"
    assert not (missing / ".context-engine" / "id.json").exists()


def test_locate_revalidates_identity_during_registry_attachment(
    ce_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = tmp_path / "original"
    original.mkdir()
    project_id = initialize_repo(original, index=False)["project_id"]
    moved = tmp_path / "moved"
    shutil.move(str(original), moved)

    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    other_id = initialize_repo(unrelated, index=False)["project_id"]

    def swap_marker_then_attach(expected_id: str, root: Path) -> None:
        write_id_file(root, other_id)
        update_registry(expected_id, root)

    monkeypatch.setattr(
        "pipeline.repo_lifecycle.update_registry",
        swap_marker_then_attach,
    )

    result = locate_repo(project_id, moved)

    assert result["ok"] is False
    assert result["error"] == "project_id_mismatch"
    assert str(moved.resolve()) not in load_registry()["projects"][project_id]["paths"]


def test_locate_rolls_back_marker_swap_during_registry_commit(
    ce_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = tmp_path / "original"
    original.mkdir()
    project_id = initialize_repo(original, index=False)["project_id"]
    moved = tmp_path / "moved"
    shutil.move(str(original), moved)

    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    other_id = initialize_repo(unrelated, index=False)["project_id"]
    real_save_registry = project_identity.save_registry

    def swap_marker_inside_commit(registry_data: dict[str, object]) -> None:
        write_id_file(moved, other_id)
        real_save_registry(registry_data)

    monkeypatch.setattr(
        "pipeline.project_id.save_registry",
        swap_marker_inside_commit,
    )

    result = locate_repo(project_id, moved)

    assert result["ok"] is False
    assert result["error"] == "project_id_mismatch"
    assert str(moved.resolve()) not in load_registry()["projects"][project_id]["paths"]


def test_forget_requires_exact_project_id_and_presence_eligibility(
    ce_home: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "friendly-name"
    repo.mkdir()
    initialized = initialize_repo(repo, index=False)
    project_id = initialized["project_id"]
    store = Path(initialized["store_dir"])
    source = repo / "source.py"
    source.write_text("sentinel = True\n", encoding="utf-8")
    shutil.rmtree(repo)

    wrong_confirm = forget_repo(project_id, confirm="friendly-name")
    assert wrong_confirm["ok"] is False
    assert wrong_confirm["error"] == "confirmation_mismatch"

    not_eligible = forget_repo(project_id, confirm=project_id)
    assert not_eligible["ok"] is False
    assert not_eligible["error"] == "forget_not_allowed"
    assert project_id in load_registry()["projects"]

    forced = forget_repo(project_id, confirm=project_id, force=True)
    assert forced["ok"] is False
    assert forced["error"] == "forget_not_allowed"
    assert project_id in load_registry()["projects"]

    registry = load_registry()
    registry["projects"][project_id]["missing_since"] = 0.0
    save_registry(registry)
    forgotten = forget_repo(
        project_id,
        confirm=project_id,
        now=100_000.0,
        retention_s=1.0,
    )

    assert forgotten["ok"] is True
    assert project_id not in load_registry()["projects"]
    assert not store.exists()


def test_forget_never_deletes_repository_source_files(
    ce_home: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    initialized = initialize_repo(repo, index=False)
    project_id = initialized["project_id"]
    source = repo / "keep.py"
    source.write_text("keep = True\n", encoding="utf-8")

    registry = load_registry()
    registry["projects"][project_id]["paths"] = [str(tmp_path / "gone")]
    registry["projects"][project_id]["missing_since"] = 0.0
    save_registry(registry)

    result = forget_repo(
        project_id,
        confirm=project_id,
        now=100_000.0,
        retention_s=1.0,
    )

    assert result["ok"] is True
    assert source.read_text(encoding="utf-8") == "keep = True\n"
    assert repo.exists()


def test_forget_registry_write_failure_preserves_store_and_source(
    ce_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    initialized = initialize_repo(repo, index=False)
    project_id = initialized["project_id"]
    store = Path(initialized["store_dir"])
    (store / "chunks.jsonl").write_text("{}\n", encoding="utf-8")
    source = repo / "keep.py"
    source.write_text("keep = True\n", encoding="utf-8")

    registry = load_registry()
    registry["projects"][project_id]["paths"] = [str(tmp_path / "gone")]
    registry["projects"][project_id]["missing_since"] = 0.0
    save_registry(registry)

    def fail_registry_write(_registry: dict[str, object]) -> None:
        raise OSError("injected registry write failure")

    monkeypatch.setattr("pipeline.project_id.save_registry", fail_registry_write)

    result = forget_repo(
        project_id,
        confirm=project_id,
        now=100_000.0,
        retention_s=1.0,
    )

    assert result["ok"] is False
    assert result["error"] == "registry_write_failed"
    assert project_id in load_registry()["projects"]
    assert store.exists()
    assert source.read_text(encoding="utf-8") == "keep = True\n"


def test_forget_final_registry_failure_leaves_retryable_intent(
    ce_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    initialized = initialize_repo(repo, index=False)
    project_id = initialized["project_id"]
    store = Path(initialized["store_dir"])
    (store / "chunks.jsonl").write_text("{}\n", encoding="utf-8")
    source = repo / "keep.py"
    source.write_text("keep = True\n", encoding="utf-8")

    registry = load_registry()
    registry["projects"][project_id]["paths"] = [str(tmp_path / "gone")]
    registry["projects"][project_id]["missing_since"] = 0.0
    save_registry(registry)
    writes = 0

    def fail_second_registry_write(registry_data: dict[str, object]) -> None:
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("injected final registry write failure")
        save_registry(registry_data)

    monkeypatch.setattr(
        "pipeline.project_id.save_registry",
        fail_second_registry_write,
    )

    result = forget_repo(
        project_id,
        confirm=project_id,
        now=100_000.0,
        retention_s=1.0,
    )

    assert result["ok"] is False
    assert result["error"] == "registry_cleanup_pending"
    pending = load_registry()["projects"][project_id]
    assert pending["forget_pending"] is True
    assert not store.exists()
    assert source.read_text(encoding="utf-8") == "keep = True\n"

    monkeypatch.setattr("pipeline.project_id.save_registry", save_registry)
    retried = forget_repo(
        project_id,
        confirm=project_id,
        now=100_000.0,
        retention_s=1.0,
    )
    assert retried["ok"] is True
    assert project_id not in load_registry()["projects"]


def test_stale_registry_writer_cannot_resurrect_forgotten_repo(
    ce_home: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    initialized = initialize_repo(repo, index=False)
    project_id = initialized["project_id"]

    registry = load_registry()
    registry["projects"][project_id]["paths"] = [str(tmp_path / "gone")]
    registry["projects"][project_id]["missing_since"] = 0.0
    save_registry(registry)
    stale_registry = load_registry()

    forgotten = forget_repo(
        project_id,
        confirm=project_id,
        now=100_000.0,
        retention_s=1.0,
    )
    assert forgotten["ok"] is True

    with pytest.raises(project_identity.RegistryConflictError):
        save_registry(stale_registry)
    assert project_id not in load_registry()["projects"]


def test_list_rows_include_presence_and_forget_allowed(
    ce_home: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    project_id = initialize_repo(repo, index=False)["project_id"]

    row = next(item for item in list_managed_repos() if item["project_id"] == project_id)

    assert row["presence"] == "active"
    assert row["forget_allowed"] is False
    assert row["root_exists"] is True


def test_dashboard_listing_persists_missing_since_and_clears_it_on_resolution(
    ce_home: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    project_id = initialize_repo(repo, index=False)["project_id"]

    shutil.rmtree(repo)
    missing = next(
        item for item in list_managed_repos() if item["project_id"] == project_id
    )
    missing_since = load_registry()["projects"][project_id]["missing_since"]

    assert missing["presence"] == "missing"
    assert isinstance(missing_since, float)

    repo.mkdir()
    write_id_file(repo, project_id)
    active = next(
        item for item in list_managed_repos() if item["project_id"] == project_id
    )

    assert active["presence"] == "active"
    assert load_registry()["projects"][project_id].get("missing_since") is None

    write_id_file(repo, "ce_replacement")
    replaced = next(
        item for item in list_managed_repos() if item["project_id"] == project_id
    )

    assert replaced["presence"] == "replaced"
    assert load_registry()["projects"][project_id].get("missing_since") is None


def test_dashboard_listing_uses_configured_missing_retention(
    ce_home: Path, tmp_path: Path
) -> None:
    from pipeline.settings import save_prefs

    repo = tmp_path / "repo"
    repo.mkdir()
    project_id = initialize_repo(repo, index=False)["project_id"]
    registry = load_registry()
    registry["projects"][project_id]["paths"] = [str(tmp_path / "gone")]
    registry["projects"][project_id]["missing_since"] = 0.0
    save_registry(registry)
    save_prefs({"missing_retention_seconds": 1e20})

    row = next(
        item for item in list_managed_repos() if item["project_id"] == project_id
    )

    assert row["presence"] == "missing"
    assert row["forget_allowed"] is False
