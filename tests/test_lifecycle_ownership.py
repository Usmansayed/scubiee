"""Lifecycle ownership rewrite — engine survives MCP reload; lock heal; non-blocking attach."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


def test_release_lock_only_if_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    from pipeline import daemon as d

    d.acquire_lock(4242, url="http://127.0.0.1:8765", repo=str(tmp_path))
    assert d.lock_path().is_file()
    # Foreign process must not clear a live engine's lock.
    monkeypatch.setattr("pipeline.daemon.os.getpid", lambda: 9999)
    d.release_lock_if_owner()
    assert d.lock_path().is_file()
    data = json.loads(d.lock_path().read_text(encoding="utf-8"))
    assert data["pid"] == 4242

    monkeypatch.setattr("pipeline.daemon.os.getpid", lambda: 4242)
    d.release_lock_if_owner()
    assert not d.lock_path().is_file()


def test_heal_lock_rewrites_missing_lock_when_healthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    from pipeline import daemon as d

    monkeypatch.setattr(d, "is_running", lambda: True)
    monkeypatch.setattr(
        d,
        "_live_engine_identity",
        lambda: {"pid": 5555, "url": "http://127.0.0.1:8765", "repo": str(tmp_path)},
    )
    out = d.heal_engine_lock()
    assert out.get("ok") is True
    assert out.get("healed") is True
    assert d._read_lock_pid() == 5555
    assert d.pid_path().is_file()


def test_engine_alive_uses_port_when_lock_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    from pipeline import watchdog as wd

    monkeypatch.setattr("pipeline.daemon._read_lock_pid", lambda: None)
    monkeypatch.setattr(
        "pipeline.daemon.pid_path",
        lambda: tmp_path / "missing.pid",
    )
    monkeypatch.setattr(
        "pipeline.daemon.meta_path",
        lambda: tmp_path / "missing.json",
    )
    monkeypatch.setattr(
        "pipeline.daemon.default_host_port",
        lambda: ("127.0.0.1", 8765),
    )
    monkeypatch.setattr(
        "pipeline.process_control.pids_listening_on_port",
        lambda port: [7777] if int(port) == 8765 else [],
    )
    monkeypatch.setattr(wd, "_pid_alive", lambda pid: pid == 7777)
    monkeypatch.setattr("pipeline.daemon.heal_engine_lock", lambda: {"ok": True})
    alive, source = wd.engine_process_alive()
    assert alive is True
    assert source == "port"


def test_watchdog_skips_restart_while_indexing_and_alive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline import watchdog as wd
    from pipeline.lifecycle_runtime import note_activity

    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_WATCHDOG_INTERVAL_S", "0.05")
    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "99999")
    monkeypatch.setattr(
        "pipeline.process_job.attach_supervisor_job",
        lambda: {"ok": True, "skipped": True},
    )
    note_activity()
    calls: list[str] = []

    monkeypatch.setattr(wd, "_health_ok", lambda: False)
    monkeypatch.setattr(wd, "engine_process_alive", lambda: (True, "port"))
    monkeypatch.setattr(
        wd,
        "_engine_busy_indexing",
        lambda: True,
    )
    monkeypatch.setattr(wd, "BACKOFF_S", (0.01, 0.01))
    monkeypatch.setattr(wd, "FAILS_BEFORE_RESTART", 2)
    with patch(
        "pipeline.daemon.force_restart_daemon",
        side_effect=lambda repo=None: calls.append("restart") or {"ok": True},
    ):
        wd.watchdog_loop(stop_after=0.35)
    assert calls == []


def test_attach_mcp_session_is_nonblocking(monkeypatch, tmp_path: Path) -> None:
    from pipeline import mcp_lifecycle as ml

    warm_calls: list[dict] = []

    def _warm(*_a, **k):
        warm_calls.append(dict(k))
        return {"ok": True, "deferred": True, "prewarm_wait": {"ms": 1}}

    monkeypatch.setattr(ml, "warm_engine_for_mcp", _warm)
    monkeypatch.setattr(ml, "_spawn_background_warm", lambda *_a, **_k: None)
    monkeypatch.setattr(ml, "_start_heartbeat", lambda *_a, **_k: None)
    monkeypatch.setattr(ml, "_install_process_signals", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "pipeline.session_isolation.default_process_session_id",
        lambda: "fast",
    )
    monkeypatch.setattr(ml.atexit, "register", lambda fn: None)

    monkeypatch.setenv("CTX_MCP_AUTO_WARM", "1")
    out = ml.attach_mcp_session(tmp_path)
    assert out["client_id"] == "mcp:fast"
    assert out.get("warm_started") is True
    assert warm_calls and warm_calls[0].get("blocking") is False


def test_engine_popen_defaults_to_no_flash_flags() -> None:
    from pipeline.process_job import CREATE_NO_WINDOW, engine_popen_kwargs
    import os
    import subprocess

    kwargs = engine_popen_kwargs()
    if os.name != "nt":
        assert kwargs.get("start_new_session") is True
        return
    flags = int(kwargs.get("creationflags") or 0)
    assert flags & CREATE_NO_WINDOW
    # Soft default must NOT use DETACHED_PROCESS (that flashes consoles).
    detached = int(getattr(subprocess, "DETACHED_PROCESS", 0x8))
    assert not (flags & detached)


def test_engine_popen_hard_detach_when_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.process_job import (
        CREATE_BREAKAWAY_FROM_JOB,
        CREATE_NO_WINDOW,
        engine_popen_kwargs,
    )
    import os
    import subprocess

    monkeypatch.setenv("CTX_ENGINE_HARD_DETACH", "1")
    kwargs = engine_popen_kwargs()
    if os.name != "nt":
        return
    flags = int(kwargs.get("creationflags") or 0)
    assert flags & CREATE_NO_WINDOW
    assert flags & CREATE_BREAKAWAY_FROM_JOB
    detached = int(getattr(subprocess, "DETACHED_PROCESS", 0x8))
    assert flags & detached
