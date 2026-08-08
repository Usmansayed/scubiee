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
    with patch("pipeline.daemon.force_restart_daemon", side_effect=fake_restart):
        wd.watchdog_loop(stop_after=3.0)
    assert "restart" in calls


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
