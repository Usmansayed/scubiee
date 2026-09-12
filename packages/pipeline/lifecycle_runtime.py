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
# After the last MCP/IDE client disconnects, wait this long then unload RAM + stop
# the engine. While any client is connected (Cursor/Codex/…), keep everything warm —
# do not unload on "idle time" between tool calls.
DEFAULT_DISCONNECT_DEBOUNCE_S = 120.0
# Back-compat aliases (same knob).
DEFAULT_IDLE_S = DEFAULT_DISCONNECT_DEBOUNCE_S
DEFAULT_TRANSITION_DEBOUNCE_S = 5.0
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


def disconnect_debounce_seconds() -> float:
    """Grace after MCP/IDE disconnect before unloading embedder + stopping engine."""
    for key in ("CTX_DISCONNECT_DEBOUNCE_S", "CTX_ENGINE_IDLE_S", "CTX_EMBED_IDLE_DEMOTE_S"):
        raw = os.environ.get(key)
        if raw is None or str(raw).strip() == "":
            continue
        try:
            return max(0.0, float(raw))
        except ValueError:
            continue
    return DEFAULT_DISCONNECT_DEBOUNCE_S


# Short alias used by should_idle_stop / governor.
disconnect_debounce_s = disconnect_debounce_seconds


def idle_seconds() -> float:
    """Alias of disconnect debounce (legacy name used across idle-stop paths)."""
    return disconnect_debounce_seconds()

