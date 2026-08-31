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
# After the last MCP/app client leaves, wait this long before stopping the engine.
# Also used as the start/stop transition debounce so accidental spam cannot thrash.
DEFAULT_IDLE_S = 25.0
DEFAULT_TRANSITION_DEBOUNCE_S = 25.0
DESIRED_RUN = "run"
DESIRED_STANDBY = "standby"
TRANSITION_NAME = "engine_transition.json"
# Why the engine last started/stopped — separates normal idle from upgrade/user paths.
TRANSITION_REASON_NORMAL = "normal"
TRANSITION_REASON_UPGRADE = "upgrade"
TRANSITION_REASON_USER = "user"
# If upgrade quiesce/rebind dies mid-flight, auto-clear so idle policy cannot stay blocked forever.
DEFAULT_UPGRADE_STALE_S = 600.0


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


def transition_debounce_seconds() -> float:
    """Min gap after a *normal* start before an automatic idle stop may fire (spam/hysteresis)."""
    raw = os.environ.get("CTX_ENGINE_TRANSITION_DEBOUNCE_S")
    if raw is None or raw.strip() == "":
        return idle_seconds() if idle_seconds() > 0 else DEFAULT_TRANSITION_DEBOUNCE_S
    try:
        return max(0.0, float(raw))
    except ValueError:
        return idle_seconds() if idle_seconds() > 0 else DEFAULT_TRANSITION_DEBOUNCE_S


def upgrade_stale_seconds() -> float:
    raw = os.environ.get("CTX_UPGRADE_STALE_S")
    if raw is None or raw.strip() == "":
        return DEFAULT_UPGRADE_STALE_S
    try:
        return max(30.0, float(raw))
    except ValueError:
        return DEFAULT_UPGRADE_STALE_S


def _upgrade_started_at(data: dict[str, Any] | None = None) -> float | None:
    document = load_transition() if data is None else _normalize_transition(data)
    raw = document.get("upgrade_started_at")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _upgrade_is_stale(*, now: float | None = None, data: dict[str, Any] | None = None) -> bool:
    started = _upgrade_started_at(data)
    if started is None:
        return False
    current = time.time() if now is None else now
    return (current - started) >= upgrade_stale_seconds()


def transition_path() -> Path:
    return _home() / TRANSITION_NAME


def load_transition() -> dict[str, Any]:
    path = transition_path()
    if not path.is_file():
        return _default_transition()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return _normalize_transition(data)


def _default_transition() -> dict[str, Any]:
    return {
        "last_start_at": None,
        "last_stop_at": None,
        "last_action": None,
        "last_start_reason": None,
        "last_stop_reason": None,
        "upgrade_in_progress": False,
        "upgrade_epoch": 0,
        "upgrade_started_at": None,
        "last_upgrade_at": None,
        "last_upgrade_version": None,
    }


def _normalize_transition(data: dict[str, Any]) -> dict[str, Any]:
    base = _default_transition()
    base.update(data)
    try:
        base["upgrade_epoch"] = int(base.get("upgrade_epoch") or 0)
    except (TypeError, ValueError):
        base["upgrade_epoch"] = 0
    base["upgrade_in_progress"] = bool(base.get("upgrade_in_progress"))
    return base


def save_transition(data: dict[str, Any]) -> dict[str, Any]:
    from pipeline.artifact_guard import atomic_write_text

    document = _normalize_transition(data)
    _home().mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        transition_path(),
        json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
    )
    return document


def upgrade_in_progress(*, now: float | None = None) -> bool:
    """True while package swap / daemon rebind is in flight (auto-clears when stale)."""
    data = load_transition()
    if not data.get("upgrade_in_progress"):
        return False
    if _upgrade_is_stale(now=now, data=data):
        abort_upgrade_transition(reason="stale_timeout", now=now)
        return False
    return True


def abort_upgrade_transition(
    *,
    reason: str = "aborted",
    now: float | None = None,
) -> dict[str, Any]:
    """Fail-safe: clear a stuck upgrade flag so normal idle policy can resume."""
    data = load_transition()
    if not data.get("upgrade_in_progress"):
        return {"ok": True, "action": "upgrade_not_in_progress"}
    current = time.time() if now is None else now
    data["upgrade_in_progress"] = False
    data["last_upgrade_abort_at"] = current
    data["last_upgrade_abort_reason"] = str(reason or "aborted")
    saved = save_transition(data)
    return {"ok": True, "action": "upgrade_aborted", "reason": reason, "transition": saved}


