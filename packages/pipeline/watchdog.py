"""Lightweight sidecar watchdog.

Polls /health. Automatic engine *load* is agent-owned (first gate/status/map).
Watchdog does not start or force-restart a stopped engine unless
CTX_WATCHDOG_AUTO_START=1. Idle unload is handled by the daemon lifecycle
(client registry + apply_idle_policy), not here.

Disable the sidecar with CTX_WATCHDOG=0.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

DEFAULT_INTERVAL_S = 15.0
FAILS_BEFORE_RESTART = 2
# Engine PID alive + /health lag (index/boot) is not a crash. 8 * 15s ≈ 2 min.
ALIVE_PID_FAILS_BEFORE_RESTART = 8
MAX_RESTARTS_PER_HOUR = 20
PAUSE_AFTER_CAP_S = 600.0
BACKOFF_S = (5.0, 15.0, 30.0)


def _home() -> Path:
    from pipeline.project_id import context_engine_home

    return context_engine_home()


def watchdog_pid_path() -> Path:
    return _home() / "watchdog.pid"


def watchdog_log_path() -> Path:
    return _home() / "watchdog.log"


def watchdog_state_path() -> Path:
    return _home() / "watchdog-state.json"


def _load_watchdog_state() -> dict[str, Any]:
    try:
        data = json.loads(watchdog_state_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}


def _update_watchdog_state(**changes: Any) -> dict[str, Any]:
    from pipeline.artifact_guard import atomic_write_text

    state = {
        "restart_count": 0,
        "last_wake_reconcile": None,
        "last_reconcile": None,
        "last_error": None,
        **_load_watchdog_state(),
        **changes,
    }
    _home().mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        watchdog_state_path(),
        json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n",
    )
    return state


def watchdog_enabled() -> bool:
    return os.environ.get("CTX_WATCHDOG", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def watchdog_auto_start_enabled() -> bool:
    """True when the poll loop may cold-start the engine (legacy).

    Default is off: the agent first-call path starts the engine immediately
    instead of waiting on this 15s tick. Set CTX_WATCHDOG_AUTO_START=1 to
    restore requested-start from the watchdog.
    """
    raw = (os.environ.get("CTX_WATCHDOG_AUTO_START") or "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n"
    try:
        _home().mkdir(parents=True, exist_ok=True)
        with open(watchdog_log_path(), "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:  # noqa: BLE001
        pass
    print(f"[watchdog] {msg}", file=sys.stderr, flush=True)


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


def discover_watchdog_pid() -> int | None:
    """Pid file first; then this home's boot scripts (never another CTX_HOME)."""
    path = watchdog_pid_path()
    if path.is_file():
        try:
            pid = int(path.read_text(encoding="utf-8").strip())
        except Exception:  # noqa: BLE001
            pid = 0
        if pid and _pid_alive(pid):
            return pid
    try:
        import psutil
    except ImportError:
        return None
    home = _home()
    boot_markers = (
        str(home / "_boot_watchdog.pyw").lower().replace("/", "\\"),
        str(home / "_boot_supervisor.pyw").lower().replace("/", "\\"),
    )
    me = os.getpid()
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            info = proc.info
            pid = int(info["pid"])
            if pid == me:
                continue
            name = str(info.get("name") or "").lower()
            if not any(tok in name for tok in ("python", "pythonw", "scubiee")):
                continue
            joined = " ".join(str(x) for x in (proc.cmdline() or [])).lower()
            joined_norm = joined.replace("/", "\\")
            if any(marker in joined_norm for marker in boot_markers) and _pid_alive(pid):
                return pid
        except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError, ValueError):
            continue
    return None


