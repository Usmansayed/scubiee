"""Silent Windows boot helpers for supervisor/engine (no console flash)."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any


def _home() -> Path:
    from pipeline.project_id import context_engine_home

    return context_engine_home()


def watchdog_boot_script_path() -> Path:
    return _home() / "_boot_watchdog.pyw"


def spawn_lock_path() -> Path:
    return _home() / "watchdog.spawn.lock"


def write_watchdog_boot_script() -> Path:
    """Write a .pyw boot file so pythonw runs with no console window."""
    _home().mkdir(parents=True, exist_ok=True)
    path = watchdog_boot_script_path()
    # Keep boot tiny and self-contained: set soft-spawn, then enter watchdog loop.
    path.write_text(
        "\n".join(
            [
                "import os",
                "os.environ.setdefault('CTX_ENGINE_SOFT_SPAWN', '1')",
                "os.environ.setdefault('PYTHONUTF8', '1')",
                "from pipeline.watchdog import watchdog_loop",
                "watchdog_loop()",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def acquire_spawn_lock(*, ttl_s: float = 20.0) -> bool:
    """Prevent MCP reload storms from launching dozens of watchdogs."""
    path = spawn_lock_path()
    _home().mkdir(parents=True, exist_ok=True)
    now = time.time()
    try:
        if path.is_file():
            age = now - path.stat().st_mtime
            if age < ttl_s:
                return False
        path.write_text(str(now), encoding="utf-8")
        return True
    except OSError:
        return True


def release_spawn_lock() -> None:
    try:
        spawn_lock_path().unlink(missing_ok=True)
    except OSError:
        pass


def start_watchdog_silent_orphan() -> dict[str, Any]:
    """WMI-spawn pythonw boot script — no cmd.exe, no console flash."""
    from pipeline.process_job import background_python, windows_wmi_create_process
    from pipeline.watchdog import (
        is_watchdog_running,
        watchdog_log_path,
        watchdog_pid_path,
        watchdog_status,
    )

    if is_watchdog_running():
        return {"ok": True, "already_running": True, **watchdog_status()}
    if not acquire_spawn_lock():
        time.sleep(0.8)
        if is_watchdog_running():
            return {"ok": True, "already_running": True, "spawn_locked": True, **watchdog_status()}
        return {"ok": False, "error": "spawn_locked", "hint": "another spawn in progress"}

    try:
        boot = write_watchdog_boot_script()
        py = background_python()
        # Quote paths for Win32_Process.Create; pythonw + .pyw = no console.
        command = f'"{py}" "{boot}"'
        try:
            with open(watchdog_log_path(), "a", encoding="utf-8") as log_f:
                log_f.write(
                    f"\n--- silent orphan spawn {time.strftime('%Y-%m-%d %H:%M:%S')} "
                    f"py={py} boot={boot} ---\n"
                )
        except OSError:
            pass
        created = windows_wmi_create_process(command, cwd=str(_home()))
        if created.get("ok") and created.get("pid"):
            try:
                watchdog_pid_path().write_text(str(int(created["pid"])), encoding="utf-8")
            except OSError:
                pass
            time.sleep(0.6)
            return {
                "ok": True,
                "started": True,
                "orphan": True,
                "silent": True,
                "pid": int(created["pid"]),
                "boot": str(boot),
                **{k: created.get(k) for k in ("method", "return_value")},
            }
        return {"ok": False, "error": "wmi_create_failed", "detail": created}
    finally:
        release_spawn_lock()
