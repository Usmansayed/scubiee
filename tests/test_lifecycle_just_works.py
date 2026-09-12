"""0.3.62 — Cursor just-works: supervisor-owned engine, locate>sync, single PID."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


def test_bind_identity_rewrites_wrapper_to_listener(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    from pipeline import daemon as d

    monkeypatch.setattr(d, "is_running", lambda: True)
    monkeypatch.setattr(
        d,
        "_live_engine_identity",
        lambda: {"pid": 6936, "url": "http://127.0.0.1:8765", "repo": str(tmp_path)},
    )
    from pipeline.artifact_guard import atomic_write_text

    atomic_write_text(
        d.lock_path(),
        json.dumps(
            {
                "pid": 24404,
                "url": "http://127.0.0.1:8765",
                "repo": str(tmp_path),
            }
        )
        + "\n",
    )
    d.pid_path().write_text("24404", encoding="utf-8")
    out = d.bind_engine_identity_to_listener(repo=str(tmp_path))
    assert out.get("bound") is True
    assert d._read_lock_pid() == 6936
    assert d.pid_path().read_text(encoding="utf-8").strip() == "6936"


def test_mcp_ensure_never_calls_start_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_SUPERVISOR_ENGINE_WAIT_S", "0.2")
    from pipeline import daemon as d

    calls: list[str] = []
    monkeypatch.setattr(d, "is_running", lambda: False)
    monkeypatch.setattr(d, "_read_lock_pid", lambda: None)
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.ensure_supervisor_detached",
        lambda: calls.append("supervisor") or {"ok": True, "started": True},
    )
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.set_desired_mode",
        lambda *_a, **_k: {"desired_mode": "run"},
    )
    monkeypatch.setattr("pipeline.lifecycle_runtime.note_activity", lambda: None)
    monkeypatch.setattr(
        d,
        "start_daemon",
        lambda *_a, **_k: calls.append("start_daemon") or {"ok": True},
    )
    out = d.ensure_daemon(tmp_path, force_if_hung=False, spawn_owner="supervisor")
    assert "start_daemon" not in calls
    assert "supervisor" in calls
    assert out.get("spawn_owner") == "supervisor"
    assert out.get("ok") is False


def test_ensure_direct_starts_without_supervisor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    from pipeline import daemon as d

    calls: list[str] = []
    monkeypatch.setattr(d, "is_running", lambda: False)
    monkeypatch.setattr(d, "_read_lock_pid", lambda: None)
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.ensure_supervisor_detached",
        lambda: calls.append("supervisor") or {"ok": True, "started": True},
    )
    monkeypatch.setattr("pipeline.lifecycle_runtime.note_activity", lambda: None)
    monkeypatch.setattr(
        d,
        "start_daemon",
        lambda *_a, **_k: calls.append("start_daemon") or {"ok": True, "started": True},
    )
    out = d.ensure_daemon(tmp_path, force_if_hung=False, spawn_owner="direct")
    assert "supervisor" not in calls
    assert "start_daemon" in calls
    assert out.get("spawn_owner") == "direct"
    assert out.get("ok") is True


def test_coalesce_cursor_mcp_clients(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    from pipeline import lifecycle_runtime as lr

    monkeypatch.setattr(lr, "reconcile_clients", lambda now=None: [])
    monkeypatch.setattr(
        "pipeline.memory_governor.get_governor",
        lambda: type("G", (), {"ensure_semantic_tier": lambda self: None})(),
    )
    monkeypatch.setattr(
        "pipeline.engine.ensure_embedder_ready",
        lambda *_a, **_k: {"ok": True},
    )
    first = lr.register_client("mcp:cursor@proc-1", pid=111, kind="mcp", host="cursor")
    assert first.get("ok") is True
    second = lr.register_client("mcp:cursor@proc-2", pid=222, kind="mcp", host="cursor")
    assert second.get("ok") is True
    assert "mcp:cursor@proc-1" in (second.get("coalesced") or [])
    data = lr.load_clients()
    assert list(data["clients"].keys()) == ["mcp:cursor@proc-2"]


def test_locate_streak_defers_live_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from conftest import enroll_test_repo
    from pipeline.sync_loop import BackgroundSyncLoop

    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    enroll_test_repo(tmp_path, home=home, project_id="ce_justworks_locate1234567890ab")
    monkeypatch.setattr(
        "pipeline.sync_loop.BackgroundSyncLoop._clients_active",
        lambda self: False,
    )
    loop = BackgroundSyncLoop(tmp_path, locate_streak_ms=60_000)
    now = 100.0
    loop.note_locate(now=now)
    deferred = loop._defer_for_active_session(["a.py"], now=now + 1.0, estimated_total=1)
    assert deferred is not None
    assert deferred["reason"] == "locate_streak"
    assert deferred["strategy"] == "deferred_active_session"


def test_watchdog_honors_engine_start_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline import watchdog as wd
    from pipeline.daemon import note_engine_start_request

    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_WATCHDOG_INTERVAL_S", "0.05")
    monkeypatch.setenv("CTX_WATCHDOG_AUTO_START", "1")
    monkeypatch.setattr(
        "pipeline.process_job.attach_supervisor_job",
        lambda: {"ok": True, "skipped": True},
    )
    note_engine_start_request(repo=str(tmp_path / "proj"))
    calls: list[str] = []
    monkeypatch.setattr(wd, "_health_ok", lambda: False)
    monkeypatch.setattr(wd, "engine_process_alive", lambda: (False, "none"))
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.engine_should_be_running",
        lambda: True,
    )
    monkeypatch.setattr(
        "pipeline.daemon.start_daemon",
        lambda repo=None: calls.append(str(repo)) or {"ok": True},
    )
    wd.watchdog_loop(stop_after=0.25)
    assert calls, "expected start_daemon after engine.start_request stamp"


def test_watchdog_skips_auto_start_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline import watchdog as wd
    from pipeline.daemon import note_engine_start_request, start_request_path

    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_WATCHDOG_INTERVAL_S", "0.05")
    monkeypatch.delenv("CTX_WATCHDOG_AUTO_START", raising=False)
    monkeypatch.setattr(
        "pipeline.process_job.attach_supervisor_job",
        lambda: {"ok": True, "skipped": True},
    )
    note_engine_start_request(repo=str(tmp_path / "proj"))
    calls: list[str] = []
    monkeypatch.setattr(wd, "_health_ok", lambda: False)
    monkeypatch.setattr(wd, "engine_process_alive", lambda: (False, "none"))
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.engine_should_be_running",
        lambda: True,
    )
    monkeypatch.setattr(
        "pipeline.daemon.start_daemon",
        lambda repo=None: calls.append(str(repo)) or {"ok": True},
    )
    wd.watchdog_loop(stop_after=0.25)
    assert calls == [], "watchdog must not cold-start; agent start_daemon owns warm"
    assert not start_request_path().is_file()


def test_ensure_supervisor_detached_uses_orphan_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    from pipeline import lifecycle_runtime as lr

    calls: list[dict] = []
    monkeypatch.setattr(lr, "current_desktop", lambda: "windows")
    monkeypatch.setattr(lr, "_run_windows_supervisor_task", lambda: {"ok": False})
    monkeypatch.setattr(
        "pipeline.watchdog.is_watchdog_running",
        lambda: False,
    )
    monkeypatch.setattr(
        "pipeline.watchdog.watchdog_status",
        lambda: {"running": False},
    )

    def _start(*, orphan: bool = False):
        calls.append({"orphan": orphan})
        return {"ok": True, "started": True, "orphan": orphan, "pid": 1}

    monkeypatch.setattr("pipeline.watchdog.start_watchdog", _start)
    lr._last_ensure_supervisor_at = 0.0
    lr._last_ensure_supervisor_result = None
    out = lr.ensure_supervisor_detached()
    assert calls and calls[0]["orphan"] is True
    assert out.get("started") == "wmi_orphan"


def test_background_python_prefers_pythonw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    from pipeline import process_job as pj

    py = tmp_path / "python.exe"
    pyw = tmp_path / "pythonw.exe"
    py.write_text("", encoding="utf-8")
    pyw.write_text("", encoding="utf-8")
    monkeypatch.setattr("pipeline.daemon.daemon_python", lambda: str(py))
    if os.name == "nt":
        assert Path(pj.background_python()).name == "pythonw.exe"
    else:
        assert pj.background_python() == str(py)
