"""Engine daemon process sweep — orphan kill on upgrade/restart."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from pipeline.process_control import (
    _cmdline_is_engine_run,
    enumerate_engine_run_pids,
    kill_all_engine_daemons,
)


def test_cmdline_is_engine_run_matches_daemon_not_watchdog() -> None:
    assert _cmdline_is_engine_run(
        ["python", "-m", "pipeline", "engine", "run", ".", "--port", "8765"],
        port=8765,
    )
    assert not _cmdline_is_engine_run(
        ["python", "-m", "pipeline", "engine", "watchdog"],
        port=8765,
    )
    assert not _cmdline_is_engine_run(
        ["python", "-m", "pipeline", "engine", "run", ".", "--port", "9999"],
        port=8765,
    )


def test_enumerate_engine_run_pids_scans_orphans(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_ENGINE_ENUM_FULL", "1")
    fake = [
        {"pid": 100, "name": "python.exe", "cmdline": ["python", "-m", "pipeline", "engine", "run", ".", "--port", "8765"]},
        {"pid": 200, "name": "python.exe", "cmdline": ["python", "-m", "pipeline", "engine", "watchdog"]},
        {"pid": 300, "name": "python.exe", "cmdline": ["python", "-m", "pipeline", "engine", "run", ".", "--port", "8765"]},
    ]

    class _Proc:
        def __init__(self, info: dict):
            self.info = info

        def cmdline(self):
            return self.info.get("cmdline") or []

    class _Psutil:
        NoSuchProcess = Exception
        AccessDenied = Exception

        @staticmethod
        def process_iter(fields):
            del fields
            for row in fake:
                yield _Proc(row)

    monkeypatch.setitem(__import__("sys").modules, "psutil", _Psutil())
    monkeypatch.setattr("pipeline.process_control.pids_listening_on_port", lambda _port: [])
    monkeypatch.setattr("pipeline.daemon._read_lock_pid", lambda: None)
    monkeypatch.setattr("pipeline.daemon.pid_path", lambda: __import__("pathlib").Path("/no/pid"))
    pids = enumerate_engine_run_pids(port=8765)
    assert pids == [100, 300]


def test_kill_all_engine_daemons_waits_until_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    health = {"up": True}
    scans = {"n": 0}

    def _scan(**_):
        scans["n"] += 1
        return [111, 222] if scans["n"] == 1 else []

    monkeypatch.setattr("pipeline.process_control.enumerate_engine_run_pids", _scan)
    monkeypatch.setattr("pipeline.process_control.pids_listening_on_port", lambda _port: [])

    def _term(pid, **_):
        health["up"] = False
        return {"pid": pid, "terminated": True}

    monkeypatch.setattr("pipeline.process_control.safe_terminate_pid", _term)
    monkeypatch.setattr("pipeline.daemon.is_running", lambda: health["up"])
    monkeypatch.setattr("pipeline.daemon.release_lock", lambda: None)
    monkeypatch.setattr("pipeline.daemon.pid_path", lambda: __import__("pathlib").Path("/no/pid"))
    monkeypatch.setattr("pipeline.daemon._read_lock_pid", lambda: None)

    out = kill_all_engine_daemons(port=8765, wait_s=1.0)
    assert out["ok"] is True
    assert sorted(out["killed"]) == [111, 222]
    assert out["still_healthy"] is False


def test_is_context_engine_process_recognizes_engine_run_module() -> None:
    from pipeline.process_control import is_context_engine_process

    class _Proc:
        def __init__(self):
            self._cmd = [
                r"C:\uv\tools\scubiee\Scripts\python.exe",
                "-u",
                "-m",
                "pipeline",
                "engine",
                "run",
                ".",
                "--port",
                "8765",
            ]

        def cmdline(self):
            return self._cmd

        def name(self):
            return "python.exe"

    import pipeline.process_control as pc

    original = __import__("psutil").Process

    class _Psutil:
        class Process:
            def __init__(self, pid: int):
                self._p = _Proc()

            def cmdline(self):
                return self._p.cmdline()

            def name(self):
                return self._p.name()

    # Direct helper path
    assert pc._cmdline_is_engine_run(
        ["python", "-m", "pipeline", "engine", "run", ".", "--port", "8765"],
        port=8765,
    )


def test_force_restart_uses_kill_sweep_and_force_start(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[str] = []

    monkeypatch.setattr(
        "pipeline.daemon.stop_daemon",
        lambda **_: calls.append("stop") or {"ok": True, "still_healthy": False},
    )
    monkeypatch.setattr("pipeline.daemon.is_running", lambda: False)
    monkeypatch.setattr(
        "pipeline.process_control.kill_all_engine_daemons",
        lambda **_: calls.append("sweep") or {"ok": True, "killed": [1, 2], "still_healthy": False},
    )
    monkeypatch.setattr("pipeline.daemon.release_lock", lambda: calls.append("unlock"))
    monkeypatch.setattr(
        "pipeline.daemon.start_daemon",
        lambda *a, **k: calls.append(f"start:force={k.get('force')}") or {"ok": True, "started": True},
    )
    monkeypatch.setattr("pipeline.daemon.meta_path", lambda: tmp_path / "engine.json")
    (tmp_path / "engine.json").write_text('{"url":"http://127.0.0.1:8765","repo":"."}', encoding="utf-8")

    from pipeline.daemon import force_restart_daemon

    out = force_restart_daemon(tmp_path)
    assert out["ok"] is True
    assert out["forced"] is True
    assert "stop" in calls
    assert any(c.startswith("start:force=True") for c in calls)


def test_kill_all_engine_allows_child_engine_run(monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.process_control import kill_all_engine_daemons

    calls: list[tuple] = []

    def _term(pid, **kwargs):
        calls.append((pid, kwargs.get("allow_child")))
        return {"pid": pid, "terminated": True}

    monkeypatch.setattr("pipeline.process_control.enumerate_engine_run_pids", lambda **_: [4242])
    monkeypatch.setattr("pipeline.process_control.pids_listening_on_port", lambda _p: [])
    monkeypatch.setattr("pipeline.process_control.safe_terminate_pid", _term)
    monkeypatch.setattr("pipeline.daemon.is_running", lambda: False)
    monkeypatch.setattr("pipeline.daemon.release_lock", lambda: None)
    out = kill_all_engine_daemons(port=8765, wait_s=0.2)
    assert calls[0] == (4242, True)
    assert out["killed"] == [4242]
