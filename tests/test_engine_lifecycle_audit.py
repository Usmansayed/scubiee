"""Issue 2 (engine dies silently) and issue 8 (disconnect traceback spam)."""

from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

import pytest

_STAMP = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} ")


def test_timestamped_stream_stamps_each_line_once():
    from pipeline.engine_log import TimestampedStream

    inner = io.StringIO()
    s = TimestampedStream(inner)
    s.write("[engine] a")
    s.write(" still a\n[engine] b\n")
    s.write("Traceback (most recent call last):\n  File x\n")
    lines = inner.getvalue().splitlines()
    assert len(lines) == 4
    assert all(_STAMP.match(line) for line in lines)
    assert lines[0].endswith("[engine] a still a")  # partial writes: one stamp


def test_note_stop_writes_audit_line(_isolate_scubiee_home: Path, monkeypatch):
    from pipeline.engine_log import note_stop

    monkeypatch.delenv("CTX_SCUBIEE_ROLE", raising=False)
    note_stop("engine", 4242, reason="unit_reason", method="taskkill/T/F")
    note_stop("watchdog", 77, reason="stop_watchdog", method="taskkill/F")
    eng = (_isolate_scubiee_home / "engine.log").read_text(encoding="utf-8")
    wd = (_isolate_scubiee_home / "watchdog.log").read_text(encoding="utf-8")
    line = eng.splitlines()[0]
    assert _STAMP.match(line)
    for part in ("[stop] target=engine", "pid=4242", "reason=unit_reason", "method=taskkill/T/F", "by_pid=", "at="):
        assert part in line
    assert "target=watchdog pid=77" in eng and "target=watchdog pid=77" in wd


def test_orphan_env_keeps_config_drops_secrets():
    from pipeline.daemon import _orphan_env

    out = _orphan_env(
        {
            "CTX_ENGINE_IDLE_S": "10",
            "CTX_TOKEN_MODE": "savings",
            "PYTHONUTF8": "1",
            "PATH": r"C:\x",
            "HF_TOKEN": "hf_secret",
            "OPENAI_API_KEY": "sk-secret",
            "PYTHON_KEYRING_PASSWORD": "pw",
            "RANDOM_VAR": "x",
        }
    )
    assert out == {"CTX_ENGINE_IDLE_S": "10", "CTX_TOKEN_MODE": "savings", "PYTHONUTF8": "1", "PATH": r"C:\x"}


def test_orphan_spawn_builds_boot_command(_isolate_scubiee_home: Path, monkeypatch):
    import pipeline.daemon as d

    seen: dict = {}

    def _wmi(command_line, *, cwd=None):
        seen["cmd"] = command_line
        seen["cwd"] = cwd
        boot = re.search(r"(\S*_boot_engine_\w+\.json)", command_line).group(1).strip('"')
        seen["boot"] = json.loads(Path(boot).read_text(encoding="utf-8"))
        return {"ok": True, "pid": 999, "method": "wmi_com"}

    monkeypatch.setattr("pipeline.process_job.windows_wmi_create_process", _wmi)
    cmd = ["C:/py/pythonw.exe", "-u", "-m", "pipeline", "engine", "run", "C:/repo", "--host", "127.0.0.1", "--port", "8765"]
    out = d._spawn_engine_orphan(cmd, {"CTX_REPO": "C:/repo", "HF_TOKEN": "x"}, cwd=str(_isolate_scubiee_home))
    assert out["ok"] and out["pid"] == 999
    assert "-m pipeline.engine_boot" in seen["cmd"]
    assert seen["cmd"].rstrip().endswith("engine run C:/repo --host 127.0.0.1 --port 8765")
    assert seen["boot"]["env"] == {"CTX_REPO": "C:/repo"}
    assert seen["boot"]["log"].endswith("engine.log")


def test_orphan_spawn_failure_removes_boot_file(_isolate_scubiee_home: Path, monkeypatch):
    import pipeline.daemon as d

    monkeypatch.setattr(
        "pipeline.process_job.windows_wmi_create_process",
        lambda *_a, **_k: {"ok": False, "error": "denied"},
    )
    out = d._spawn_engine_orphan(["py", "-u", "-m", "pipeline", "engine", "run"], {}, cwd=".")
    assert out["ok"] is False
    assert not list(_isolate_scubiee_home.glob("_boot_engine_*.json"))


