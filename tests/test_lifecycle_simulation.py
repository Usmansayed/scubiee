"""Full MCP lifecycle simulation (in-process; no real IDE).

Covers: register → demand → idle without clients → standby gate;
ensure coalesce; silent taskkill helper contract.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


def test_lifecycle_sim_no_clients_eventually_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_DISCONNECT_DEBOUNCE_S", "5")
    monkeypatch.setenv("CTX_ENGINE_TRANSITION_DEBOUNCE_S", "0")
    from pipeline.lifecycle_runtime import (
        DESIRED_RUN,
        apply_idle_policy,
        note_activity,
        set_desired_mode,
        should_idle_stop,
    )

    set_desired_mode(DESIRED_RUN)
    note_activity(now=1000.0)
    assert should_idle_stop(now=1002.0) is False
    assert should_idle_stop(now=1006.0) is True
    with patch("pipeline.daemon.is_running", return_value=True), patch(
        "pipeline.daemon.stop_daemon",
        return_value={"ok": True},
    ) as stop:
        out = apply_idle_policy(now=1006.0, force=True)
    assert out.get("action") == "standby"
    stop.assert_called()


def test_lifecycle_sim_register_blocks_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_DISCONNECT_DEBOUNCE_S", "1")
    from pipeline.lifecycle_runtime import (
        register_client,
        should_idle_stop,
        unregister_client,
    )

    register_client("mcp:cursor@1", pid=1, now=10.0)
    assert should_idle_stop(now=100.0) is False
    unregister_client("mcp:cursor@1", now=11.0)
    assert should_idle_stop(now=11.5) is False
    assert should_idle_stop(now=13.0) is True


def test_lifecycle_sim_second_client_keeps_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_DISCONNECT_DEBOUNCE_S", "1")
    from pipeline.lifecycle_runtime import (
        active_client_count,
        register_client,
        should_idle_stop,
        unregister_client,
    )

    monkeypatch.setattr(
        "pipeline.lifecycle_runtime._client_pid_trustworthy", lambda meta: True
    )
    register_client("mcp:cursor@1", pid=11, now=10.0)
    register_client("mcp:codex@2", pid=22, now=10.5)
    assert active_client_count() >= 1
    unregister_client("mcp:cursor@1", now=11.0)
    assert should_idle_stop(now=20.0) is False
    unregister_client("mcp:codex@2", now=12.0)
    assert should_idle_stop(now=12.4) is False
    assert should_idle_stop(now=14.0) is True


def test_lifecycle_sim_health_clears_stale_start_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline import watchdog as wd
    from pipeline.daemon import note_engine_start_request, start_request_path

    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_WATCHDOG_INTERVAL_S", "0.05")
    monkeypatch.setattr(
        "pipeline.process_job.attach_supervisor_job",
        lambda: {"ok": True, "skipped": True},
    )
    note_engine_start_request(repo=str(tmp_path))
    assert start_request_path().is_file()
    monkeypatch.setattr(wd, "_health_ok", lambda: True)
    wd.watchdog_loop(stop_after=0.2)
    assert not start_request_path().is_file()


def test_lifecycle_sim_supervisor_spawn_cooldown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    from pipeline import lifecycle_runtime as life

    starts: list[dict] = []
    monkeypatch.setattr(life, "current_desktop", lambda: "windows")
    monkeypatch.setattr(life, "_run_windows_supervisor_task", lambda: {"ok": False})
    monkeypatch.setattr("pipeline.watchdog.is_watchdog_running", lambda: False)
    monkeypatch.setattr("pipeline.watchdog.watchdog_status", lambda: {"running": False})
    monkeypatch.setattr(
        "pipeline.watchdog.start_watchdog",
        lambda **kwargs: starts.append(dict(kwargs)) or {"ok": True, "pid": 1},
    )
    life._last_ensure_supervisor_at = 0.0
    life._last_ensure_supervisor_result = None
    first = life.ensure_supervisor_detached()
    second = life.ensure_supervisor_detached()
    assert first.get("ok") is True
    assert len(starts) == 1
    assert second.get("spawn_cooldown") is True


def test_watchdog_child_stays_alive_then_exits_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Subprocess watchdog_loop must not die immediately (CLI temp-home guard is separate)."""
    import os
    import subprocess
    import sys
    import time

    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    env = os.environ.copy()
    env["CTX_HOME"] = str(tmp_path)
    env["CTX_WATCHDOG"] = "1"
    env["CTX_WATCHDOG_INTERVAL_S"] = "0.5"
    kwargs: dict = {
        "args": [
            sys.executable,
            "-c",
            "from pipeline.watchdog import watchdog_loop; watchdog_loop(stop_after=2.0)",
        ],
        "env": env,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
    proc = subprocess.Popen(**kwargs)
    time.sleep(0.8)
    still_running = proc.poll() is None
    if not still_running:
        err = proc.stderr.read() if proc.stderr else ""
        raise AssertionError(f"watchdog child exited early code={proc.returncode} stderr={err}")
    rc = proc.wait(timeout=8)
    assert rc == 0
    log = tmp_path / "watchdog.log"
    text = log.read_text(encoding="utf-8") if log.is_file() else ""
    assert "started" in text
    assert "exited" in text
