"""Autonomous desktop policy: standby vs run, idle stop, logon autostart.

The user-facing contract is setup-once then `scubiee init`. This module is the
machine-side policy that keeps the engine off until work, and off again when
idle, without fighting the watchdog.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

TASK_NAME = "ContextEngineSupervisor"
LAUNCH_AGENT_LABEL = "com.contextengine.supervisor"
POLICY_NAME = "lifecycle_policy.json"
CLIENTS_NAME = "active_clients.json"
DEFAULT_IDLE_S = 60.0
DESIRED_RUN = "run"
DESIRED_STANDBY = "standby"


def _home() -> Path:
    from pipeline.project_id import context_engine_home

    return context_engine_home()


def _user_home() -> Path:
    return Path.home()


def _session_uid() -> int:
    getter = getattr(os, "getuid", None)
    if callable(getter):
        return int(getter())
    return 0


def current_desktop() -> str:
    if os.name == "nt" or sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def policy_path() -> Path:
    return _home() / POLICY_NAME


def clients_path() -> Path:
    return _home() / CLIENTS_NAME


def idle_seconds() -> float:
    raw = os.environ.get("CTX_ENGINE_IDLE_S")
    if raw is None or raw.strip() == "":
        return DEFAULT_IDLE_S
    try:
        return max(0.0, float(raw))
    except ValueError:
        return DEFAULT_IDLE_S


def load_policy() -> dict[str, Any]:
    path = policy_path()
    if not path.is_file():
        return {
            "desired_mode": DESIRED_STANDBY,
            "idle_s": idle_seconds(),
            "last_activity": None,
            "last_client_left_at": None,
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {
        "desired_mode": data.get("desired_mode") or DESIRED_STANDBY,
        "idle_s": idle_seconds(),
        "last_activity": data.get("last_activity"),
        "last_client_left_at": data.get("last_client_left_at"),
    }


def save_policy(policy: dict[str, Any]) -> dict[str, Any]:
    from pipeline.artifact_guard import atomic_write_text

    document = {
        "desired_mode": policy.get("desired_mode") or DESIRED_STANDBY,
        "idle_s": idle_seconds(),
        "last_activity": policy.get("last_activity"),
        "last_client_left_at": policy.get("last_client_left_at"),
    }
    _home().mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        policy_path(),
        json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
    )
    return document


def set_desired_mode(mode: str) -> dict[str, Any]:
    if mode not in {DESIRED_RUN, DESIRED_STANDBY}:
        raise ValueError(f"unknown desired mode {mode}")
    policy = load_policy()
    policy["desired_mode"] = mode
    return save_policy(policy)


def note_activity(*, now: float | None = None) -> dict[str, Any]:
    """Mark engine use. Clears stale disconnect anchors so HTTP/CLI activity
    keeps the idle clock honest (search/status must not race a prior client leave).
    """
    policy = load_policy()
    current = time.time() if now is None else now
    policy["desired_mode"] = DESIRED_RUN
    policy["last_activity"] = current
    # Activity after the last client left means the engine is in use again —
    # do not idle-stop off a stale last_client_left_at.
    policy["last_client_left_at"] = None
    return save_policy(policy)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except Exception:  # noqa: BLE001
        return False


def load_clients() -> dict[str, Any]:
    path = clients_path()
    if not path.is_file():
        return {"clients": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"clients": {}}
    if not isinstance(data, dict):
        return {"clients": {}}
    clients = data.get("clients")
    if not isinstance(clients, dict):
        clients = {}
    return {"clients": clients}


def save_clients(data: dict[str, Any]) -> dict[str, Any]:
    from pipeline.artifact_guard import atomic_write_text

    document = {"clients": data.get("clients") if isinstance(data.get("clients"), dict) else {}}
    _home().mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        clients_path(),
        json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
    )
    return document


def _mark_clients_gone(*, now: float | None = None) -> None:
    policy = load_policy()
    policy["last_client_left_at"] = time.time() if now is None else now
    save_policy(policy)


def register_client(
    client_id: str,
    *,
    pid: int | None = None,
    kind: str = "mcp",
    now: float | None = None,
) -> dict[str, Any]:
    """Track an IDE/MCP/CLI front-end so idle unload waits for disconnect."""
    current = time.time() if now is None else now
    owner = int(pid if pid is not None else os.getpid())
    data = load_clients()
    clients = data.setdefault("clients", {})
    clients[str(client_id)] = {
        "client_id": str(client_id),
        "pid": owner,
        "kind": str(kind or "mcp"),
        "registered_at": current,
        "last_seen_at": current,
    }
    save_clients(data)
    policy = load_policy()
    policy["desired_mode"] = DESIRED_RUN
    policy["last_activity"] = current
    policy["last_client_left_at"] = None
    save_policy(policy)
    return {
        "ok": True,
        "client_id": str(client_id),
        "active_clients": len(clients),
    }


def unregister_client(client_id: str, *, now: float | None = None) -> dict[str, Any]:
    data = load_clients()
    clients = data.setdefault("clients", {})
    clients.pop(str(client_id), None)
    save_clients(data)
    remaining = len(clients)
    if remaining == 0:
        _mark_clients_gone(now=now)
    return {
        "ok": True,
        "client_id": str(client_id),
        "active_clients": remaining,
    }


def reconcile_clients(*, now: float | None = None) -> list[dict[str, Any]]:
    """Drop dead client PIDs; record when the last live client disappears."""
    data = load_clients()
    clients = data.get("clients")
    clients = clients if isinstance(clients, dict) else {}
    before = len(clients)
    alive: dict[str, Any] = {}
    for client_id, meta in clients.items():
        if not isinstance(meta, dict):
            continue
        pid = int(meta.get("pid") or 0)
        if _pid_alive(pid):
            alive[str(client_id)] = meta
    data["clients"] = alive
    save_clients(data)
    if before > 0 and not alive:
        _mark_clients_gone(now=now)
    return [dict(item) for item in alive.values()]


def active_client_count() -> int:
    return len(reconcile_clients())


def should_idle_stop(*, now: float | None = None) -> bool:
    policy = load_policy()
    if policy.get("desired_mode") != DESIRED_RUN:
        return False
    idle_s = idle_seconds()
    if idle_s <= 0:
        return False
    current = time.time() if now is None else now
    if reconcile_clients(now=current):
        return False
    policy = load_policy()
    last_left = policy.get("last_client_left_at")
    last_activity = policy.get("last_activity")
    # Use the most recent signal of use. Preferring only last_client_left_at
    # ignored search/health activity and killed warm engines mid-session.
    candidates = [float(x) for x in (last_left, last_activity) if x is not None]
    if not candidates:
        return False
    return (current - max(candidates)) >= idle_s


def apply_idle_policy(*, now: float | None = None) -> dict[str, Any]:
    """Stop the engine after the idle window once clients are gone."""
    from pipeline.daemon import is_running

    if load_policy().get("desired_mode") == DESIRED_STANDBY:
        return {"ok": True, "action": "already_standby"}
    if not should_idle_stop(now=now):
        return {"ok": True, "action": "none"}
    running = is_running()
    result = enter_standby(stop_engine=running)
    return {**result, "action": "standby" if running else "policy_only"}


def engine_should_be_running() -> bool:
    from pipeline.pause_resume import is_paused

    if is_paused():
        return False
    return load_policy().get("desired_mode") == DESIRED_RUN


def supervisor_command(*, python: str | None = None, logon: bool = True) -> list[str]:
    exe = python or sys.executable
    cmd = [os.path.abspath(str(exe)), "-u", "-m", "pipeline", "engine", "supervisor"]
    if logon:
        cmd.append("--logon")
    return cmd


def launch_agent_plist_path() -> Path:
    return _user_home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _launch_agent_plist(cmd: list[str]) -> str:
    args = "\n".join(f"    <string>{_xml_escape(part)}</string>" for part in cmd)
    log = _user_home() / "Library" / "Logs" / "scubiee-supervisor.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log_s = _xml_escape(str(log))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        "  <key>Label</key>\n"
        f"  <string>{LAUNCH_AGENT_LABEL}</string>\n"
        "  <key>ProgramArguments</key>\n"
        "  <array>\n"
        f"{args}\n"
        "  </array>\n"
        "  <key>RunAtLoad</key>\n"
        "  <true/>\n"
        "  <key>KeepAlive</key>\n"
        "  <true/>\n"
        "  <key>ThrottleInterval</key>\n"
        "  <integer>15</integer>\n"
        "  <key>LimitLoadToSessionType</key>\n"
        "  <string>Aqua</string>\n"
        "  <key>ProcessType</key>\n"
        "  <string>Background</string>\n"
        "  <key>EnvironmentVariables</key>\n"
        "  <dict>\n"
        "    <key>PYTHONUTF8</key>\n"
        "    <string>1</string>\n"
        "  </dict>\n"
        "  <key>StandardOutPath</key>\n"
        f"  <string>{log_s}</string>\n"
        "  <key>StandardErrorPath</key>\n"
        f"  <string>{log_s}</string>\n"
        "</dict>\n"
        "</plist>\n"
    )


def _gui_target() -> str:
    return f"gui/{_session_uid()}/{LAUNCH_AGENT_LABEL}"


def _write_windows_run_key(command: str) -> bool:
    """User-level logon fallback when schtasks is denied."""
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, TASK_NAME, 0, winreg.REG_SZ, command)
        return True
    except OSError:
        return False


def _delete_windows_run_key() -> None:
    try:
        import winreg
    except ImportError:
        return
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, TASK_NAME)
    except OSError:
        return


def _register_windows(cmd: list[str], *, runner: Any) -> dict[str, Any]:
    quoted = subprocess.list2cmdline(cmd)
    completed = runner(
        [
            "schtasks",
            "/Create",
            "/TN",
            TASK_NAME,
            "/TR",
            quoted,
            "/SC",
            "ONLOGON",
            "/RL",
            "LIMITED",
            "/F",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    ok = getattr(completed, "returncode", 1) == 0
    detail = getattr(completed, "stdout", "") or getattr(completed, "stderr", "")
    if ok:
        return {
            "ok": True,
            "method": "schtasks",
            "platform": "windows",
            "task": TASK_NAME,
            "command": cmd,
            "detail": detail,
        }
    if _write_windows_run_key(quoted):
        return {
            "ok": True,
            "method": "run_key",
            "platform": "windows",
            "task": TASK_NAME,
            "command": cmd,
            "detail": "schtasks denied; registered HKCU Run instead",
        }
    return {
        "ok": False,
        "optional": True,
        "method": "none",
        "platform": "windows",
        "task": TASK_NAME,
        "command": cmd,
        "detail": detail or "Access is denied",
    }


def _register_darwin(cmd: list[str], *, runner: Any) -> dict[str, Any]:
    plist = launch_agent_plist_path()
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text(_launch_agent_plist(cmd), encoding="utf-8")
    domain = f"gui/{_session_uid()}"
    runner(
        ["launchctl", "bootout", f"{domain}/{LAUNCH_AGENT_LABEL}"],
        capture_output=True,
        text=True,
        check=False,
    )
    loaded = runner(
        ["launchctl", "bootstrap", domain, str(plist)],
        capture_output=True,
        text=True,
        check=False,
    )
    if getattr(loaded, "returncode", 1) != 0:
        loaded = runner(
            ["launchctl", "load", "-w", str(plist)],
            capture_output=True,
            text=True,
            check=False,
        )
    ok = getattr(loaded, "returncode", 1) == 0
    return {
        "ok": ok,
        "platform": "darwin",
        "task": str(plist),
        "command": cmd,
        "detail": getattr(loaded, "stdout", "") or getattr(loaded, "stderr", ""),
    }


def _register_linux(cmd: list[str]) -> dict[str, Any]:
    """Register autostart on Linux via both XDG desktop entry and systemd user service.

    XDG autostart works on desktop (GNOME/KDE).
    systemd user service works on headless/server (common for CUDA workstations).
    """
    results: dict[str, Any] = {"ok": True, "platform": "linux", "command": cmd}

    # 1. XDG desktop autostart (GUI sessions)
    desktop_dir = _user_home() / ".config" / "autostart"
    desktop_dir.mkdir(parents=True, exist_ok=True)
    desktop = desktop_dir / "scubiee-supervisor.desktop"
    exec_line = " ".join(f'"{part}"' if " " in part else part for part in cmd)
    desktop.write_text(
        "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                "Name=Scubiee Supervisor",
                "X-GNOME-Autostart-enabled=true",
                f"Exec={exec_line}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    results["xdg_desktop"] = str(desktop)

    # 2. systemd user service (headless + desktop, survives terminal close)
    systemd_dir = _user_home() / ".config" / "systemd" / "user"
    systemd_dir.mkdir(parents=True, exist_ok=True)
    service_file = systemd_dir / "scubiee.service"
    python_bin = cmd[0] if cmd else sys.executable
    service_content = f"""\