def clear_clients() -> dict[str, Any]:
    """Drop all registered front-end clients (upgrade quiesce / stale PID cleanup)."""
    return save_clients({"clients": {}})


def begin_upgrade_transition(
    *,
    version: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Enter upgrade path: force-stop allowed, idle debounce suspended."""
    current = time.time() if now is None else now
    data = load_transition()
    if data.get("upgrade_in_progress") and not _upgrade_is_stale(now=current, data=data):
        return {"ok": True, "action": "upgrade_begin_already", "transition": data}

    if data.get("upgrade_in_progress"):
        abort_upgrade_transition(reason="stale_replaced", now=current)
        data = load_transition()

    data["upgrade_in_progress"] = True
    data["upgrade_started_at"] = current
    data["upgrade_epoch"] = int(data.get("upgrade_epoch") or 0) + 1
    if version:
        data["last_upgrade_version"] = str(version)
    saved = save_transition(data)
    clear_clients()
    policy = load_policy()
    policy["desired_mode"] = DESIRED_RUN
    policy["last_client_left_at"] = None
    save_policy(policy)
    return {"ok": True, "action": "upgrade_begin", "transition": saved}


def complete_upgrade_transition(
    *,
    version: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Exit upgrade path: new daemon is authoritative; normal disconnect grace resumes."""
    current = time.time() if now is None else now
    data = load_transition()
    data["upgrade_in_progress"] = False
    data["last_upgrade_at"] = current
    if version:
        data["last_upgrade_version"] = str(version)
    data["last_start_at"] = current
    data["last_action"] = "start"
    data["last_start_reason"] = TRANSITION_REASON_UPGRADE
    data["last_stop_reason"] = TRANSITION_REASON_UPGRADE
    save_transition(data)
    policy = load_policy()
    policy["desired_mode"] = DESIRED_RUN
    policy["last_activity"] = current
    policy["last_client_left_at"] = None
    save_policy(policy)
    return {"ok": True, "action": "upgrade_complete", "transition": data}


def note_engine_transition(
    action: str,
    *,
    reason: str = TRANSITION_REASON_NORMAL,
    now: float | None = None,
) -> dict[str, Any]:
    """Record a completed start or stop for debounce bookkeeping."""
    current = time.time() if now is None else now
    data = load_transition()
    if action == "start":
        data["last_start_at"] = current
        data["last_action"] = "start"
        data["last_start_reason"] = str(reason or TRANSITION_REASON_NORMAL)
    elif action == "stop":
        data["last_stop_at"] = current
        data["last_action"] = "stop"
        data["last_stop_reason"] = str(reason or TRANSITION_REASON_NORMAL)
    else:
        raise ValueError(f"unknown transition action {action}")
    return save_transition(data)


def _transition_debounce_applies(data: dict[str, Any] | None = None) -> bool:
    """Anti-thrash debounce applies only to normal automatic idle stops."""
    document = load_transition() if data is None else _normalize_transition(data)
    if document.get("upgrade_in_progress"):
        return False
    reason = str(document.get("last_start_reason") or TRANSITION_REASON_NORMAL)
    if reason in {TRANSITION_REASON_UPGRADE, TRANSITION_REASON_USER}:
        return False
    return True


def idle_stop_debounced(*, now: float | None = None) -> dict[str, Any] | None:
    """Block automatic idle-stop if a normal start happened too recently (spam guard).

    Upgrade and explicit user stops bypass this — they use separate transition reasons.
    """
    if not _transition_debounce_applies():
        return None
    debounce = transition_debounce_seconds()
    if debounce <= 0:
        return None
    current = time.time() if now is None else now
    data = load_transition()
    last_start = data.get("last_start_at")
    if last_start is None:
        return None
    age = current - float(last_start)
    if age >= debounce:
        return None
    wait_s = round(debounce - age, 3)
    return {
        "ok": True,
        "blocked": True,
        "action": "stop",
        "reason": "transition_debounce",
        "wait_s": wait_s,
        "debounce_s": debounce,
        "hint": (
            f"Engine started {age:.1f}s ago; automatic stop waits "
            f"{wait_s:.1f}s more (debounce={debounce:.0f}s)."
        ),
    }


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
    """Mark interactive engine use (MCP tools, locate, CLI work).

    Passive polls (/status, /health, keeper) must not call this — they would
    prevent idle stop after MCP disconnect.
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


def _client_pid_trustworthy(meta: dict[str, Any]) -> bool:
    """Avoid false 'client connected' when a PID was reused by an unrelated process."""
    pid = int(meta.get("pid") or 0)
    if not _pid_alive(pid):
        return False
    kind = str(meta.get("kind") or "mcp").strip().lower()
    if kind not in {"mcp", "bridge"}:
        return True
    try:
        from pipeline.process_control import is_context_engine_process, process_cmdline

        if is_context_engine_process(pid):
            return True
        cmd = process_cmdline(pid)
        if not cmd:
            return _pid_alive(pid)
        blob = " ".join(str(part) for part in cmd).lower()
        markers = (
            "scubiee",
            "mcp-bridge",
            "mcp_bridge",
            "pipeline",
            "context-engine",
            "context_engine",
        )
        return any(marker in blob for marker in markers)
    except Exception:  # noqa: BLE001
        return _pid_alive(pid)


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
    reconcile_clients(now=current)
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


def touch_client(client_id: str, *, now: float | None = None) -> bool:
    """Refresh liveness for a registered front-end (best-effort)."""
    current = time.time() if now is None else now
    data = load_clients()
    clients = data.get("clients")
    clients = clients if isinstance(clients, dict) else {}
    meta = clients.get(str(client_id))
    if not isinstance(meta, dict):
        return False
    meta["last_seen_at"] = current
    save_clients(data)
    return True


def _client_last_seen_at(meta: dict[str, Any]) -> float | None:
    raw = meta.get("last_seen_at")
    if raw is None:
        raw = meta.get("registered_at")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _client_is_stale(meta: dict[str, Any], *, now: float | None = None) -> bool:
    """True when a live PID has not invoked MCP tools recently (zombie bridge)."""
    seen = _client_last_seen_at(meta)
    if seen is None:
        return False
    current = time.time() if now is None else now
    return (current - seen) >= idle_seconds()


def unregister_client(client_id: str, *, now: float | None = None) -> dict[str, Any]:
    data = load_clients()
    clients = data.setdefault("clients", {})
    clients.pop(str(client_id), None)
    save_clients(data)
    remaining = reconcile_clients(now=now)
    if not remaining:
        _mark_clients_gone(now=now)
    return {
        "ok": True,
        "client_id": str(client_id),
        "active_clients": len(remaining),
    }


def reconcile_clients(*, now: float | None = None) -> list[dict[str, Any]]:
    """Drop dead, untrusted, or stale client PIDs; record when the last disappears."""
    current = time.time() if now is None else now
    data = load_clients()
    clients = data.get("clients")
    clients = clients if isinstance(clients, dict) else {}
    before = len(clients)
    alive: dict[str, Any] = {}
    for client_id, meta in clients.items():
        if not isinstance(meta, dict):
            continue
        if not _client_pid_trustworthy(meta):
            continue
        if _client_is_stale(meta, now=current):
            continue
        alive[str(client_id)] = meta
    data["clients"] = alive
    save_clients(data)
    if before > 0 and not alive:
        _mark_clients_gone(now=current)
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
    # After MCP/IDE disconnect, anchor strictly on client-leave time so unrelated
    # stale last_activity cannot delay or accelerate shutdown incorrectly.
    if last_left is not None:
        return (current - float(last_left)) >= idle_s
    if last_activity is None:
        return False
    return (current - float(last_activity)) >= idle_s


def apply_idle_policy(*, now: float | None = None) -> dict[str, Any]:
    """Stop the engine after the idle window once clients are gone."""
    from pipeline.daemon import is_running

    if upgrade_in_progress(now=now):
        return {"ok": True, "action": "upgrade_in_progress"}
    if load_policy().get("desired_mode") == DESIRED_STANDBY:
        return {"ok": True, "action": "already_standby"}
    if not should_idle_stop(now=now):
        return {"ok": True, "action": "none"}
    blocked = idle_stop_debounced(now=now)
    if blocked is not None:
        return {**blocked, "action": "debounced"}
    if reconcile_clients(now=now):
        return {"ok": True, "action": "clients_reconnected"}
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