def transition_debounce_seconds() -> float:
    """Min gap after a *normal* start before an automatic idle stop may fire (spam/hysteresis)."""
    raw = os.environ.get("CTX_ENGINE_TRANSITION_DEBOUNCE_S")
    if raw is None or raw.strip() == "":
        return DEFAULT_TRANSITION_DEBOUNCE_S
    try:
        return max(0.0, float(raw))
    except ValueError:
        return DEFAULT_TRANSITION_DEBOUNCE_S


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

    Does **not** clear ``last_client_left_at``: unload is disconnect-driven.
    Re-registering an MCP/IDE client clears the leave stamp. Passive polls
    (/status, /health, keeper) must not call this.
    """
    policy = load_policy()
    current = time.time() if now is None else now
    policy["desired_mode"] = DESIRED_RUN
    policy["last_activity"] = current
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


def _lifecycle_log(event: str, **fields: Any) -> None:
    """Structured stderr so engine.log shows leave → debounce → stop → gone."""
    bits = " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)
    line = f"[lifecycle] {event} {bits}".rstrip()
    print(line, file=sys.stderr, flush=True)


def _mark_clients_gone(*, now: float | None = None) -> None:
    """Stamp disconnect time. Unload happens after ``disconnect_debounce_s`` (default 120s)."""
    stamp = time.time() if now is None else now
    policy = load_policy()
    policy["last_client_left_at"] = stamp
    save_policy(policy)
    _lifecycle_log(
        "debounce_arm",
        last_client_left_at=round(float(stamp), 3),
        wait_s=disconnect_debounce_seconds(),
    )


def _postpone_disconnect_stamp(*, now: float | None = None) -> None:
    """Keep an armed disconnect from firing the instant indexing/warming ends."""
    policy = load_policy()
    if policy.get("last_client_left_at") is None:
        return
    stamp = time.time() if now is None else now
    policy["last_client_left_at"] = float(stamp)
    save_policy(policy)


def mcp_host_from_client_id(client_id: str, *, kind: str = "mcp") -> str | None:
    """Extract host key from ids like ``mcp:cursor@proc-123`` or ``cursor@conn-…``."""
    if str(kind or "mcp").strip().lower() != "mcp":
        return None
    cid = str(client_id or "").strip()
    if not cid:
        return None
    if cid.startswith("mcp:"):
        cid = cid[4:]
    if "@" not in cid:
        return None
    host = cid.split("@", 1)[0].strip().lower()
    return host or None


def coalesce_mcp_clients(
    clients: dict[str, Any],
    *,
    keep_id: str,
    host: str | None,
) -> list[str]:
    """Drop older same-host MCP clients so idle policy tracks one primary per IDE."""
    if not host:
        return []
    dropped: list[str] = []
    for cid, meta in list(clients.items()):
        if str(cid) == str(keep_id):
            continue
        if not isinstance(meta, dict):
            clients.pop(cid, None)
            dropped.append(str(cid))
            continue
        other_host = mcp_host_from_client_id(
            str(cid), kind=str(meta.get("kind") or "mcp")
        )
        if other_host == host:
            clients.pop(cid, None)
            dropped.append(str(cid))
    return dropped


def register_client(
    client_id: str,
    *,
    pid: int | None = None,
    kind: str = "mcp",
    host: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Track an IDE/MCP/CLI front-end so idle unload waits for disconnect."""
    current = time.time() if now is None else now
    reconcile_clients(now=current)
    owner = int(pid if pid is not None else os.getpid())
    data = load_clients()
    clients = data.setdefault("clients", {})
    host_key = (host or "").strip().lower() or mcp_host_from_client_id(
        str(client_id), kind=kind
    )
    dropped = coalesce_mcp_clients(clients, keep_id=str(client_id), host=host_key)
    clients[str(client_id)] = {
        "client_id": str(client_id),
        "pid": owner,
        "kind": str(kind or "mcp"),
        "host": host_key,
        "registered_at": current,
        "last_seen_at": current,
    }
    save_clients(data)
    policy = load_policy()
    policy["desired_mode"] = DESIRED_RUN
    policy["last_activity"] = current
    policy["last_client_left_at"] = None
    save_policy(policy)
    # MCP/IDE attached → load FastEmbed NOW (block until ready), not on first map.
    try:
        from pipeline.memory_governor import get_governor

        get_governor().ensure_semantic_tier()
    except Exception:  # noqa: BLE001
        pass
    prewarm: dict[str, Any] | None = None
    try:
        from pipeline.engine import ensure_embedder_ready

        prewarm = ensure_embedder_ready(os.environ.get("CTX_REPO") or None)
    except Exception as exc:  # noqa: BLE001
        prewarm = {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "client_id": str(client_id),
        "active_clients": len(clients),
        "coalesced": dropped,
        "host": host_key,
        "prewarm": prewarm,
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
    """Evict only dead / untrusted PIDs — not quiet IDEs.

    While Cursor/Codex/etc. keep an MCP worker alive we hold the warm engine.
    Heartbeat refreshes ``last_seen_at`` for observability; unload is driven by
    disconnect (PID gone / unregister), not by tool-call silence.
    """
    if _client_pid_trustworthy(meta):
        return False
    # Dead or untrusted PID — drop immediately from the registry.
    return True


def unregister_client(client_id: str, *, now: float | None = None) -> dict[str, Any]:
    data = load_clients()
    clients = data.setdefault("clients", {})
    clients.pop(str(client_id), None)
    save_clients(data)
    remaining = reconcile_clients(now=now)
    if not remaining:
        _mark_clients_gone(now=now)
    _lifecycle_log(
        "client_left",
        client_id=str(client_id),
        remaining=len(remaining),
    )
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


def _idle_busy_reason() -> str | None:
    """Why idle stop must not fire (indexing / warming). None = idle OK."""
    try:
        from pipeline.memory_governor import get_governor

        if get_governor().indexing:
            return "indexing"
    except Exception:  # noqa: BLE001
        pass
    try:
        from pipeline.ce_service import get_context_engine

        ce = get_context_engine()
        warm = str(getattr(ce, "warm_state", "") or "").strip().lower()
        if warm in {"warming", "indexing"}:
            return f"warm_state:{warm}"
    except Exception:  # noqa: BLE001
        pass
    return None


def should_idle_stop(*, now: float | None = None, require_run_mode: bool = True) -> bool:
    """True after disconnect debounce (default 120s) with no active MCP/IDE clients.

    While any client is registered the engine stays up for fast map/sync —
    we do **not** unload on quiet tool-call idle.

    Also covers sticky ``desired_mode=run`` with **zero clients and no leave
    stamp** (CLI ``engine ensure`` / wipe leftovers): idle clock uses
    ``last_activity`` or last engine start so the watchdog cannot keep a
    ghost engine forever.
    """
    policy = load_policy()
    if require_run_mode and policy.get("desired_mode") != DESIRED_RUN:
        return False
    debounce = disconnect_debounce_s()
    # <=0 keeps legacy "never auto-stop" (disable unload).
    if debounce <= 0:
        return False
    if _idle_busy_reason() is not None:
        return False
    current = time.time() if now is None else now
    if reconcile_clients(now=current):
        return False
    policy = load_policy()
    if active_client_count() > 0:
        return False

    last_left = policy.get("last_client_left_at")
    if last_left is not None:
        # Reconnect: a start after the leave stamp is a new engine, not leftover idle.
        try:
            last_start = load_transition().get("last_start_at")
            if last_start is not None and float(last_start) > float(last_left):
                return False
        except (TypeError, ValueError):
            pass
        return (current - float(last_left)) >= debounce

    # No leave stamp + no clients: sticky run without MCP (CLI ensure).
    anchor = policy.get("last_activity")
    if anchor is None:
        try:
            anchor = load_transition().get("last_start_at")
        except Exception:  # noqa: BLE001
            anchor = None
    if anchor is None:
        return False
    try:
        return (current - float(anchor)) >= debounce
    except (TypeError, ValueError):
        return False



def apply_idle_policy(*, now: float | None = None, force: bool = False) -> dict[str, Any]:
    """After disconnect debounce: demote embedder + stop engine."""
    from pipeline.daemon import is_running

    if upgrade_in_progress(now=now):
        return {"ok": True, "action": "upgrade_in_progress"}
    busy = _idle_busy_reason()
    if busy is not None:
        _postpone_disconnect_stamp(now=now)
        return {"ok": True, "action": "busy", "reason": busy}
    running = is_running()
    if not running and load_policy().get("desired_mode") == DESIRED_STANDBY:
        sweep: dict[str, Any] | None = None
        try:
            from pipeline.process_control import sweep_orphan_scubiee_frontends

            sweep = sweep_orphan_scubiee_frontends()
        except Exception:  # noqa: BLE001
            sweep = None
        return {"ok": True, "action": "already_standby", "orphan_sweep": sweep}
    if not should_idle_stop(now=now, require_run_mode=False):
        return {"ok": True, "action": "none"}
    if not force:
        blocked = idle_stop_debounced(now=now)
        if blocked is not None:
            return {**blocked, "action": "debounced"}
    if reconcile_clients(now=now):
        return {"ok": True, "action": "clients_reconnected"}
    busy = _idle_busy_reason()
    if busy is not None:
        _postpone_disconnect_stamp(now=now)
        return {"ok": True, "action": "busy", "reason": busy}
    # Success metric is process exit (ORT RSS is not returned in-process).
    # Soft demote inside enter_standby is pre-exit cleanup only.
    _lifecycle_log(
        "standby_stop",
        running=running,
        debounce_s=disconnect_debounce_s(),
    )
    result = enter_standby(stop_engine=True)
    try:
        from pipeline.process_control import sweep_orphan_scubiee_frontends

        result["orphan_sweep"] = sweep_orphan_scubiee_frontends()
    except Exception as exc:  # noqa: BLE001
        result["orphan_sweep_error"] = str(exc)
    still = False
    try:
        still = is_running()
    except Exception:  # noqa: BLE001
        still = False
    _lifecycle_log("running", running=still)
    return {**result, "action": "standby"}


def engine_should_be_running() -> bool:
    from pipeline.pause_resume import is_paused

    if is_paused():
        return False
    if load_policy().get("desired_mode") == DESIRED_RUN:
        return True
    try:
        from pipeline.daemon import start_request_path

        return start_request_path().is_file()
    except Exception:  # noqa: BLE001
        return False


def supervisor_command(*, python: str | None = None, logon: bool = True) -> list[str]:
    # Prefer pythonw on Windows so Run-key / schtasks never open a console.
    if python:
        exe = python
    else:
        try:
            from pipeline.process_job import background_python

            exe = background_python()
        except Exception:  # noqa: BLE001
            exe = sys.executable
    cmd = [os.path.abspath(str(exe)), "-u", "-m", "pipeline", "engine", "supervisor"]
    if logon:
        cmd.append("--logon")
    return cmd


def windows_supervisor_boot_path() -> Path:
    from pipeline.project_id import context_engine_home

    return context_engine_home() / "_boot_supervisor.pyw"


def write_windows_supervisor_boot_script() -> Path:
    """Hidden logon boot (pythonw + .pyw) — never python.exe console."""
    from pipeline.project_id import context_engine_home

    home = context_engine_home()
    home.mkdir(parents=True, exist_ok=True)
    path = windows_supervisor_boot_path()
    path.write_text(
        "\n".join(
            [
                "import os",
                "os.environ.setdefault('CTX_ENGINE_SOFT_SPAWN', '1')",
                "os.environ.setdefault('PYTHONUTF8', '1')",
                "from pipeline.lifecycle_runtime import run_supervisor",
                "run_supervisor(logon=True)",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def windows_hidden_supervisor_command() -> list[str]:
    """Command line for HKCU Run / schtasks that cannot flash a console."""
    from pipeline.process_job import background_python

    boot = write_windows_supervisor_boot_script()
    return [background_python(), str(boot)]


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
    # Always register a no-console pythonw boot on Windows — even if the caller
    # passed a console python.exe command (old installs flashed every logon).
    try:
        quiet = windows_hidden_supervisor_command()
        quoted = subprocess.list2cmdline(quiet)
        cmd = quiet
    except Exception:  # noqa: BLE001
        quoted = subprocess.list2cmdline(cmd)

    def _run(argv: list[str]) -> Any:
        kwargs: dict[str, Any] = {
            "capture_output": True,
            "text": True,
            "check": False,
        }
        if os.name == "nt":
            kwargs["creationflags"] = int(
                getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            )
        return runner(argv, **kwargs)

    completed = _run(
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
        ]
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
            "detail": "schtasks denied; registered HKCU Run (pythonw, no console)",
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
    desktop = current_desktop()
    if desktop == "windows":
        def _run_default(argv: list[str], **kwargs: Any) -> Any:
            kwargs.setdefault("capture_output", True)
            kwargs.setdefault("text", True)
            kwargs.setdefault("check", False)
            kwargs.setdefault(
                "creationflags",
                int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)),
            )
            return subprocess.run(argv, **kwargs)  # noqa: S603

        run = runner or _run_default
        completed = run(
            ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        _delete_windows_run_key()
        return {
            "ok": True,  # run key deleted even if schtasks missing
            "platform": "windows",
            "task": TASK_NAME,
            "schtasks_rc": getattr(completed, "returncode", 1),
        }
    run = runner or subprocess.run
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
    """Disconnect/idle: stop the fat engine process (ORT RSS only drops on exit)."""
    policy = set_desired_mode(DESIRED_STANDBY)
    try:
        from pipeline.memory_governor import get_governor

        # Pre-exit cleanup only — does not free ORT arena RSS.
        get_governor().force_demote_disconnect()
    except Exception:  # noqa: BLE001
        pass
    stopped = None
    if stop_engine:
        from pipeline.daemon import stop_daemon

        _lifecycle_log("standby_stop", reason="idle_standby")
        stopped = stop_daemon(reason="idle_standby")
    return {"ok": True, "policy": policy, "engine": stopped}


def request_run(*, repo: Path | str | None = None) -> dict[str, Any]:
    """User work is about to happen: engine is allowed to exist."""
    note_activity()
    from pipeline.daemon import ensure_daemon

    return ensure_daemon(repo)


def ensure_supervisor() -> dict[str, Any]:
    """Keep a supervisor in this session. Never uses the --logon path.

    On Windows, prefer the detached/orphan spawn path so CLI ``connect`` and
    MCP share the same non-Cursor parent. Darwin prefers LaunchAgent.
    """
    if current_desktop() == "windows":
        return ensure_supervisor_detached()
    from pipeline.watchdog import is_watchdog_running, start_watchdog, watchdog_status

    if is_watchdog_running():
        return {"ok": True, "already_running": True, **watchdog_status()}
    if current_desktop() == "darwin" and launch_agent_plist_path().is_file():
        kicked = kickstart_launch_agent()
        time.sleep(0.4)
        if is_watchdog_running():
            return {"ok": True, "started": "launch_agent", **kicked, **watchdog_status()}
    return start_watchdog(orphan=False)


def _windows_supervisor_task_exists() -> bool:
    try:
        completed = subprocess.run(
            ["schtasks", "/Query", "/TN", TASK_NAME],
            capture_output=True,
            text=True,
            check=False,
            timeout=8,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)),
        )
    except Exception:  # noqa: BLE001
        return False
    return getattr(completed, "returncode", 1) == 0


def _run_windows_supervisor_task() -> dict[str, Any]:
    """Kick the logon Scheduled Task so Task Scheduler parents the supervisor.

    Never call this when the task is missing — ``schtasks`` itself flashes a
    console and MCP was hammering /Run in a tight loop.
    """
    if not _windows_supervisor_task_exists():
        return {
            "ok": False,
            "method": "schtasks_run",
            "skipped": "task_missing",
            "task": TASK_NAME,
        }
    try:
        completed = subprocess.run(
            ["schtasks", "/Run", "/TN", TASK_NAME],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)),
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "method": "schtasks_run", "error": str(exc)}
    return {
        "ok": getattr(completed, "returncode", 1) == 0,
        "method": "schtasks_run",
        "task": TASK_NAME,
        "stdout": (completed.stdout or "")[:200],
        "stderr": (completed.stderr or "")[:200],
    }


