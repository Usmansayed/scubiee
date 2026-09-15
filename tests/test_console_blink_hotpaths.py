"""Regression: Windows helper spawns must not flash consoles (R4)."""

from __future__ import annotations

import inspect
import os
import subprocess
from pathlib import Path

import pytest


def test_hidden_run_adds_sw_hide_and_no_window() -> None:
    from pipeline.process_job import CREATE_NO_WINDOW, hidden_run, windows_hidden_startupinfo

    if os.name != "nt":
        return
    calls: list[dict] = []

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        calls.append(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    import pipeline.process_job as pj

    original = pj.subprocess.run
    pj.subprocess.run = fake_run  # type: ignore[assignment]
    try:
        hidden_run(["netstat", "-ano"], capture_output=True, check=False)
    finally:
        pj.subprocess.run = original  # type: ignore[assignment]
    assert calls
    flags = int(calls[0].get("creationflags") or 0)
    assert flags & CREATE_NO_WINDOW
    assert "startupinfo" in calls[0]


def test_daemon_python_probe_uses_hidden_run() -> None:
    import pipeline.daemon as daemon

    src = inspect.getsource(daemon.daemon_python)
    assert "hidden_run" in src
    # Nested probe must not use bare subprocess.run (console flash on Win).
    probe = src.split("def _has_fastembed", 1)[1].split("\n    current =", 1)[0]
    assert "subprocess.run" not in probe


def test_schedule_delete_does_not_use_detached() -> None:
    from pipeline import process_control as pc

    src = inspect.getsource(pc._schedule_delete_after_exit)
    assert "hidden_popen" in src
    assert "subprocess.DETACHED_PROCESS" not in src
    assert "flags |= subprocess.DETACHED" not in src


def test_resolve_child_rejects_console_python_pin(monkeypatch, tmp_path: Path) -> None:
    if os.name != "nt":
        return
    from pipeline import mcp_bridge as bridge

    py = tmp_path / "python.exe"
    py.write_text("", encoding="utf-8")
    monkeypatch.setenv(
        "CTX_MCP_BRIDGE_SPAWN_JSON",
        f'["{py.as_posix()}", "-u", "-m", "pipeline.mcp_locate"]',
    )
    monkeypatch.setattr(
        bridge,
        "_windows_mcp_worker_command",
        lambda: ("pythonw.exe", ["-u", "-m", "pipeline.mcp_locate"]),
    )
    cmd, args = bridge.resolve_child_command()
    assert Path(cmd).name.lower() == "pythonw.exe"
    assert args[-1] == "pipeline.mcp_locate"


def test_pids_listening_uses_hidden_run() -> None:
    src = inspect.getsource(
        __import__("pipeline.process_control", fromlist=["pids_listening_on_port"]).pids_listening_on_port
    )
    assert "hidden_run" in src


def test_heal_skips_netstat_when_lock_alive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Watchdog ~15s heal must not spawn netstat on the steady healthy path."""
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    from pipeline import daemon as d

    monkeypatch.setattr(d, "is_running", lambda: True)
    monkeypatch.setattr(d, "_pid_alive", lambda pid: True)
    d.acquire_lock(4242, url="http://127.0.0.1:8765", repo=str(tmp_path))
    d.pid_path().write_text("4242", encoding="utf-8")

    calls: list[str] = []

    def _boom_netstat(*_a, **_k):  # noqa: ANN001
        calls.append("netstat")
        raise AssertionError("heal must not call pids_listening_on_port")

    monkeypatch.setattr(
        "pipeline.process_control.pids_listening_on_port",
        _boom_netstat,
    )
    monkeypatch.setattr(
        d,
        "bind_engine_identity_to_listener",
        lambda **_k: (_ for _ in ()).throw(AssertionError("bind should be skipped")),
    )
    out = d.heal_engine_lock()
    assert out.get("ok") is True
    assert out.get("reason") == "lock_present"
    assert out.get("healed") is False
    assert calls == []


def test_live_identity_prefers_lock_before_netstat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    from pipeline import daemon as d

    monkeypatch.setattr(d, "_pid_alive", lambda pid: True)
    d.acquire_lock(7777, url="http://127.0.0.1:8765", repo=str(tmp_path))

    class _Client:
        def __init__(self, *a, **k):  # noqa: ANN001
            pass

        def get(self, _path: str):
            return {"ok": True, "repo": str(tmp_path)}

    monkeypatch.setattr(d, "EngineClient", _Client)
    monkeypatch.setattr(
        "pipeline.process_control.pids_listening_on_port",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no netstat")),
    )
    ident = d._live_engine_identity()
    assert ident is not None
    assert ident["pid"] == 7777


def test_schtasks_helpers_use_hidden_run() -> None:
    import inspect
    from pipeline import lifecycle_runtime as lr

    src = inspect.getsource(lr._schtasks_hidden)
    assert "hidden_run" in src
    src_q = inspect.getsource(lr._windows_supervisor_task_exists)
    assert "_schtasks_hidden" in src_q
    src_r = inspect.getsource(lr._run_windows_supervisor_task)
    assert "_schtasks_hidden" in src_r


def test_windows_task_missing_cache_skips_requery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline import lifecycle_runtime as lr

    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    calls: list[list[str]] = []

    def fake_hidden(argv, **_k):  # noqa: ANN001
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="missing")

    monkeypatch.setattr(lr, "_schtasks_hidden", fake_hidden)
    lr._TASK_EXISTS_CACHE = None
    assert lr._windows_supervisor_task_exists(force=True) is False
    assert lr._windows_supervisor_task_exists() is False  # memory cache
    assert len(calls) == 1
    assert calls[0][:2] == ["schtasks", "/Query"]

    # Simulate a new MCP worker process: memory cleared, disk miss must stick.
    lr._TASK_EXISTS_CACHE = None
    assert lr._windows_supervisor_task_exists() is False
    assert len(calls) == 1, "disk cache must prevent schtasks flash across workers"


def test_windows_task_disk_cache_survives_memory_clear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline import lifecycle_runtime as lr

    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    lr._remember_task_exists(False)
    lr._TASK_EXISTS_CACHE = None

    def boom(*_a, **_k):  # noqa: ANN001
        raise AssertionError("schtasks must not run when disk says missing")

    monkeypatch.setattr(lr, "_schtasks_hidden", boom)
    assert lr._windows_supervisor_task_exists() is False


def test_accel_gpu_probes_use_hidden_run() -> None:
    import inspect
    from pipeline import accel

    assert "hidden_run" in inspect.getsource(accel._has_nvidia)
    assert "hidden_run" in inspect.getsource(accel._windows_d3d12_gpus)