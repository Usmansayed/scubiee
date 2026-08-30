"""Tests for copied-checkout fork + path-scoped wipe resilience."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from pipeline.checkout_identity import (
    fork_copied_checkout,
    reconcile_registry_copy_collisions,
    remove_registry_checkout,
    resolve_checkout_project_id,
)
from pipeline.project_id import (
    load_registry,
    projects_root,
    read_id_file,
    resolve_project,
    save_registry,
    write_id_file,
)
from pipeline.repo_lifecycle import initialize_repo, remove_repo
from pipeline.wipe import wipe_repo


@pytest.fixture
def ce_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    return home


def _fs_id(tag: str) -> dict[str, object]:
    return {"os": "posix", "dev": 1, "ino": hash(tag) % 10_000_000}


def _fake_fs(path: Path | str, *, original: Path, copy: Path):
    resolved = Path(path).resolve()
    if resolved == copy.resolve():
        return _fs_id("copy")
    return _fs_id("orig")


def _enroll(path: Path, pid: str, *, fs_tag: str = "orig") -> None:
    path.mkdir(parents=True, exist_ok=True)
    write_id_file(path, pid)
    save_registry(
        {
            "projects": {
                pid: {
                    "managed": True,
                    "root": str(path.resolve()),
                    "paths": [str(path.resolve())],
                    "fs_id": _fs_id(fs_tag),
                }
            }
        }
    )
    (projects_root() / pid).mkdir(parents=True, exist_ok=True)


def test_resolve_forks_copied_checkout_on_first_bind(
    ce_home: Path, tmp_path: Path,
) -> None:
    original = tmp_path / "a"
    copy = tmp_path / "a-copy"
    pid = "ce_copyfork1234567890abcdef"
    _enroll(original, pid, fs_tag="orig")
    shutil.copytree(original, copy)

    with patch(
        "pipeline.checkout_identity._current_fs_id",
        side_effect=lambda p: _fake_fs(p, original=original, copy=copy),
    ):
        new_pid, report = resolve_checkout_project_id(copy, read_id_file(copy))

    assert report["forked"] is True
    assert new_pid != pid
    assert read_id_file(copy) == new_pid
    assert read_id_file(original) == pid
    assert str(copy.resolve()) not in load_registry()["projects"][pid].get("paths", [])


def test_resolve_project_auto_forks_copy_without_manual_init(
    ce_home: Path, tmp_path: Path,
) -> None:
    original = tmp_path / "a"
    copy = tmp_path / "a1"
    pid = "ce_bindfork1234567890abcdef"
    _enroll(original, pid, fs_tag="orig")
    shutil.copytree(original, copy)

    with patch(
        "pipeline.checkout_identity._current_fs_id",
        side_effect=lambda p: _fake_fs(p, original=original, copy=copy),
    ):
        ref = resolve_project(copy, migrate=False)

    assert ref.project_id != pid
    assert read_id_file(copy) == ref.project_id
    assert read_id_file(original) == pid


def test_wipe_one_copy_keeps_sibling_registry_and_store(
    ce_home: Path, tmp_path: Path,
) -> None:
    original = tmp_path / "a"
    copy = tmp_path / "a-copy"
    pid = "ce_wipesib1234567890abcdef"
    _enroll(original, pid, fs_tag="orig")
    shutil.copytree(original, copy)
    save_registry(
        {
            "projects": {
                pid: {
                    "managed": True,
                    "root": str(original.resolve()),
                    "paths": [str(original.resolve()), str(copy.resolve())],
                    "fs_id": _fs_id("orig"),
                }
            }
        }
    )
    (projects_root() / pid / "chunks.jsonl").write_text("{}\n", encoding="utf-8")

    removed = remove_repo(copy, delete_store=True)

    assert removed["ok"]
    assert removed["siblings_remaining"] == 1
    assert removed["registry_row_removed"] is False
    assert removed["store_deleted"] is False
    assert pid in load_registry()["projects"]
    assert (projects_root() / pid / "chunks.jsonl").is_file()
    assert read_id_file(original) == pid


def test_wipe_after_manual_scubiee_delete_still_targets_only_that_path(
    ce_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = tmp_path / "a"
    copy = tmp_path / "a-copy"
    pid = "ce_manualdel1234567890abcdef"
    _enroll(original, pid, fs_tag="orig")
    shutil.copytree(original, copy)
    save_registry(
        {
            "projects": {
                pid: {
                    "managed": True,
                    "root": str(original.resolve()),
                    "paths": [str(original.resolve()), str(copy.resolve())],
                    "fs_id": _fs_id("orig"),
                }
            }
        }
    )
    shutil.rmtree(copy / ".scubiee")

    monkeypatch.setattr(
        "pipeline.rules_installer.strip_all_project_tool_surfaces",
        lambda *_a, **_k: {"ok": True},
    )

    report = wipe_repo(copy)

    assert report["ok"]
    assert report["project_id"] == pid
    assert pid in load_registry()["projects"]
    assert read_id_file(original) == pid


def test_reconcile_registry_copy_collisions_forks_stale_shared_id(
    ce_home: Path, tmp_path: Path,
) -> None:
    original = tmp_path / "a"
    copy = tmp_path / "a2"
    pid = "ce_reconcile1234567890abcdef"
    _enroll(original, pid, fs_tag="orig")
    shutil.copytree(original, copy)
    save_registry(
        {
            "projects": {
                pid: {
                    "managed": True,
                    "root": str(original.resolve()),
                    "paths": [str(original.resolve()), str(copy.resolve())],
                    "fs_id": _fs_id("orig"),
                }
            }
        }
    )

    with patch(
        "pipeline.checkout_identity._current_fs_id",
        side_effect=lambda p: _fake_fs(p, original=original, copy=copy),
    ):
        result = reconcile_registry_copy_collisions()

    assert len(result["forked"]) == 1
    assert read_id_file(copy) != pid
    assert read_id_file(original) == pid


def test_initialize_repo_forks_copy_that_still_has_id_json(
    ce_home: Path, tmp_path: Path,
) -> None:
    original = tmp_path / "a"
    copy = tmp_path / "a-copy"
    pid = "ce_initcopy1234567890abcdef"
    _enroll(original, pid, fs_tag="orig")
    shutil.copytree(original, copy)

    with patch(
        "pipeline.checkout_identity._current_fs_id",
        side_effect=lambda p: _fake_fs(p, original=original, copy=copy),
    ):
        out = initialize_repo(copy, index=False)

    assert out["project_id"] != pid
    assert read_id_file(copy) != pid
    assert read_id_file(original) == pid
    assert str(copy.resolve()) not in load_registry()["projects"][pid].get("paths", [])


def test_untrusted_id_file_still_forks_on_resolve(
    ce_home: Path, tmp_path: Path,
) -> None:
    original = tmp_path / "a"
    copy = tmp_path / "a-copy"
    pid = "ce_untrust1234567890abcdef"
    _enroll(original, pid, fs_tag="orig")
    shutil.copytree(original, copy)

    with patch(
        "pipeline.checkout_identity._current_fs_id",
        side_effect=lambda p: _fake_fs(p, original=original, copy=copy),
    ):
        ref = resolve_project(copy, migrate=False)

    assert ref.project_id != pid
    assert read_id_file(copy) == ref.project_id


def test_fork_registers_new_project_in_registry(
    ce_home: Path, tmp_path: Path,
) -> None:
    original = tmp_path / "a"
    copy = tmp_path / "a-copy"
    pid = "ce_regfork1234567890abcdef"
    _enroll(original, pid, fs_tag="orig")
    shutil.copytree(original, copy)

    from pipeline.project_id import _norm_path

    with patch(
        "pipeline.checkout_identity._current_fs_id",
        side_effect=lambda p: _fake_fs(p, original=original, copy=copy),
    ):
        new_pid = fork_copied_checkout(copy, from_project_id=pid)

    assert new_pid in load_registry()["projects"]
    paths = load_registry()["projects"][new_pid].get("paths", [])
    assert any(_norm_path(item) == _norm_path(copy) for item in paths)


def test_detect_registry_copy_collisions_reports_unforked_copy(
    ce_home: Path, tmp_path: Path,
) -> None:
    from pipeline.checkout_identity import detect_registry_copy_collisions

    original = tmp_path / "a"
    copy = tmp_path / "a-copy"
    pid = "ce_detect1234567890abcdef"
    _enroll(original, pid, fs_tag="orig")
    shutil.copytree(original, copy)
    save_registry(
        {
            "projects": {
                pid: {
                    "managed": True,
                    "root": str(original.resolve()),
                    "paths": [str(original.resolve()), str(copy.resolve())],
                    "fs_id": _fs_id("orig"),
                }
            }
        }
    )

    with patch(
        "pipeline.checkout_identity._current_fs_id",
        side_effect=lambda p: _fake_fs(p, original=original, copy=copy),
    ):
        hits = detect_registry_copy_collisions()

    assert len(hits) == 1
    assert Path(hits[0]["path"]).resolve() == copy.resolve()


def test_fs_id_os_mismatch_does_not_false_fork(
    ce_home: Path, tmp_path: Path,
) -> None:
    from pipeline.checkout_identity import _is_copy_of_registry_checkout

    original = tmp_path / "a"
    pid = "ce_osmismatch1234567890abc"
    original.mkdir()
    write_id_file(original, pid)
    save_registry(
        {
            "projects": {
                pid: {
                    "managed": True,
                    "root": str(original.resolve()),
                    "paths": [str(original.resolve())],
                    "fs_id": {"os": "posix", "dev": 1, "ino": 42},
                }
            }
        }
    )

    def fake_fs(path: Path | str):
        return {"os": "nt", "file_id": 99, "vol_serial": 1}

    with patch("pipeline.checkout_identity._current_fs_id", side_effect=fake_fs):
        assert _is_copy_of_registry_checkout(original, pid) is False


def test_update_registry_does_not_overwrite_fs_id_for_copy_alias(
    ce_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pipeline.project_id import update_registry

    original = tmp_path / "a"
    copy = tmp_path / "a-copy"
    pid = "ce_fsalias1234567890abcdef"
    _enroll(original, pid, fs_tag="orig")
    copy.mkdir()
    write_id_file(copy, pid)

    def fake_fs(path: Path | str, *, original: Path = original, copy: Path = copy):
        resolved = Path(path).resolve()
        if resolved == copy.resolve():
            return _fs_id("copy")
        return _fs_id("orig")

    with patch(
        "pipeline.hw_track.get_filesystem_id",
        side_effect=lambda p: fake_fs(p),
    ):
        save_registry(
            {
                "projects": {
                    pid: {
                        "managed": True,
                        "root": str(original.resolve()),
                        "paths": [str(original.resolve())],
                        "fs_id": _fs_id("orig"),
                    }
                }
            }
        )
        update_registry(pid, copy)

    entry = load_registry()["projects"][pid]
    assert entry["fs_id"] == _fs_id("orig")


def test_initialize_restores_id_on_original_after_copy_deleted_scubiee(
    ce_home: Path, tmp_path: Path,
) -> None:
    original = tmp_path / "a"
    copy = tmp_path / "a-copy"
    pid = "ce_initrest1234567890abcdef"
    _enroll(original, pid, fs_tag="orig")
    shutil.copytree(original, copy)
    shutil.rmtree(copy / ".scubiee")

    with patch(
        "pipeline.checkout_identity._current_fs_id",
        side_effect=lambda p: _fake_fs(p, original=original, copy=copy),
    ):
        out = initialize_repo(copy, index=False)

    assert out["project_id"] != pid
    assert read_id_file(original) == pid