_ENSURE_SUPERVISOR_COOLDOWN_S = 20.0
_last_ensure_supervisor_at = 0.0
_last_ensure_supervisor_result: dict[str, Any] | None = None


def ensure_supervisor_detached() -> dict[str, Any]:
    """Ensure supervisor without leaving MCP as the parent of the watchdog tree.

    Prefer OS-managed parents (schtasks / LaunchAgent / WMI orphan). Never use a
    plain in-tree Popen from MCP — that makes Cursor close kill the engine job.

    Rate-limited: MCP reconnect storms must not spawn schtasks/WMI every few ms.
    """
    global _last_ensure_supervisor_at, _last_ensure_supervisor_result
    from pipeline.watchdog import is_watchdog_running, start_watchdog, watchdog_status

    if is_watchdog_running():
        return {"ok": True, "already_running": True, **watchdog_status()}

    now = time.time()
    if (
        _last_ensure_supervisor_result is not None
        and (now - _last_ensure_supervisor_at) < _ENSURE_SUPERVISOR_COOLDOWN_S
    ):
        # Still not running, but do not flash-spawn again.
        return {
            "ok": False,
            "error": "spawn_cooldown",
            "spawn_cooldown": True,
            "cooldown_s": _ENSURE_SUPERVISOR_COOLDOWN_S,
            "last": _last_ensure_supervisor_result,
        }

    desktop = current_desktop()
    result: dict[str, Any]
    if desktop == "windows":
        kicked = _run_windows_supervisor_task()
        if kicked.get("ok"):
            time.sleep(0.6)
        if is_watchdog_running():
            result = {
                "ok": True,
                "started": "schtasks",
                **kicked,
                **watchdog_status(),
            }
        else:
            orphaned = start_watchdog(orphan=True)
            time.sleep(0.4)
            if is_watchdog_running() or orphaned.get("ok"):
                result = {
                    "ok": True,
                    **orphaned,
                    **watchdog_status(),
                    "started": "wmi_orphan",
                }
            else:
                result = orphaned
        _last_ensure_supervisor_at = time.time()
        _last_ensure_supervisor_result = dict(result)
        return result
    if desktop == "darwin" and launch_agent_plist_path().is_file():
        kicked = kickstart_launch_agent()
        time.sleep(0.4)
        if is_watchdog_running():
            result = {"ok": True, "started": "launch_agent", **kicked, **watchdog_status()}
            _last_ensure_supervisor_at = time.time()
            _last_ensure_supervisor_result = dict(result)
            return result
    result = start_watchdog(orphan=False)
    _last_ensure_supervisor_at = time.time()
    _last_ensure_supervisor_result = dict(result)
    return result

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