[Unit]
Description=Scubiee daemon supervisor
After=default.target

[Service]
Type=simple
ExecStart={exec_line}
Restart=on-failure
RestartSec=5
Environment=TOKENIZERS_PARALLELISM=false

[Install]
WantedBy=default.target
"""
    service_file.write_text(service_content, encoding="utf-8")
    results["systemd_service"] = str(service_file)

    # Enable the service (best-effort — systemctl may not be available)
    try:
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            capture_output=True, check=False, timeout=10,
        )
        subprocess.run(
            ["systemctl", "--user", "enable", "scubiee.service"],
            capture_output=True, check=False, timeout=10,
        )
        subprocess.run(
            ["systemctl", "--user", "start", "scubiee.service"],
            capture_output=True, check=False, timeout=10,
        )
        results["systemd_enabled"] = True
    except (FileNotFoundError, OSError):
        # systemctl not available (minimal container, old distro)
        results["systemd_enabled"] = False

    results["task"] = str(service_file)
    return results


def register_logon_autostart(
    *,
    runner: Any | None = None,
    python: str | None = None,
) -> dict[str, Any]:
    """Register a user-logon task that starts the supervisor (not the GPU engine)."""
    run = runner or subprocess.run
    cmd = supervisor_command(python=python)
    desktop = current_desktop()
    if desktop == "windows":
        return _register_windows(cmd, runner=run)
    if desktop == "darwin":
        return _register_darwin(cmd, runner=run)
    return _register_linux(cmd)


def unregister_logon_autostart(*, runner: Any | None = None) -> dict[str, Any]:
    run = runner or subprocess.run
    desktop = current_desktop()
    if desktop == "windows":
        completed = run(
            ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        _delete_windows_run_key()
        return {
            "ok": getattr(completed, "returncode", 1) == 0,
            "platform": "windows",
            "task": TASK_NAME,
        }
    if desktop == "darwin":
        run(
            ["launchctl", "bootout", _gui_target()],
            capture_output=True,
            text=True,
            check=False,
        )
        plist = launch_agent_plist_path()
        plist.unlink(missing_ok=True)
        return {"ok": True, "platform": "darwin", "task": str(plist)}
    desktop_file = (
        _user_home() / ".config" / "autostart" / "scubiee-supervisor.desktop"
    )
    desktop_file.unlink(missing_ok=True)
    return {"ok": True, "platform": "linux", "task": str(desktop_file)}


def kickstart_launch_agent(*, runner: Any | None = None) -> dict[str, Any]:
    run = runner or subprocess.run
    completed = run(
        ["launchctl", "kickstart", _gui_target()],
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "ok": getattr(completed, "returncode", 1) == 0,
        "platform": "darwin",
        "task": _gui_target(),
    }


def handle_supervisor_exit(signum: int | None = None, frame: Any = None) -> None:
    """Logoff / Ctrl+C / launchd stop: engine must not outlive the session."""
    del frame
    try:
        enter_standby(stop_engine=True)
    except Exception:  # noqa: BLE001
        pass
    if signum is not None:
        raise SystemExit(0)


def install_supervisor_signals() -> None:
    import signal

    signal.signal(signal.SIGTERM, handle_supervisor_exit)
    signal.signal(signal.SIGINT, handle_supervisor_exit)
    sighup = getattr(signal, "SIGHUP", None)
    if sighup is not None:
        signal.signal(sighup, handle_supervisor_exit)


def enter_standby(*, stop_engine: bool = True) -> dict[str, Any]:
    """Logon / idle: keep supervisor, do not keep a warm engine."""
    policy = set_desired_mode(DESIRED_STANDBY)
    stopped = None
    if stop_engine:
        from pipeline.daemon import is_running, stop_daemon

        if is_running():
            stopped = stop_daemon()
    return {"ok": True, "policy": policy, "engine": stopped}


def request_run(*, repo: Path | str | None = None) -> dict[str, Any]:
    """User work is about to happen: engine is allowed to exist."""
    note_activity()
    from pipeline.daemon import ensure_daemon

    return ensure_daemon(repo)


def ensure_supervisor() -> dict[str, Any]:
    """Keep a supervisor in this session. Never uses the --logon path.

    Windows/Linux fall back to an in-session watchdog. Darwin prefers the
    LaunchAgent so logout can SIGTERM the supervisor and stop the engine.
    """
    from pipeline.watchdog import is_watchdog_running, start_watchdog, watchdog_status

    if is_watchdog_running():
        return {"ok": True, "already_running": True, **watchdog_status()}
    if current_desktop() == "darwin" and launch_agent_plist_path().is_file():
        kicked = kickstart_launch_agent()
        time.sleep(0.4)
        if is_watchdog_running():
            return {"ok": True, "started": "launch_agent", **kicked, **watchdog_status()}
    return start_watchdog()


def run_supervisor(*, logon: bool = False) -> None:
    """Blocking supervisor used by the logon task and `scubiee engine supervisor`."""
    from pipeline.process_job import attach_supervisor_job
    from pipeline.watchdog import watchdog_loop

    install_supervisor_signals()
    if logon and (not engine_should_be_running() or should_idle_stop()):
        enter_standby(stop_engine=True)
    attach_supervisor_job()
    watchdog_loop()


def install_session_runtime() -> dict[str, Any]:
    """Machine install tail: logon task + current-session supervisor, no GPU."""
    registered = register_logon_autostart()
    supervisor = ensure_supervisor()
    if not engine_should_be_running():
        set_desired_mode(DESIRED_STANDBY)
    supervisor_ok = bool(supervisor.get("ok"))
    warning = None
    if not registered.get("ok") and supervisor_ok:
        warning = (
            "logon autostart not registered; supervisor is running for this session"
        )
    return {
        "ok": supervisor_ok,
        "autostart": registered,
        "supervisor": supervisor,
        "policy": load_policy(),
        "warning": warning,
    }