def is_watchdog_running() -> bool:
    pid = discover_watchdog_pid()
    if pid is None:
        return False
    path = watchdog_pid_path()
    try:
        if not path.is_file() or path.read_text(encoding="utf-8").strip() != str(pid):
            _home().mkdir(parents=True, exist_ok=True)
            path.write_text(str(pid), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return True


def watchdog_status() -> dict[str, Any]:
    state = _load_watchdog_state()
    return {
        "enabled": watchdog_enabled(),
        "running": is_watchdog_running(),
        "pid": discover_watchdog_pid(),
        "log": str(watchdog_log_path()),
        "interval_s": float(os.environ.get("CTX_WATCHDOG_INTERVAL_S", str(DEFAULT_INTERVAL_S))),
        "restart_count": int(state.get("restart_count") or 0),
        "last_wake_reconcile": state.get("last_wake_reconcile"),
        "last_reconcile": state.get("last_reconcile"),
        "last_error": state.get("last_error"),
    }


def _load_engine_meta() -> dict[str, Any]:
    from pipeline.daemon import meta_path

    path = meta_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _health_ok(*, timeout: float = 3.0) -> bool:
    from pipeline.client import EngineClient, engine_url

    try:
        return EngineClient(engine_url(), timeout=timeout).healthy()
    except Exception:  # noqa: BLE001
        return False


def _engine_busy_indexing() -> bool:
    """True when /health says indexing/warming — do not force-restart."""
    from pipeline.client import EngineClient, engine_url

    try:
        health = EngineClient(engine_url(), timeout=2.0).get("/health")
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(health, dict):
        return False
    warm = str(health.get("warm_state") or "").strip().lower()
    return warm in {"indexing", "warming"}


def engine_process_alive() -> tuple[bool, str]:
    """Liveness beyond ``engine.lock`` — lock may be missing while the listener is up."""
    try:
        from pipeline.daemon import _read_lock_pid, heal_engine_lock, meta_path, pid_path

        lock_pid = _read_lock_pid()
        if lock_pid and _pid_alive(int(lock_pid)):
            return True, "lock"
        if pid_path().is_file():
            try:
                pid = int(pid_path().read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                pid = 0
            if pid and _pid_alive(pid):
                return True, "pid_file"
        if meta_path().is_file():
            try:
                meta = json.loads(meta_path().read_text(encoding="utf-8"))
                meta_pid = int((meta or {}).get("pid") or 0)
            except Exception:  # noqa: BLE001
                meta_pid = 0
            if meta_pid and _pid_alive(meta_pid):
                return True, "meta"
        from pipeline.daemon import default_host_port
        from pipeline.process_control import pids_listening_on_port

        _host, port = default_host_port()
        listeners = pids_listening_on_port(int(port))
        for pid in listeners:
            if _pid_alive(int(pid)):
                try:
                    heal_engine_lock()
                except Exception:  # noqa: BLE001
                    pass
                return True, "port"
    except Exception:  # noqa: BLE001
        pass
    return False, "none"


def watchdog_loop(*, stop_after: float | None = None) -> None:
    """Blocking poll loop (runs in the watchdog child process)."""
    interval = float(os.environ.get("CTX_WATCHDOG_INTERVAL_S", str(DEFAULT_INTERVAL_S)))
    interval = max(0.5, interval)
    _home().mkdir(parents=True, exist_ok=True)
    watchdog_pid_path().write_text(str(os.getpid()), encoding="utf-8")
    try:
        from pipeline.process_job import attach_supervisor_job

        attach_supervisor_job()
    except Exception as exc:  # noqa: BLE001
        _log(f"job attach note: {exc}")
    _log(f"started pid={os.getpid()} interval={interval}s")

    fails = 0
    restart_times: list[float] = []
    backoff_i = 0
    deadline = time.time() + stop_after if stop_after else None
    last_tick = time.monotonic()
    wake_gap_s = max(
        interval * 3,
        float(os.environ.get("CTX_WAKE_GAP_MS", "30000")) / 1000,
    )

    try:
        while True:
            if deadline is not None and time.time() >= deadline:
                break
            monotonic_now = time.monotonic()
            if monotonic_now - last_tick > wake_gap_s:
                from pipeline.daemon import reconcile_managed_repositories

                reconciled_at = time.time()
                try:
                    reconcile_managed_repositories(reason="watchdog_sleep_wake")
                    _update_watchdog_state(
                        last_wake_reconcile=reconciled_at,
                        last_reconcile=reconciled_at,
                        last_error=None,
                    )
                except Exception as exc:  # noqa: BLE001
                    _update_watchdog_state(
                        last_wake_reconcile=reconciled_at,
                        last_error=str(exc),
                    )
                    _log(f"sleep/wake reconcile failed: {exc}")
            last_tick = monotonic_now
            from pipeline.lifecycle_runtime import engine_should_be_running

            if _health_ok():
                fails = 0
                backoff_i = 0
                try:
                    from pipeline.daemon import consume_engine_start_request, heal_engine_lock

                    consume_engine_start_request()
                    heal_engine_lock()
                except Exception:  # noqa: BLE001
                    pass
                # Orphan MCP after Cursor close → unregister → standby after debounce.
                try:
                    from pipeline.lifecycle_runtime import enforce_mcp_warm_contract

                    contract = enforce_mcp_warm_contract()
                    action = str((contract or {}).get("action") or "")
                    if action not in {"", "none", "already_standby", "hold_clients"}:
                        _log(
                            f"warm contract action={action} "
                            f"clients={(contract or {}).get('active_clients')}"
                        )
                except Exception as exc:  # noqa: BLE001
                    _log(f"warm contract skipped: {exc}")
                time.sleep(interval)
                continue

            if not engine_should_be_running():
                fails = 0
                time.sleep(interval)
                continue

            pid_alive, alive_src = engine_process_alive()
            # Leftover start_request stamps: consume always so they cannot keep
            # engine_should_be_running sticky. Cold-start itself is agent-owned
            # unless CTX_WATCHDOG_AUTO_START=1.
            if not pid_alive:
                try:
                    from pipeline.daemon import (
                        consume_engine_start_request,
                        start_daemon,
                        start_request_is_actionable,
                    )
                    from pipeline.lifecycle_runtime import (
                        DESIRED_STANDBY,
                        active_client_count,
                        set_desired_mode,
                    )

                    req = consume_engine_start_request()
                except Exception:  # noqa: BLE001
                    req = None
                if req is not None:
                    try:
                        clients = int(active_client_count())
                    except Exception:  # noqa: BLE001
                        clients = 0
                    if not watchdog_auto_start_enabled():
                        _log(
                            "skip auto start (agent warm) "
                            f"clients={clients} repo={req.get('repo') or ''}"
                        )
                        fails = 0
                        time.sleep(interval)
                        continue
                    if not start_request_is_actionable(req, clients=clients):
                        _log(
                            "skip stale start_request "
                            f"clients={clients} at={req.get('at')}"
                        )
                        try:
                            set_desired_mode(DESIRED_STANDBY)
                        except Exception:  # noqa: BLE001
                            pass
                        fails = 0
                        time.sleep(interval)
                        continue
                    meta = _load_engine_meta()
                    repo = (
                        str(req.get("repo") or "").strip()
                        or meta.get("repo")
                        or os.environ.get("CTX_REPO")
                        or "."
                    )
                    _log(f"requested start repo={repo}")
                    try:
                        result = start_daemon(repo)
                    except Exception as exc:  # noqa: BLE001
                        _log(f"requested start exception: {exc}")
                        result = {"ok": False, "error": str(exc)}
                    _log(
                        f"requested start result={result.get('ok')} "
                        f"{result.get('error') or ''}".strip()
                    )
                    fails = 0
                    backoff_i = 0
                    time.sleep(interval)
                    continue

            if pid_alive and _engine_busy_indexing():
                _log(
                    f"skip restart indexing alive_src={alive_src} "
                    "(index/boot health lag is not a crash)"
                )
                fails = 0
                time.sleep(interval)
                continue

            fails += 1
            fail_limit = (
                ALIVE_PID_FAILS_BEFORE_RESTART if pid_alive else FAILS_BEFORE_RESTART
            )
            _log(
                f"health fail count={fails}/{fail_limit} "
                f"pid_alive={pid_alive} src={alive_src}"
            )
            if fails < fail_limit:
                time.sleep(interval)
                continue

            # Automatic engine load is agent-owned (first gate/status/map).
            # Watchdog must not revive a stopped engine just because MCP is
            # still connected. Disconnect unload stays on the idle sweeper.
            if not watchdog_auto_start_enabled():
                _log(
                    "skip auto load (agent warm) "
                    f"pid_alive={pid_alive} src={alive_src}"
                )
                fails = 0
                time.sleep(interval)
                continue

            # Demand gate: never force-restart a ghost engine when nothing
            # needs it (no MCP clients, no pending start_request).
            try:
                from pipeline.lifecycle_runtime import (
                    DESIRED_STANDBY,
                    active_client_count,
                    set_desired_mode,
                )
                from pipeline.daemon import start_request_path

                has_demand = active_client_count() > 0 or start_request_path().is_file()
            except Exception:  # noqa: BLE001
                has_demand = True
            if not has_demand and not pid_alive:
                _log("skip force restart: no clients and no start_request → standby")
                try:
                    set_desired_mode(DESIRED_STANDBY)
                except Exception:  # noqa: BLE001
                    pass
                fails = 0
                time.sleep(interval)
                continue

            # Crash-loop cap
            now = time.time()
            restart_times = [t for t in restart_times if now - t < 3600.0]
            if len(restart_times) >= MAX_RESTARTS_PER_HOUR:
                _log(
                    f"restart cap {MAX_RESTARTS_PER_HOUR}/hour — pause {PAUSE_AFTER_CAP_S:.0f}s"
                )
                time.sleep(PAUSE_AFTER_CAP_S)
                restart_times.clear()
                fails = 0
                continue

            from pipeline.daemon import force_restart_daemon

            meta = _load_engine_meta()
            repo = meta.get("repo") or os.environ.get("CTX_REPO") or "."
            _log(f"force restart repo={repo}")
            try:
                result = force_restart_daemon(repo)
            except Exception as exc:  # noqa: BLE001
                _log(f"force restart exception: {exc}")
                result = {"ok": False, "error": str(exc)}
            _log(f"restart result={result.get('ok')} {result.get('error') or ''}".strip())
            state = _load_watchdog_state()
            _update_watchdog_state(
                restart_count=int(state.get("restart_count") or 0) + 1,
                last_reconcile=time.time() if result.get("ok") else state.get("last_reconcile"),
                last_error=result.get("error"),
            )
            restart_times.append(time.time())
            fails = 0
            wait = BACKOFF_S[min(backoff_i, len(BACKOFF_S) - 1)]
            backoff_i += 1
            time.sleep(wait)
    finally:
        try:
            watchdog_pid_path().unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        _log("exited")


def start_watchdog(*, orphan: bool = False) -> dict[str, Any]:
    """Spawn detached watchdog if enabled and not already running.

    ``orphan=True`` (MCP / connect paths on Windows): spawn via WMI so the
    watchdog is **not** a child of Cursor MCP. Otherwise closing Cursor kills the
    supervisor job (KILL_ON_JOB_CLOSE) and takes the engine with it.
    """
    from pipeline.pause_resume import is_paused, is_resuming

    if is_paused() and not is_resuming():
        return {"ok": True, "skipped": True, "reason": "globally_paused"}
    if not watchdog_enabled():
        return {"ok": True, "skipped": True, "reason": "CTX_WATCHDOG=0"}
    if is_watchdog_running():
        return {"ok": True, "already_running": True, **watchdog_status()}

    _home().mkdir(parents=True, exist_ok=True)
    from pipeline.process_job import background_python

    py = background_python()
    log_path = watchdog_log_path()
    try:
        with open(log_path, "a", encoding="utf-8") as log_f:
            log_f.write(f"\n--- spawn {time.strftime('%Y-%m-%d %H:%M:%S')} orphan={orphan} ---\n")
    except OSError:
        pass

    if orphan and os.name == "nt":
        from pipeline.silent_spawn import start_watchdog_silent_orphan

        created = start_watchdog_silent_orphan()
        if created.get("ok"):
            return created
        # Fall through to Popen if WMI denied — still no cmd.exe.
        _log(f"silent orphan spawn failed: {created}; falling back to Popen")

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env.setdefault("CTX_ENGINE_SOFT_SPAWN", "1")
    cmd = [py, "-u", "-m", "pipeline", "engine", "watchdog"]
    log_f = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
    kwargs: dict[str, Any] = {
        "env": env,
        "stdout": log_f,
        "stderr": log_f,
        "stdin": subprocess.DEVNULL,
    }
    if os.name == "nt":
        from pipeline.process_job import engine_popen_kwargs

        # Soft flags: CREATE_NO_WINDOW only — DETACHED flashes consoles.
        kwargs.update(engine_popen_kwargs(soft=True))
    elif sys.platform != "darwin":
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **kwargs)  # noqa: S603
    try:
        log_f.close()
    except Exception:  # noqa: BLE001
        pass
    watchdog_pid_path().write_text(str(proc.pid), encoding="utf-8")
    time.sleep(0.3)
    return {
        "ok": True,
        "started": True,
        "orphan": bool(orphan),
        "pid": proc.pid,
        "log": str(log_path),
    }


def stop_watchdog() -> dict[str, Any]:
    path = watchdog_pid_path()
    pid = None
    if path.is_file():
        try:
            pid = int(path.read_text(encoding="utf-8").strip())
        except Exception:  # noqa: BLE001
            pid = None
    if pid and _pid_alive(pid):
        try:
            if os.name == "nt":
                from pipeline.process_job import taskkill_silent

                taskkill_silent(int(pid), tree=False)
            else:
                os.kill(pid, 15)
        except Exception:  # noqa: BLE001
            pass
    try:
        path.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass
    time.sleep(0.2)
    return {"ok": True, "stopped_pid": pid, "running": is_watchdog_running()}
