"""Stopping an engine that isn't there must not recreate a wiped CTX_HOME."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def missing_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    monkeypatch.setattr("pipeline.daemon.EngineClient.post", lambda *a, **k: {})
    monkeypatch.setattr("pipeline.daemon.is_running", lambda: False)
    monkeypatch.setattr(
        "pipeline.process_control.kill_all_engine_daemons",
        lambda **k: {"ok": True, "killed": []},
    )
    return home


def test_stop_daemon_does_not_create_missing_home(missing_home: Path) -> None:
    from pipeline.daemon import stop_daemon

    out = stop_daemon(reason="user")
    assert out["ok"] is True
    assert not missing_home.exists()


def test_note_stop_does_not_create_missing_home(missing_home: Path) -> None:
    from pipeline.engine_log import note_stop

    note_stop("engine", 1234, reason="test", method="kill")
    assert not missing_home.exists()


def test_stop_daemon_still_records_when_home_exists(missing_home: Path) -> None:
    from pipeline.daemon import stop_daemon
    from pipeline.lifecycle_runtime import load_transition

    missing_home.mkdir()
    stop_daemon(reason="user")
    assert load_transition()["last_action"] == "stop"
    assert "[stop]" in (missing_home / "engine.log").read_text(encoding="utf-8")
