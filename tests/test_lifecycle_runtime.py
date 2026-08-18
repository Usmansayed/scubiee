"""Autonomous desktop lifecycle: standby, idle stop, logon autostart."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pipeline import lifecycle_runtime as life


def test_standby_does_not_idle_stop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "1")
    life.set_desired_mode(life.DESIRED_STANDBY)
    life.save_policy({**life.load_policy(), "last_activity": 1.0})
    assert life.engine_should_be_running() is False
    assert life.should_idle_stop(now=10_000.0) is False


def test_run_mode_idles_after_quiet_period(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "30")
    life.note_activity(now=100.0)
    assert life.engine_should_be_running() is True
    assert life.should_idle_stop(now=129.0) is False
    assert life.should_idle_stop(now=131.0) is True


def test_active_client_blocks_idle_stop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "30")
    monkeypatch.setattr(life, "_pid_alive", lambda pid: pid == 4242)
    life.note_activity(now=100.0)
    life.register_client("mcp:4242", pid=4242, now=100.0)
    assert life.should_idle_stop(now=200.0) is False


def test_idle_after_last_client_disconnects(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "120")
    life.register_client("mcp:1", pid=1, now=100.0)
    life.unregister_client("mcp:1", now=100.0)
    assert life.should_idle_stop(now=219.0) is False
    assert life.should_idle_stop(now=221.0) is True


def test_reconcile_dead_client_marks_disconnect(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setattr(life, "_pid_alive", lambda _pid: False)
    life.register_client("mcp:9999", pid=9999, now=50.0)
    assert life.reconcile_clients(now=60.0) == []
    policy = life.load_policy()
    assert policy["last_client_left_at"] == 60.0


def test_zero_idle_never_stops(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "0")
    life.note_activity(now=1.0)
    assert life.should_idle_stop(now=1_000_000.0) is False


def test_register_logon_autostart_uses_onlogon_task(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setattr(life, "current_desktop", lambda: "windows")
    seen: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        seen.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    result = life.register_logon_autostart(
        runner=fake_run, python=r"C:\Python\python.exe"
    )
    assert result["ok"] is True
    create = seen[0]
    assert create[:2] == ["schtasks", "/Create"]
    assert "ONLOGON" in create
    assert life.TASK_NAME in create
    assert "supervisor" in " ".join(create).lower()
    assert "--logon" in " ".join(create)


def test_install_session_runtime_does_not_start_engine(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    started: list[str] = []

    monkeypatch.setattr(
        life,
        "register_logon_autostart",
        lambda **_kwargs: {"ok": True, "task": "ContextEngineSupervisor"},
    )
    monkeypatch.setattr(
        life,
        "ensure_supervisor",
        lambda: {"ok": True, "already_running": False, "started": True},
    )
    monkeypatch.setattr(
        "pipeline.daemon.start_daemon",
        lambda *_args, **_kwargs: started.append("engine") or {"ok": True},
    )
    out = life.install_session_runtime()
    assert out["ok"] is True
    assert started == []
    assert life.engine_should_be_running() is False


def test_install_session_runtime_ok_when_logon_task_is_denied(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setattr(
        life,
        "register_logon_autostart",
        lambda **_kwargs: {
            "ok": False,
            "platform": "windows",
            "detail": "ERROR: Access is denied.\n",
        },
    )
    monkeypatch.setattr(
        life,
        "ensure_supervisor",
        lambda: {"ok": True, "started": True, "pid": 19428},
    )
    out = life.install_session_runtime()
    assert out["ok"] is True
    assert out["supervisor"]["ok"] is True
    assert out["autostart"]["ok"] is False
    assert out.get("warning")


def test_windows_autostart_falls_back_to_run_key_on_access_denied(
    monkeypatch,
) -> None:
    monkeypatch.setattr(life, "current_desktop", lambda: "windows")
    written: dict[str, str] = {}

    def fake_run(cmd, **_kwargs):
        del cmd
        return SimpleNamespace(
            returncode=1, stdout="", stderr="ERROR: Access is denied.\n"
        )

    def fake_write(command: str) -> bool:
        written["cmd"] = command
        return True

    monkeypatch.setattr(life, "_write_windows_run_key", fake_write)
    result = life.register_logon_autostart(
        runner=fake_run, python=r"C:\Python\python.exe"
    )
    assert result["ok"] is True
    assert result["method"] == "run_key"
    assert "supervisor" in written["cmd"].lower()


def test_ensure_supervisor_uses_watchdog_not_logon_task(monkeypatch) -> None:
    monkeypatch.setattr(life, "current_desktop", lambda: "windows")
    monkeypatch.setattr("pipeline.watchdog.is_watchdog_running", lambda: False)
    monkeypatch.setattr(
        "pipeline.watchdog.start_watchdog",
        lambda: {"ok": True, "started": True, "pid": 1},
    )
    seen: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        seen.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(life.subprocess, "run", fake_run)
    out = life.ensure_supervisor()
    assert out["ok"] is True
    assert seen == []


def test_unregister_logon_autostart_deletes_task(monkeypatch) -> None:
    monkeypatch.setattr(life, "current_desktop", lambda: "windows")

    def fake_run(cmd, **_kwargs):
        assert cmd[:2] == ["schtasks", "/Delete"]
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    assert life.unregister_logon_autostart(runner=fake_run)["ok"] is True


def test_darwin_register_writes_launch_agent_and_bootstraps(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setattr(life, "current_desktop", lambda: "darwin")
    monkeypatch.setattr(life, "_session_uid", lambda: 501)
    monkeypatch.setattr(life, "_user_home", lambda: tmp_path)
    seen: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        seen.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    result = life.register_logon_autostart(
        runner=fake_run, python="/usr/bin/python3"
    )
    plist = tmp_path / "Library" / "LaunchAgents" / f"{life.LAUNCH_AGENT_LABEL}.plist"
    assert result["ok"] is True
    assert result["platform"] == "darwin"
    assert plist.is_file()
    body = plist.read_text(encoding="utf-8")
    assert life.LAUNCH_AGENT_LABEL in body
    assert "supervisor" in body
    assert "--logon" in body
    assert "<key>RunAtLoad</key>" in body
    assert "<true/>" in body
    joined = " ".join(" ".join(cmd) for cmd in seen)
    assert "launchctl" in joined
    assert "bootstrap" in joined
    assert "gui/501" in joined


def test_darwin_unregister_bootout_and_removes_plist(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(life, "current_desktop", lambda: "darwin")
    monkeypatch.setattr(life, "_session_uid", lambda: 501)
    monkeypatch.setattr(life, "_user_home", lambda: tmp_path)
    plist = tmp_path / "Library" / "LaunchAgents" / f"{life.LAUNCH_AGENT_LABEL}.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text("stub\n", encoding="utf-8")
    seen: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        seen.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    out = life.unregister_logon_autostart(runner=fake_run)
    assert out["ok"] is True
    assert out["platform"] == "darwin"
    assert not plist.exists()
    assert seen[0][:2] == ["launchctl", "bootout"]
    assert f"gui/501/{life.LAUNCH_AGENT_LABEL}" in seen[0]


def test_linux_register_uses_xdg_autostart(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(life, "current_desktop", lambda: "linux")
    monkeypatch.setattr(life, "_user_home", lambda: tmp_path)
    result = life.register_logon_autostart(python="/usr/bin/python3")
    desktop = tmp_path / ".config" / "autostart" / "context-engine-supervisor.desktop"
    assert result["ok"] is True
    assert result["platform"] == "linux"
    assert desktop.is_file()
    assert "supervisor" in desktop.read_text(encoding="utf-8")


def test_supervisor_exit_handler_stops_engine(monkeypatch) -> None:
    stopped: list[bool] = []

    def fake_standby(*, stop_engine: bool = True):
        stopped.append(stop_engine)
        return {"ok": True}

    monkeypatch.setattr(life, "enter_standby", fake_standby)
    life.handle_supervisor_exit()
    assert stopped == [True]


def test_ensure_supervisor_on_darwin_kickstarts_agent_not_orphan(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setattr(life, "current_desktop", lambda: "darwin")
    monkeypatch.setattr(life, "_session_uid", lambda: 501)
    monkeypatch.setattr(life, "_user_home", lambda: tmp_path)
    monkeypatch.setattr(life.time, "sleep", lambda _s: None)
    plist = tmp_path / "Library" / "LaunchAgents" / f"{life.LAUNCH_AGENT_LABEL}.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text("stub\n", encoding="utf-8")
    spawned: list[str] = []
    seen: list[list[str]] = []
    running = [False]

    def is_running() -> bool:
        return running[0]

    def fake_run(cmd, **_kwargs):
        seen.append(list(cmd))
        running[0] = True
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("pipeline.watchdog.is_watchdog_running", is_running)
    monkeypatch.setattr(
        "pipeline.watchdog.start_watchdog",
        lambda: spawned.append("watchdog") or {"ok": True, "started": True},
    )
    monkeypatch.setattr(life.subprocess, "run", fake_run)
    out = life.ensure_supervisor()
    assert out["ok"] is True
    assert spawned == []
    assert seen[0][:2] == ["launchctl", "kickstart"]

