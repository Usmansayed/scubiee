"""Lightweight watchdog sidecar tests."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))


@pytest.fixture
def wd_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "ce"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    monkeypatch.setenv("CTX_WATCHDOG", "1")
    monkeypatch.setenv("CTX_WATCHDOG_INTERVAL_S", "0.05")
    return home


@pytest.fixture(autouse=True)
def _no_windows_job(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "pipeline.process_job.attach_supervisor_job",
        lambda: {"ok": True, "skipped": True},
    )


def test_windows_hidden_spawn_does_not_use_detached_process():
    import os
    import subprocess

    from pipeline.process_job import (
        CREATE_NO_WINDOW,
        hidden_popen_kwargs,
        windows_hidden_creationflags,
    )

    flags = windows_hidden_creationflags()
    assert flags & CREATE_NO_WINDOW
    # Hidden helpers (watchdog) stay non-DETACHED; engine uses DETACHED separately.
    assert not flags & int(getattr(subprocess, "DETACHED_PROCESS", 0x8))
    kwargs = hidden_popen_kwargs()
    if os.name == "nt":
        assert kwargs["creationflags"] == flags


def test_watchdog_disabled(wd_home: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CTX_WATCHDOG", "0")
    from pipeline.watchdog import start_watchdog, watchdog_enabled

    assert watchdog_enabled() is False
    r = start_watchdog()
    assert r.get("skipped") is True


def test_stop_watchdog_clears_pid(wd_home: Path):
    from pipeline.watchdog import stop_watchdog, watchdog_pid_path

    watchdog_pid_path().write_text("999999", encoding="utf-8")
    out = stop_watchdog()
    assert out["ok"] is True
    assert not watchdog_pid_path().is_file()


def test_loop_restarts_after_two_fails(wd_home: Path, monkeypatch: pytest.MonkeyPatch):
    from pipeline import watchdog as wd
    from pipeline.lifecycle_runtime import note_activity

    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "99999")
    monkeypatch.setenv("CTX_WATCHDOG_AUTO_START", "1")
    note_activity()
    calls: list[str] = []
    health_left = [False, False, True, True]

    def health():
        return health_left.pop(0) if health_left else True

    def fake_restart(repo=None):
        calls.append("restart")
        return {"ok": True, "forced": True}

    monkeypatch.setattr(wd, "_health_ok", health)
    monkeypatch.setattr(wd, "BACKOFF_S", (0.01, 0.01, 0.01))
    monkeypatch.setattr(wd, "FAILS_BEFORE_RESTART", 2)
    # Demand present → restart allowed (ghost engines without clients must not).
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.active_client_count",
        lambda: 1,
    )
    with patch("pipeline.daemon.force_restart_daemon", side_effect=fake_restart):
        wd.watchdog_loop(stop_after=3.0)
    assert "restart" in calls


def test_loop_skips_restart_when_mcp_clients_and_pid_alive(
    wd_home: Path, monkeypatch: pytest.MonkeyPatch
):
    from pipeline import watchdog as wd
    from pipeline.lifecycle_runtime import note_activity

    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "99999")
    note_activity()
    calls: list[str] = []

    monkeypatch.setattr(wd, "_health_ok", lambda: False)
    monkeypatch.setattr(wd, "_pid_alive", lambda pid: True)
    monkeypatch.setattr("pipeline.daemon._read_lock_pid", lambda: 4242)
    monkeypatch.setattr("pipeline.lifecycle_runtime.active_client_count", lambda: 1)
    monkeypatch.setattr(wd, "BACKOFF_S", (0.01, 0.01, 0.01))
    monkeypatch.setattr(wd, "FAILS_BEFORE_RESTART", 2)
    with patch(
        "pipeline.daemon.force_restart_daemon",
        side_effect=lambda repo=None: calls.append("restart") or {"ok": True},
    ):
        wd.watchdog_loop(stop_after=0.4)
    assert calls == []


def test_loop_does_not_autoload_when_mcp_clients_but_pid_dead(
    wd_home: Path, monkeypatch: pytest.MonkeyPatch
):
    """MCP still connected must not make the watchdog cold-start the engine."""
    from pipeline import watchdog as wd
    from pipeline.lifecycle_runtime import note_activity

    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "99999")
    monkeypatch.delenv("CTX_WATCHDOG_AUTO_START", raising=False)
    note_activity()
    calls: list[str] = []

    monkeypatch.setattr(wd, "_health_ok", lambda: False)
    monkeypatch.setattr(wd, "_pid_alive", lambda pid: False)
    monkeypatch.setattr("pipeline.daemon._read_lock_pid", lambda: 4242)
    monkeypatch.setattr("pipeline.lifecycle_runtime.active_client_count", lambda: 2)
    monkeypatch.setattr(wd, "BACKOFF_S", (0.01, 0.01, 0.01))
    monkeypatch.setattr(wd, "FAILS_BEFORE_RESTART", 2)
    with patch(
        "pipeline.daemon.force_restart_daemon",
        side_effect=lambda repo=None: calls.append("restart") or {"ok": True},
    ):
        wd.watchdog_loop(stop_after=3.0)
    assert calls == []


def test_loop_restarts_when_mcp_clients_but_pid_dead(
    wd_home: Path, monkeypatch: pytest.MonkeyPatch
):
    """Opt-in auto-start may revive after the engine process dies."""
    from pipeline import watchdog as wd
    from pipeline.lifecycle_runtime import note_activity

    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "99999")
    monkeypatch.setenv("CTX_WATCHDOG_AUTO_START", "1")
    note_activity()
    calls: list[str] = []

    monkeypatch.setattr(wd, "_health_ok", lambda: False)
    monkeypatch.setattr(wd, "_pid_alive", lambda pid: False)
    monkeypatch.setattr("pipeline.daemon._read_lock_pid", lambda: 4242)
    monkeypatch.setattr("pipeline.lifecycle_runtime.active_client_count", lambda: 2)
    monkeypatch.setattr(wd, "BACKOFF_S", (0.01, 0.01, 0.01))
    monkeypatch.setattr(wd, "FAILS_BEFORE_RESTART", 2)
    with patch(
        "pipeline.daemon.force_restart_daemon",
        side_effect=lambda repo=None: calls.append("restart") or {"ok": True},
    ):
        wd.watchdog_loop(stop_after=3.0)
    assert "restart" in calls


def test_loop_does_not_kill_alive_engine_on_brief_health_lag(
    wd_home: Path, monkeypatch: pytest.MonkeyPatch
):
    """Indexing/boot health timeouts are not crashes while the engine PID is alive."""
    from pipeline import watchdog as wd
    from pipeline.lifecycle_runtime import note_activity

    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "99999")
    note_activity()
    calls: list[str] = []

    monkeypatch.setattr(wd, "_health_ok", lambda: False)
    monkeypatch.setattr(wd, "_pid_alive", lambda pid: True)
    monkeypatch.setattr("pipeline.daemon._read_lock_pid", lambda: 4242)
    monkeypatch.setattr("pipeline.lifecycle_runtime.active_client_count", lambda: 0)
    monkeypatch.setattr(wd, "BACKOFF_S", (0.01, 0.01, 0.01))
    monkeypatch.setattr(wd, "FAILS_BEFORE_RESTART", 2)
    monkeypatch.setattr(wd, "ALIVE_PID_FAILS_BEFORE_RESTART", 8)
    with patch(
        "pipeline.daemon.force_restart_daemon",
        side_effect=lambda repo=None: calls.append("restart") or {"ok": True},
    ):
        wd.watchdog_loop(stop_after=3.0)
    assert calls == []


def test_loop_standby_does_not_restart(wd_home: Path, monkeypatch: pytest.MonkeyPatch):
    from pipeline import watchdog as wd
    from pipeline.lifecycle_runtime import DESIRED_STANDBY, set_desired_mode

    set_desired_mode(DESIRED_STANDBY)
    calls: list[str] = []

    monkeypatch.setattr(wd, "_health_ok", lambda: False)
    monkeypatch.setattr(wd, "BACKOFF_S", (0.01, 0.01, 0.01))
    monkeypatch.setattr(wd, "FAILS_BEFORE_RESTART", 2)
    with patch("pipeline.daemon.force_restart_daemon", side_effect=lambda repo=None: calls.append("restart") or {"ok": True}):
        wd.watchdog_loop(stop_after=0.3)
    assert calls == []


def test_loop_idle_stop_is_not_watchdogs_job(wd_home: Path, monkeypatch: pytest.MonkeyPatch):
    from pipeline import watchdog as wd
    from pipeline.lifecycle_runtime import note_activity

    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "1")
    note_activity(now=1.0)
    stopped: list[str] = []

    monkeypatch.setattr(wd, "_health_ok", lambda: True)
    monkeypatch.setattr("pipeline.lifecycle_runtime.enter_standby", lambda **kwargs: stopped.append("standby") or {"ok": True})
    monkeypatch.setattr(wd, "BACKOFF_S", (0.01, 0.01, 0.01))
    wd.watchdog_loop(stop_after=0.3)
    assert stopped == []


def test_apply_idle_policy_enters_standby_once(wd_home: Path, monkeypatch: pytest.MonkeyPatch):
    from pipeline.lifecycle_runtime import (
        apply_idle_policy,
        engine_should_be_running,
        note_activity,
        register_client,
        unregister_client,
    )

    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "1")
    monkeypatch.setenv("CTX_DISCONNECT_DEBOUNCE_S", "1")
    monkeypatch.setenv("CTX_ENGINE_TRANSITION_DEBOUNCE_S", "0")
    note_activity(now=1.0)
    register_client("t", pid=1, now=1.0)
    unregister_client("t", now=1.0)
    # A successful stop must leave is_running() False, otherwise the sweep is
    # right to try again — a resident engine under standby is the wedge state.
    alive = {"running": True}

    def fake_stop(*args, **kwargs):
        alive["running"] = False
        return {"ok": True, "running": False}

    with patch("pipeline.daemon.is_running", side_effect=lambda: alive["running"]), patch(
        "pipeline.daemon.stop_daemon",
        side_effect=fake_stop,
    ):
        first = apply_idle_policy(now=10.0)
        second = apply_idle_policy(now=10.0)
    assert first["action"] == "standby"
    assert second["action"] == "already_standby"
    assert engine_should_be_running() is False


def test_force_restart_calls_stop_and_start(wd_home: Path):
    from pipeline.daemon import force_restart_daemon, meta_path

    meta_path().write_text(
        '{"repo": "C:/tmp/proj", "url": "http://127.0.0.1:8765"}',
        encoding="utf-8",
    )
    with patch("pipeline.daemon.stop_daemon", return_value={"ok": True}) as stop, patch(
        "pipeline.daemon.start_daemon",
        return_value={"ok": True, "started": True},
    ) as start, patch("pipeline.daemon._pid_alive", return_value=False), patch(
        "pipeline.daemon.is_running", return_value=False
    ):
        out = force_restart_daemon("C:/tmp/proj")
    assert out.get("forced") is True
    assert out.get("ok") is True
    stop.assert_called()
    start.assert_called()


def test_watchdog_status_shape(wd_home: Path):
    from pipeline.watchdog import watchdog_status

    s = watchdog_status()
    assert "enabled" in s
    assert "running" in s
    assert "log" in s
