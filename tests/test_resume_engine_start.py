"""`scubiee resume` starts the engine while pause_state is still paused+resuming.

The engine child (`scubiee engine run`) must not be refused by the global-stop
guard during that window, or resume waits ~90s for a health check that can
never pass.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def ce_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    return home


def _state(home: Path, **data) -> None:
    (home / "pause_state.json").write_text(json.dumps(data), encoding="utf-8")


def test_engine_run_allowed_while_resuming(ce_home: Path) -> None:
    from pipeline.lifecycle_guard import guard_engine_action, paused_blocks_command

    _state(ce_home, paused=True, resuming=True)
    assert paused_blocks_command("engine", ["engine", "run", "/repo"]) is None
    assert guard_engine_action("run") is None


def test_engine_run_still_blocked_when_stopped(ce_home: Path) -> None:
    from pipeline.lifecycle_guard import guard_engine_action, paused_blocks_command

    _state(ce_home, paused=True)
    assert paused_blocks_command("engine", ["engine", "run", "/repo"]) is not None
    assert guard_engine_action("run") is not None


def test_supervisor_keeps_engine_while_resuming(ce_home: Path, monkeypatch) -> None:
    from pipeline import lifecycle_runtime

    monkeypatch.setattr(lifecycle_runtime, "store_hold_active", lambda: False)
    monkeypatch.setattr(
        lifecycle_runtime, "load_policy", lambda: {"desired_mode": lifecycle_runtime.DESIRED_RUN}
    )
    _state(ce_home, paused=True, resuming=True)
    assert lifecycle_runtime.engine_should_be_running() is True
    _state(ce_home, paused=True)
    assert lifecycle_runtime.engine_should_be_running() is False


def test_resume_reports_failure_when_engine_does_not_start(ce_home: Path, monkeypatch) -> None:
    from pipeline import pause_resume

    _state(ce_home, paused=True, connected_tools=[])
    monkeypatch.setattr(pause_resume, "_restore_enrolled_id_files", lambda: [])
    monkeypatch.setattr(
        "pipeline.project_id.load_registry",
        lambda: {"projects": {"p": {"managed": True, "paths": [str(ce_home)]}}},
    )
    monkeypatch.setattr(
        "pipeline.daemon.ensure_daemon",
        lambda repo: {"ok": False, "error": "daemon started but health check timed out"},
    )
    monkeypatch.setattr("pipeline.watchdog.start_watchdog", lambda: {"ok": True}, raising=False)
    monkeypatch.setattr(
        "pipeline.daemon.reconcile_managed_repositories", lambda **k: {"reconciled": 0}
    )
    report = pause_resume.resume()
    assert report["ok"] is False
    assert "engine" in report.get("hint", "").lower()
