"""`scubiee remove` must fully detach a repo, including from a still-running keeper."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def enrolled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from conftest import enroll_test_repo

    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    enroll_test_repo(repo, home=home, project_id="ce_removedetach1234567890abcdef")
    monkeypatch.setattr(
        "pipeline.sync_loop.BackgroundSyncLoop._clients_active", lambda self: False
    )
    return repo


def test_remove_deletes_repo_id_file(enrolled: Path) -> None:
    from pipeline.repo_lifecycle import remove_repo

    id_file = enrolled / ".scubiee" / "id.json"
    assert id_file.is_file()
    out = remove_repo(enrolled)
    assert out["ok"] is True
    assert not id_file.exists()


def test_keeper_stops_syncing_a_removed_repo(enrolled: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.repo_lifecycle import remove_repo
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(enrolled)
    remove_repo(enrolled)
    monkeypatch.setattr(
        "pipeline.root_probe.root_probe",
        lambda *_a, **_k: pytest.fail("keeper probed a removed repo"),
    )
    assert loop.keeper_tick(reason="interval")["strategy"] == "lifecycle_blocked"
    assert loop.drain_due()[0]["strategy"] == "lifecycle_blocked"
    assert not (enrolled / ".scubiee" / "id.json").exists()


def test_keeper_stops_syncing_a_paused_repo(enrolled: Path) -> None:
    from pipeline.repo_lifecycle import activate_repo, pause_repo
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(enrolled)
    pause_repo(enrolled, reason="test")
    out = loop.keeper_tick(reason="interval")
    assert out == {"refreshed": False, "strategy": "lifecycle_blocked", "reason": "paused"}
    activate_repo(enrolled)
    assert loop._lifecycle_blocks_sync() is None


def test_keeper_still_syncs_an_active_repo(enrolled: Path) -> None:
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(enrolled)
    assert loop._lifecycle_blocks_sync() is None
