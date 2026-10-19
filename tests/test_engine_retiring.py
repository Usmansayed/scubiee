"""A start racing an in-flight stop must replace the engine, not adopt it."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ce_home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(ce_home))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]
    monkeypatch.setenv("CTX_ENGINE_URL", f"http://127.0.0.1:{free_port}")
    return ce_home


@pytest.fixture
def engine_proc():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    yield proc
    proc.kill()
    proc.wait()


def _retire(d, proc, *, exit_after_s: float | None) -> None:
    d.acquire_lock(proc.pid, url="http://127.0.0.1:1", repo=None)
    d.note_engine_retiring(proc.pid, reason="stop_daemon:idle_standby")
    if exit_after_s is not None:
        threading.Timer(exit_after_s, proc.kill).start()


def test_wait_returns_once_engine_exits_and_frees_lock(home, engine_proc) -> None:
    from pipeline import daemon as d

    _retire(d, engine_proc, exit_after_s=0.5)
    assert d.retiring_engine_pid() == engine_proc.pid
    out = d.wait_for_retiring_engine(5.0)
    # The killed child is an unreaped zombie here; it must still count as exited.
    assert out is not None and out["exited"] is True
    assert d._read_lock_pid() is None
    assert d.is_running() is False


def test_live_stopper_keeps_start_waiting_after_engine_exits(home, engine_proc) -> None:
    """stop_daemon sweeps the port after the old pid dies; a start must not spawn into that."""
    from pipeline import daemon as d

    stopper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        d.note_engine_retiring(None, reason="stop_daemon:idle_standby", stopper_pid=stopper.pid)
        d.note_engine_retiring(engine_proc.pid, reason="http_shutdown:idle_standby")
        engine_proc.kill()
        engine_proc.wait()
        assert d.retiring_engine() == {"pid": engine_proc.pid, "stopper_pid": stopper.pid}
        threading.Timer(0.5, lambda: d.clear_engine_retiring(stopper_pid=stopper.pid)).start()
        out = d.wait_for_retiring_engine(5.0)
        assert out is not None and out["exited"] is True
        assert out["waited_ms"] >= 400
    finally:
        stopper.kill()
        stopper.wait()


def test_stopper_never_waits_on_itself(home) -> None:
    import os

    from pipeline import daemon as d

    d.note_engine_retiring(None, reason="stop_daemon:user", stopper_pid=os.getpid())
    assert d.retiring_engine() is None


def test_stop_daemon_clears_its_marker(home, monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline import daemon as d

    seen: dict[str, object] = {}

    def fake_sweep(**_k):
        seen["during"] = d._load_retiring()
        return {"ok": True, "killed": []}

    monkeypatch.setattr("pipeline.process_control.kill_all_engine_daemons", fake_sweep)
    monkeypatch.setattr("pipeline.process_control.safe_terminate_pid", lambda *a, **k: {})
    d.stop_daemon(reason="idle_standby")
    assert seen["during"] is not None
    assert not d.retiring_path().exists()


def test_standby_backs_off_when_start_lands_mid_retire(
    home, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline import daemon as d
    from pipeline import lifecycle_runtime as lr

    stopped: list[str] = []

    class Governor:
        def force_demote_disconnect(self) -> None:
            lr.note_engine_transition("start")

    monkeypatch.setattr("pipeline.memory_governor.get_governor", lambda: Governor())
    monkeypatch.setattr(d, "stop_daemon", lambda **k: stopped.append("stop") or {"ok": True})
    out = lr.enter_standby(stop_engine=True)
    assert out["action"] == "start_won_standby"
    assert stopped == []
    assert lr.load_policy()["desired_mode"] == lr.DESIRED_RUN


def test_no_marker_means_no_wait(home) -> None:
    from pipeline import daemon as d

    assert d.wait_for_retiring_engine(5.0) is None


def test_stale_or_foreign_marker_is_ignored(home, engine_proc) -> None:
    from pipeline import daemon as d

    d.acquire_lock(engine_proc.pid, url="http://127.0.0.1:1", repo=None)
    old = {"pid": engine_proc.pid, "reason": "x", "at": time.time() - 3600}
    d.retiring_path().write_text(json.dumps(old), encoding="utf-8")
    assert d.retiring_engine_pid() is None

    d.note_engine_retiring(engine_proc.pid + 100000, reason="other engine")
    assert d.retiring_engine_pid() is None


def test_start_spawns_fresh_engine_after_retiring_one_exits(
    home, engine_proc, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline import daemon as d

    class Spawned(Exception):
        pass

    def fake_spawn(cmd, env):
        raise Spawned()

    monkeypatch.setattr("pipeline.install_guard.check_install_conflict", lambda: None)
    monkeypatch.setattr("pipeline.install_guard.write_install_marker", lambda *a, **k: None)
    monkeypatch.setattr(d, "_engine_orphan_spawn_enabled", lambda: False)
    monkeypatch.setattr(d, "_spawn_engine_child", fake_spawn)

    _retire(d, engine_proc, exit_after_s=0.5)
    assert d.is_running() is True
    with pytest.raises(Spawned):
        d.start_daemon(None, wait_s=5.0)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows spawn pid may be a launcher")
def test_start_returns_fast_when_spawned_engine_dies(
    home, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline import daemon as d

    children: list[subprocess.Popen] = []

    def short_lived(cmd, env):
        children.append(subprocess.Popen([sys.executable, "-c", "pass"]))
        return children[-1].pid

    monkeypatch.setattr("pipeline.install_guard.check_install_conflict", lambda: None)
    monkeypatch.setattr("pipeline.install_guard.write_install_marker", lambda *a, **k: None)
    monkeypatch.setattr("pipeline.watchdog.ensure_watchdog_sidecar", lambda: None)
    monkeypatch.setattr(d, "_engine_orphan_spawn_enabled", lambda: False)
    monkeypatch.setattr(d, "_spawn_engine_child", short_lived)

    started = time.time()
    out = d.start_daemon(None, wait_s=30.0)
    assert time.time() - started < 10.0
    assert out["ok"] is False and out["exited"] is True
    assert d._read_lock_pid() is None
    for child in children:
        child.wait()


def test_start_reports_engine_still_shutting_down(
    home, engine_proc, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline import daemon as d

    monkeypatch.setattr(d, "RETIRING_WAIT_S", 0.5)
    _retire(d, engine_proc, exit_after_s=None)
    out = d.start_daemon(None, wait_s=0.5)
    assert out["ok"] is False
    assert not out.get("already_running")
    assert out["retiring"]["pid"] == engine_proc.pid


def test_engine_stopping_itself_returns_at_once(home, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    import pipeline.daemon as d
    import pipeline.process_control as pc

    d.acquire_lock(os.getpid(), url="http://127.0.0.1:1", repo=None)

    def _no_sweep(**_k):
        raise AssertionError("the engine cannot sweep its own pid off the port")

    monkeypatch.setattr(pc, "kill_all_engine_daemons", _no_sweep)
    t0 = time.monotonic()
    out = d.stop_daemon(reason="idle_standby")
    assert time.monotonic() - t0 < 1.0
    assert out["self_retire"] is True and out["killed"] == []
    assert d._read_lock_pid() == os.getpid()
    assert d.retiring_engine() is None
