"""Demand-driven idle: unload only after a real MCP leave stamp."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_start_request_is_actionable_ttl() -> None:
    from pipeline.daemon import start_request_is_actionable

    assert start_request_is_actionable({"at": 1.0}, now=10_000.0, clients=1) is True
    assert start_request_is_actionable({"at": 1.0}, now=10_000.0, clients=0) is False
    assert start_request_is_actionable({"at": 9_900.0}, now=10_000.0, clients=0) is True
    assert start_request_is_actionable({}, now=10_000.0, clients=0) is False


def test_should_idle_stop_holds_without_leave_stamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLI init / deferred attach: no leave stamp ⇒ never arm 10s unload."""
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_DISCONNECT_DEBOUNCE_S", "10")
    from pipeline.lifecycle_runtime import (
        DESIRED_RUN,
        note_activity,
        set_desired_mode,
        should_idle_stop,
    )

    set_desired_mode(DESIRED_RUN)
    note_activity(now=100.0)
    assert should_idle_stop(now=105.0) is False
    assert should_idle_stop(now=111.0) is False
    assert should_idle_stop(now=10_000.0) is False


def test_watchdog_skips_force_restart_without_demand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline import watchdog as wd
    from pipeline.lifecycle_runtime import DESIRED_RUN, set_desired_mode

    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_WATCHDOG_INTERVAL_S", "0.05")
    set_desired_mode(DESIRED_RUN)
    calls: list[str] = []

    monkeypatch.setattr(wd, "_health_ok", lambda: False)
    monkeypatch.setattr(wd, "engine_process_alive", lambda: (False, "none"))
    monkeypatch.setattr(wd, "FAILS_BEFORE_RESTART", 2)
    monkeypatch.setattr(wd, "BACKOFF_S", (0.01, 0.01))
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.engine_should_be_running",
        lambda: True,
    )
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.active_client_count",
        lambda: 0,
    )
    monkeypatch.setattr(
        "pipeline.daemon.force_restart_daemon",
        lambda repo=None: calls.append("restart") or {"ok": True},
    )
    monkeypatch.setattr(
        "pipeline.process_job.attach_supervisor_job",
        lambda: {"ok": True, "skipped": True},
    )
    wd.watchdog_loop(stop_after=0.8)
    assert calls == [], "force_restart must not run without clients/start_request"


def test_watchdog_skips_stale_start_request_without_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    import time

    from pipeline import watchdog as wd
    from pipeline.daemon import start_request_path

    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_WATCHDOG_INTERVAL_S", "0.05")
    monkeypatch.setattr(
        "pipeline.process_job.attach_supervisor_job",
        lambda: {"ok": True, "skipped": True},
    )
    start_request_path().parent.mkdir(parents=True, exist_ok=True)
    start_request_path().write_text(
        json.dumps({"repo": str(tmp_path), "at": time.time() - 400}) + "\n",
        encoding="utf-8",
    )
    starts: list[str] = []
    monkeypatch.setattr(wd, "_health_ok", lambda: False)
    monkeypatch.setattr(wd, "engine_process_alive", lambda: (False, "none"))
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.active_client_count",
        lambda: 0,
    )
    monkeypatch.setattr(
        "pipeline.daemon.start_daemon",
        lambda repo=None: starts.append(str(repo)) or {"ok": True},
    )
    wd.watchdog_loop(stop_after=0.3)
    assert starts == []
    assert not start_request_path().is_file()
