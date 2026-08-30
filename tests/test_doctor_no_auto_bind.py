"""Doctor/connect/resume must not auto-enroll repos after wipe."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.connect_state import MachineSetupRequiredError, require_machine_setup
from pipeline.doctor import doctor_repo
from pipeline.project_id import ProjectNotBoundError, resolve_project
from pipeline.rules_installer import install_tool
from pipeline.tool_registry import get_tool


def test_resolve_project_bind_false_raises_when_unenrolled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(ProjectNotBoundError):
        resolve_project(repo, migrate=False, bind=False)


def test_doctor_does_not_create_scubiee_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()

    report = doctor_repo(repo)

    assert not (repo / ".scubiee").exists()
    assert report.get("enrollment", {}).get("enrolled") is False
    assert report.get("project_id") is None
    repair_ids = {item["id"] for item in report.get("repair_plan") or []}
    assert "initialize_repo" in repair_ids


def test_connect_requires_setup_before_recreating_home_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    monkeypatch.chdir(tmp_path)

    with pytest.raises(MachineSetupRequiredError):
        require_machine_setup()

    tool = get_tool("cursor")
    assert tool is not None
    report = install_tool(tool, dry_run=False)
    assert report["ok"] is False
    assert not (home / "connected_tools.json").is_file()