def _stub_start_daemon_env(monkeypatch, home: Path):
    import pipeline.daemon as d

    monkeypatch.setattr(d, "is_running", lambda: False)
    monkeypatch.setattr("pipeline.install_guard.check_install_conflict", lambda: None)
    monkeypatch.setattr("pipeline.install_guard.write_install_marker", lambda: None)
    monkeypatch.setattr("pipeline.watchdog.ensure_watchdog_sidecar", lambda: {"ok": True})
    return d


def test_start_daemon_prefers_orphan_spawn(_isolate_scubiee_home: Path, monkeypatch, tmp_path):
    d = _stub_start_daemon_env(monkeypatch, _isolate_scubiee_home)
    monkeypatch.setenv("CTX_ENGINE_ORPHAN_SPAWN", "1")
    monkeypatch.setattr(d.os, "name", "nt")
    monkeypatch.setattr(d, "_spawn_engine_orphan", lambda *_a, **_k: {"ok": True, "pid": 31337})

    def _no_popen(*_a, **_k):
        raise AssertionError("Popen must not run when the orphan spawn worked")

    monkeypatch.setattr(d, "_spawn_engine_child", _no_popen)
    out = d.start_daemon(tmp_path, wait_s=0)
    assert out["ok"] and out["pid"] == 31337
    assert d.pid_path().read_text(encoding="utf-8").strip() == "31337"


def test_start_daemon_falls_back_and_says_so(_isolate_scubiee_home: Path, monkeypatch, tmp_path):
    d = _stub_start_daemon_env(monkeypatch, _isolate_scubiee_home)
    monkeypatch.setenv("CTX_ENGINE_ORPHAN_SPAWN", "1")
    monkeypatch.setattr(d.os, "name", "nt")
    monkeypatch.setattr(d, "_spawn_engine_orphan", lambda *_a, **_k: {"ok": False, "error": "pywin32_missing"})
    monkeypatch.setattr(d, "_spawn_engine_child", lambda *_a, **_k: 4444)
    out = d.start_daemon(tmp_path, wait_s=0)
    assert out["pid"] == 4444
    log = (_isolate_scubiee_home / "engine.log").read_text(encoding="utf-8")
    assert "WMI orphan spawn failed (pywin32_missing)" in log


def test_engine_boot_applies_env_and_deletes_file(tmp_path, monkeypatch):
    import pipeline.engine_boot as boot

    f = tmp_path / "_boot_engine_x.json"
    f.write_text(json.dumps({"env": {"CTX_UNIT_BOOT": "yes"}, "log": ""}), encoding="utf-8")
    ran: dict = {}
    monkeypatch.setattr(boot.runpy, "run_module", lambda name, **kw: ran.update(name=name, argv=list(sys.argv)))
    monkeypatch.delenv("CTX_UNIT_BOOT", raising=False)
    boot.main([str(f), "engine", "run", "C:/repo"])
    assert ran["name"] == "pipeline" and ran["argv"][1:] == ["engine", "run", "C:/repo"]
    assert boot.os.environ["CTX_UNIT_BOOT"] == "yes"
    assert boot.os.environ["CTX_ENGINE_SPAWN_METHOD"] == "wmi"
    assert not f.exists()
    monkeypatch.delenv("CTX_UNIT_BOOT", raising=False)


def test_reaper_tree_kill_spares_engine_and_watchdog(monkeypatch):
    import pipeline.process_control as pc

    killed: list[int] = []

    class _Child:
        def __init__(self, pid, cmd):
            self.pid = pid
            self._cmd = cmd

        def cmdline(self):
            return self._cmd

        def kill(self):
            killed.append(self.pid)

    class _Proc(_Child):
        def children(self, recursive=True):
            return [
                _Child(11, ["pythonw.exe", "-u", "-m", "pipeline.mcp_locate"]),
                _Child(12, ["pythonw.exe", "-u", "-m", "pipeline", "engine", "run", "C:/repo"]),
                _Child(13, ["pythonw.exe", r"C:\Users\u\.scubiee\_boot_watchdog.pyw"]),
            ]

    import psutil

    monkeypatch.setattr(psutil, "Process", lambda pid: _Proc(pid, ["pythonw.exe", "-m", "pipeline.mcp_bridge"]))
    monkeypatch.setattr(pc, "_pid_in_our_ancestry", lambda *_a, **_k: False)
    pc._terminate_pid_no_tree(10)
    assert killed == [11, 10]


