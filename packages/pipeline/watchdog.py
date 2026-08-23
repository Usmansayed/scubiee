"""Lightweight sidecar watchdog — revive Context Engine if it dies or hangs.

Not a manager: polls /health and calls daemon.force_restart_daemon when the
policy says the engine should be running. Idle unload is handled by the daemon
lifecycle (client registry + apply_idle_policy), not here.

Disable with CTX_WATCHDOG=0.
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


def is_watchdog_running() -> bool:
    path = watchdog_pid_path()
    if not path.is_file():
        return False
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except Exception:  # noqa: BLE001
        return False
    return _pid_alive(pid)


def watchdog_status() -> dict[str, Any]:
    path = watchdog_pid_path()
    pid = None
    if path.is_file():
        try:
            pid = int(path.read_text(encoding="utf-8").strip())
        except Exception:  # noqa: BLE001
            pid = None
    state = _load_watchdog_state()
    return {
        "enabled": watchdog_enabled(),
        "running": is_watchdog_running(),
        "pid": pid if pid and _pid_alive(pid) else None,
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
                time.sleep(interval)
                continue

            if not engine_should_be_running():
                fails = 0
                time.sleep(interval)
                continue

            fails += 1
            _log(f"health fail count={fails}/{FAILS_BEFORE_RESTART}")
            if fails < FAILS_BEFORE_RESTART:
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
            result = force_restart_daemon(repo)
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


def start_watchdog() -> dict[str, Any]:
    """Spawn detached watchdog if enabled and not already running."""
    from pipeline.pause_resume import is_paused

    if is_paused():
        return {"ok": True, "skipped": True, "reason": "globally_paused"}
    if not watchdog_enabled():
        return {"ok": True, "skipped": True, "reason": "CTX_WATCHDOG=0"}
    if is_watchdog_running():
        return {"ok": True, "already_running": True, **watchdog_status()}

    _home().mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    cmd = [sys.executable, "-u", "-m", "pipeline", "engine", "watchdog"]
    log_f = open(watchdog_log_path(), "a", encoding="utf-8")  # noqa: SIM115
    log_f.write(f"\n--- spawn {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    log_f.flush()
    kwargs: dict[str, Any] = {
        "env": env,
        "stdout": log_f,
        "stderr": log_f,
        "stdin": subprocess.DEVNULL,
    }
    if os.name == "nt":
        from pipeline.process_job import hidden_popen_kwargs

        kwargs.update(hidden_popen_kwargs())
    elif sys.platform != "darwin":
        # Linux fallback may outlive the installing terminal. Darwin must not
        # orphan: LaunchAgent is the parent, and GUI logout should reap us.
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **kwargs)  # noqa: S603
    try:
        log_f.close()
    except Exception:  # noqa: BLE001
        pass
    # Child will overwrite pid; stash spawn pid briefly
    watchdog_pid_path().write_text(str(proc.pid), encoding="utf-8")
    time.sleep(0.3)
    return {"ok": True, "started": True, "pid": proc.pid, "log": str(watchdog_log_path())}


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
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"],
                    capture_output=True,
                    check=False,
                )
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
