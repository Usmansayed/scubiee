"""Tests for lifecycle action-combination guardrails."""

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


def test_engine_start_blocked_when_globally_stopped(ce_home: Path) -> None:
    from pipeline.lifecycle_guard import guard_engine_action, paused_blocks_command
    from pipeline.pause_resume import _save_state

    _save_state({"paused": True})

    assert "resume" in (paused_blocks_command("engine", ["engine", "start"]) or "").lower()
    blocked = guard_engine_action("start")
    assert blocked is not None
    assert blocked["ok"] is False
    assert blocked["reason"] == "globally_paused"


def test_engine_stop_noop_when_globally_stopped(ce_home: Path) -> None:
    from pipeline.lifecycle_guard import guard_engine_action, paused_blocks_command
    from pipeline.pause_resume import _save_state

    _save_state({"paused": True})

    blocked = guard_engine_action("stop")
    assert blocked is not None
    assert blocked["ok"] is True
    assert blocked["skipped"] is True
    msg = paused_blocks_command("engine", ["engine", "stop"]) or ""
    assert "already stopped" in msg.lower() or "resume" in msg.lower()


def test_engine_start_allowed_when_only_daemon_down(ce_home: Path) -> None:
    from pipeline.lifecycle_guard import guard_engine_action, paused_blocks_command

    assert paused_blocks_command("engine", ["engine", "start"]) is None
    assert guard_engine_action("start") is None


def test_wipe_allowed_when_globally_stopped(ce_home: Path) -> None:
    from pipeline.lifecycle_guard import paused_blocks_command
    from pipeline.pause_resume import _save_state

    _save_state({"paused": True})
    assert paused_blocks_command("wipe", ["wipe", "--all"]) is None


def test_init_blocked_when_globally_stopped(ce_home: Path) -> None:
    from pipeline.lifecycle_guard import paused_blocks_command
    from pipeline.pause_resume import _save_state

    _save_state({"paused": True})
    msg = paused_blocks_command("init", ["init", "."])
    assert msg is not None
    assert "resume" in msg.lower()


def test_describe_state_distinguishes_global_vs_engine(ce_home: Path, monkeypatch) -> None:
    from pipeline.lifecycle_guard import describe_state
    from pipeline.pause_resume import _save_state

    monkeypatch.setattr("pipeline.daemon.is_running", lambda: False)
    _save_state({"paused": False})
    assert "engine stop" in describe_state()

    _save_state({"paused": True})
    assert "globally stopped" in describe_state()


def test_engine_status_allowed_with_argv(ce_home: Path) -> None:
    from pipeline.lifecycle_guard import paused_blocks_command
    from pipeline.pause_resume import _save_state

    _save_state({"paused": True})
    assert paused_blocks_command("engine", ["engine", "status"]) is None
    assert paused_blocks_command("engine", None) is not None  # missing subcommand → block


def test_lifecycle_guidance_daemon_down_is_not_global_stop(
    monkeypatch, tmp_path: Path,
) -> None:
    from pipeline import lifecycle_guidance as lg

    monkeypatch.setattr(lg, "lifecycle_snapshot", lambda _root=None: {
        "globally_paused": False,
        "machine_ready": True,
        "repo_enrolled": True,
        "repo_managed": True,
        "repo_paused": False,
        "project_id": "ce_test",
        "daemon_healthy": False,
        "cursor_connected": True,
        "root": str(tmp_path),
    })
    guide = lg.next_actions(tmp_path)
    assert guide["state"] == "daemon_down"
    assert "engine start" in guide["steps"][0]["action"]
    assert "not the same" in guide["steps"][0]["why"].lower()


def test_emit_lifecycle_notice_when_stopped(ce_home: Path, capsys) -> None:
    from pipeline.lifecycle_guard import emit_lifecycle_notice
    from pipeline.pause_resume import _save_state

    _save_state({"paused": True})
    assert emit_lifecycle_notice() is True
    err = capsys.readouterr().err
    assert "globally stopped" in err.lower()
    assert "resume" in err.lower()


def test_emit_lifecycle_notice_silent_when_ready(ce_home: Path, capsys, monkeypatch) -> None:
    from pipeline.lifecycle_guard import emit_lifecycle_notice

    monkeypatch.setattr(
        "pipeline.lifecycle_guard.describe_state",
        lambda: "ready",
    )
    assert emit_lifecycle_notice() is False
    assert capsys.readouterr().err == ""


def test_globally_paused_hint_text() -> None:
    from pipeline.lifecycle_guard import globally_paused_hint

    assert "scubiee resume" in globally_paused_hint()


def test_setup_repair_allowed_when_paused(ce_home: Path) -> None:
    from pipeline.lifecycle_guard import paused_blocks_command
    from pipeline.pause_resume import _save_state

    _save_state({"paused": True})
    assert paused_blocks_command("setup", ["setup", "--repair"]) is None
    assert paused_blocks_command("setup", ["setup"]) is not None


def test_disconnect_allowed_when_globally_stopped(ce_home: Path) -> None:
    from pipeline.lifecycle_guard import paused_blocks_command
    from pipeline.pause_resume import _save_state

    _save_state({"paused": True})
    assert paused_blocks_command("disconnect", ["disconnect", "--cursor"]) is None