def test_bridge_kill_job_allows_breakaway(monkeypatch):
    import pipeline.process_job as pj

    seen: dict = {}
    monkeypatch.setattr(pj.os, "name", "nt")
    monkeypatch.setattr(pj, "_windows_assign", lambda **kw: seen.update(kw) or {"ok": True})
    pj.attach_mcp_kill_job()
    assert seen["kill_on_close"] is True and seen["breakaway_ok"] is True


def test_hard_exit_logs_reason_then_exits(_isolate_scubiee_home: Path, monkeypatch):
    import pipeline.engine_log as el

    class _Exit(Exception):
        pass

    def _fake_exit(code):
        raise _Exit(code)

    monkeypatch.setenv("CTX_ENGINE_EXIT_TERMINATE", "0")  # never TerminateProcess the test runner
    monkeypatch.delenv("CTX_SCUBIEE_ROLE", raising=False)
    monkeypatch.setattr(el.os, "_exit", _fake_exit)
    with pytest.raises(_Exit):
        el.hard_exit(0, reason="retire_self_idle_standby")
    log = (_isolate_scubiee_home / "engine.log").read_text(encoding="utf-8")
    assert "reason=retire_self_idle_standby method=self_terminate" in log


def test_http_handle_error_quiet_on_client_disconnect(capsys):
    from pipeline.server import EngineHTTPServer

    server = EngineHTTPServer.__new__(EngineHTTPServer)  # no socket bind
    try:
        raise ConnectionAbortedError(10053, "aborted")
    except ConnectionAbortedError:
        server.handle_error(None, ("127.0.0.1", 61288))
    err = capsys.readouterr().err
    assert err.strip() == "[http] client gone mid-response: ConnectionAbortedError port=61288"
    assert "Traceback" not in err


def test_http_handle_error_keeps_real_errors(capsys):
    from pipeline.server import EngineHTTPServer

    server = EngineHTTPServer.__new__(EngineHTTPServer)
    try:
        raise ValueError("real bug")
    except ValueError:
        server.handle_error(None, ("127.0.0.1", 1))
    err = capsys.readouterr().err
    assert "Traceback" in err and "ValueError: real bug" in err


def test_prewarm_async_while_running_does_not_deadlock(monkeypatch):
    """A second prewarm request during a running prewarm used to self-deadlock.

    It held _PREWARM_LOCK and called prewarm_status(), which takes the same
    (non-reentrant) lock; every /health then blocked on it forever (py-spy on a
    live engine: 99 handler threads in prewarm_status). The watchdog read that
    as a hung engine and restarted it.
    """
    import threading

    import pipeline.engine as eng

    monkeypatch.setattr(eng, "_prewarm_enabled", lambda: True)
    monkeypatch.setattr(eng, "embedder_is_loaded", lambda: False)
    monkeypatch.setitem(eng._PREWARM_STATE, "running", True)
    box: dict = {}
    t = threading.Thread(target=lambda: box.update(out=eng.prewarm_embedder_async(None)), daemon=True)
    t.start()
    t.join(2.0)
    assert not t.is_alive(), "prewarm_embedder_async deadlocked on _PREWARM_LOCK"
    assert box["out"]["already_running"] is True
    h = threading.Thread(target=lambda: box.update(status=eng.prewarm_status()), daemon=True)
    h.start()
    h.join(2.0)
    assert not h.is_alive() and box["status"]["running"] is True


def test_quiesce_inside_engine_never_stops_engine_or_watchdog(monkeypatch):
    """load_engine -> heal_checksum_mismatch -> index_repo used to quiesce the
    running engine: it stopped the watchdog, then itself (live [stop] audit:
    by=engine at=...store_lock.quiesce_background_indexing<indexer.index_repo)."""
    import pipeline.store_lock as sl

    calls: list[str] = []
    monkeypatch.setattr("pipeline.watchdog.stop_watchdog", lambda **_k: calls.append("watchdog"))
    monkeypatch.setattr("pipeline.daemon.stop_daemon", lambda **_k: calls.append("daemon"))
    monkeypatch.setattr(
        "pipeline.process_control.stop_engine_worker_processes",
        lambda **_k: calls.append("workers") or {"ok": True},
    )
    monkeypatch.setattr(sl.time, "sleep", lambda _s: None)
    monkeypatch.setenv("CTX_SCUBIEE_ROLE", "engine")
    out = sl.quiesce_background_indexing()
    assert out["skipped"] == "in_process_daemon" and calls == []
    monkeypatch.delenv("CTX_SCUBIEE_ROLE")
    sl.quiesce_background_indexing()
    assert calls == ["watchdog", "daemon", "workers"]
