"""Doctor checks for connected tools + managed registry consistency."""

from __future__ import annotations

from pathlib import Path

from pipeline.connect_state import save_connected_tools
from pipeline.doctor import doctor_all, doctor_repo
from pipeline.managed_repos import audit_connect_registry
from pipeline.project_id import save_registry


def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()
    return path


def test_audit_warns_connected_tools_without_managed_repos(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    save_connected_tools(["cursor", "codex"])
    save_registry({"projects": {}})

    audit = audit_connect_registry()
    assert audit["ok"] is False
    assert audit["managed_repos"] == 0
    ids = {item["id"] for item in audit["warnings"]}
    assert "connected_tools_no_managed_repos" in ids


def test_audit_warns_stale_registry_path(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    missing = tmp_path / "gone-repo"
    pid = "ce_stale1234567890abcdef"
    save_registry(
        {
            "projects": {
                pid: {
                    "managed": True,
                    "root": str(missing),
                    "paths": [str(missing)],
                }
            }
        }
    )

    audit = audit_connect_registry()
    assert audit["ok"] is False
    assert len(audit["stale_registry_paths"]) == 1
    assert audit["stale_registry_paths"][0]["path"] == str(missing)
    ids = {item["id"] for item in audit["warnings"]}
    assert "stale_registry_path" in ids


def test_audit_warns_unenrolled_managed_repo(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = _git_repo(tmp_path / "proj")
    pid = "ce_unenrolled1234567890abcdef"
    save_registry(
        {
            "projects": {
                pid: {
                    "managed": True,
                    "root": str(repo.resolve()),
                    "paths": [str(repo.resolve())],
                }
            }
        }
    )
    save_connected_tools([])

    audit = audit_connect_registry()
    assert audit["ok"] is True
    assert audit["managed_repos"] == 1
    assert audit["enrolled_repos"] == 0
    assert len(audit["unenrolled_managed_repos"]) == 1
    ids = {item["id"] for item in audit["warnings"]}
    assert "unenrolled_managed_repo" in ids


def test_doctor_repo_includes_connect_registry_block(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "r"
    repo.mkdir()
    save_connected_tools(["cursor"])

    report = doctor_repo(repo)
    connect = report.get("connect_registry")
    assert isinstance(connect, dict)
    assert connect.get("connected_tools") == ["cursor"]
    # Doctor is read-only: must not auto-enroll the empty folder.
    assert not (repo / ".scubiee").exists()
    assert report.get("enrollment", {}).get("enrolled") is False
    assert connect.get("managed_repos", 0) == 0


def test_doctor_all_surfaces_fleet_connect_warnings(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = _git_repo(tmp_path / "proj")
    pid = "ce_fleet1234567890abcdef"
    save_registry(
        {
            "projects": {
                pid: {
                    "managed": True,
                    "root": str(repo.resolve()),
                    "paths": [str(repo.resolve())],
                }
            }
        }
    )
    save_connected_tools(["cursor"])

    fleet = doctor_all()
    connect = fleet.get("connect_registry")
    assert isinstance(connect, dict)
    assert connect["managed_repos"] == 1
    ids = {item["id"] for item in connect.get("warnings") or []}
    assert "unenrolled_managed_repo" in ids
    repair_ids = {
        item["id"] for item in fleet.get("repair_plan") or [] if isinstance(item, dict)
    }
    assert "unenrolled_managed_repo" in repair_ids


def test_audit_warns_shared_id_copy_collision(
    tmp_path: Path, monkeypatch
) -> None:
    import shutil
    from unittest.mock import patch

    def _fs_id(tag: str) -> dict[str, object]:
        return {"os": "posix", "dev": 1, "ino": hash(tag) % 10_000_000}

    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))

    original = tmp_path / "a"
    copy = tmp_path / "a-copy"
    pid = "ce_doccopy1234567890abcdef"
    original.mkdir()
    (original / ".scubiee").mkdir()
    (original / ".scubiee" / "id.json").write_text(
        f'{{"project_id":"{pid}"}}', encoding="utf-8"
    )
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

    def fake_fs(path):
        resolved = Path(path).resolve()
        if resolved == copy.resolve():
            return _fs_id("copy")
        return _fs_id("orig")

    with patch("pipeline.checkout_identity._current_fs_id", side_effect=fake_fs):
        audit = audit_connect_registry()

    assert audit["ok"] is False
    ids = {item["id"] for item in audit["warnings"]}
    assert "shared_id_copy_collision" in ids


def test_plan_repairs_maps_copy_collision_to_safe_fork() -> None:
    from pipeline.doctor import plan_repairs

    report = {
        "connect_registry": {
            "warnings": [
                {
                    "id": "shared_id_copy_collision",
                    "detail": "Copied checkout still shares project ce_x at /copy",
                }
            ]
        }
    }
    repair_ids = {item["id"] for item in plan_repairs(report=report)}
    assert "fork_copy_collisions" in repair_ids


def test_apply_safe_repairs_runs_copy_collision_reconcile(
    tmp_path: Path, monkeypatch
) -> None:
    import shutil
    from unittest.mock import patch

    from pipeline.checkout_identity import reconcile_registry_copy_collisions
    from pipeline.doctor import apply_safe_repairs
    from pipeline.project_id import read_id_file, write_id_file

    def _fs_id(tag: str) -> dict[str, object]:
        return {"os": "posix", "dev": 1, "ino": hash(tag) % 10_000_000}

    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))

    original = tmp_path / "a"
    copy = tmp_path / "a-copy"
    pid = "ce_repair1234567890abcdef"
    original.mkdir()
    write_id_file(original, pid)
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

    def fake_fs(path):
        resolved = Path(path).resolve()
        if resolved == copy.resolve():
            return _fs_id("copy")
        return _fs_id("orig")

    minimal = {
        "ok": False,
        "project_id": pid,
        "capabilities": {"ok": True},
        "readiness": {"index_usable": True, "manifest": {"ok": True}},
        "binding": {"ok": True},
        "journal": {"pending": False},
        "git_family": {"needs_reconcile": False},
        "connect_registry": {
            "ok": False,
            "warnings": [
                {
                    "id": "shared_id_copy_collision",
                    "detail": "fork copied checkout",
                }
            ],
        },
    }

    with patch("pipeline.checkout_identity._current_fs_id", side_effect=fake_fs):
        monkeypatch.setattr("pipeline.doctor.doctor_repo", lambda root=None: minimal)
        repaired = apply_safe_repairs(copy)
        assert read_id_file(copy) != pid
        assert read_id_file(original) == pid
        assert len(reconcile_registry_copy_collisions()["forked"]) == 0

    fork_actions = [
        item for item in repaired.get("applied") or [] if item.get("id") == "fork_copy_collisions"
    ]
    assert fork_actions
