"""Upgrade lifecycle for Scubiee.

Handles:
- Checking PyPI for newer versions (cached, max once per 24h)
- Self-upgrade via pip/uv
- Daemon version mismatch detection and auto-restart
- Post-upgrade migrations
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def installed_version() -> str:
    """Return the currently installed scubiee version."""
    try:
        from importlib.metadata import version

        return version("scubiee")
    except Exception:  # noqa: BLE001
        return "unknown"


def _update_check_path() -> Path:
    from pipeline.project_id import context_engine_home

    return context_engine_home() / "update_check.json"


def _load_update_check() -> dict[str, Any]:
    path = _update_check_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_update_check(data: dict[str, Any]) -> None:
    path = _update_check_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def check_pypi_version(*, force: bool = False, timeout: float = 5.0) -> dict[str, Any]:
    """Check PyPI for the latest scubiee version.

    Caches the result for 24h to avoid hitting PyPI on every command.
    Returns: {"latest": "0.2.57", "current": "0.2.56", "update_available": True/False}
    """
    current = installed_version()
    cached = _load_update_check()

    # Use cache if fresh (< 24h)
    if not force and cached.get("checked_at"):
        age = time.time() - cached["checked_at"]
        if age < 86400:  # 24 hours
            return {
                "current": current,
                "latest": cached.get("latest", current),
                "update_available": _version_tuple(cached.get("latest", current)) > _version_tuple(current),
                "cached": True,
                "checked_at": cached["checked_at"],
            }

    # Query PyPI
    latest = current
    try:
        import urllib.request

        url = "https://pypi.org/pypi/scubiee/json"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            latest = data.get("info", {}).get("version", current)
    except Exception:  # noqa: BLE001
        return {
            "current": current,
            "latest": current,
            "update_available": False,
            "error": "pypi_unreachable",
        }

    # Save cache
    _save_update_check({
        "latest": latest,
        "current": current,
        "checked_at": time.time(),
    })

    return {
        "current": current,
        "latest": latest,
        "update_available": _version_tuple(latest) > _version_tuple(current),
        "cached": False,
    }


def _version_tuple(v: str) -> tuple[int, ...]:
    """Parse "0.2.56" into (0, 2, 56) for comparison."""
    try:
        return tuple(int(x) for x in v.split("."))
    except (ValueError, AttributeError):
        return (0,)


def update_available_hint() -> str | None:
    """Return a one-line hint if a newer version is available, else None.

    Non-blocking: uses cached check only (never hits network).
    """
    cached = _load_update_check()
    if not cached.get("latest"):
        return None
    current = installed_version()
    latest = cached["latest"]
    if _version_tuple(latest) > _version_tuple(current):
        return f"Update available: {current} \u2192 {latest}  (scubiee upgrade)"
    return None


def daemon_version() -> str | None:
    """Query the running daemon's version. Returns None if not reachable."""
    try:
        from pipeline.client import EngineClient

        client = EngineClient(timeout=3.0)
        health = client.get("/health")
        return health.get("version")
    except Exception:  # noqa: BLE001
        return None


def daemon_version_matches() -> bool:
    """True if the running daemon version matches the installed CLI version."""
    dv = daemon_version()
    if dv is None:
        return True  # No daemon = no mismatch
    return dv == installed_version()


def restart_daemon_if_stale() -> dict[str, Any]:
    """If daemon version != installed version, restart it."""
    dv = daemon_version()
    iv = installed_version()
    if dv is None:
        return {"ok": True, "action": "no_daemon"}
    if dv == iv:
        return {"ok": True, "action": "version_match", "version": iv}

    # Version mismatch -- restart
    try:
        from pipeline.daemon import force_restart_daemon

        result = force_restart_daemon()
        return {
            "ok": result.get("ok", False),
            "action": "restarted",
            "old_version": dv,
            "new_version": iv,
            "restart": result,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "action": "restart_failed", "error": str(exc)}


def do_upgrade(*, pre_release: bool = False) -> dict[str, Any]:
    """Perform the full upgrade: pull package -> restart daemon -> migrate.

    Returns a structured report.
    """
    report: dict[str, Any] = {"ok": True}
    old_version = installed_version()
    report["old_version"] = old_version

    # 1. Upgrade the package
    uv = shutil.which("uv")
    from pipeline.process_control import is_uv_tool_install

    if is_uv_tool_install() and uv:
        cmd = [uv, "tool", "upgrade", "scubiee"]
        if pre_release:
            cmd.append("--prerelease=allow")
    elif uv:
        cmd = [uv, "pip", "install", "--upgrade", "--python", sys.executable, "scubiee"]
    else:
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "scubiee"]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        report["pip"] = {
            "ok": proc.returncode == 0,
            "cmd": cmd,
            "stdout": (proc.stdout or "").strip()[-300:],
            "stderr": (proc.stderr or "").strip()[-300:],
        }
        if proc.returncode != 0:
            report["ok"] = False
            report["error"] = "package_upgrade_failed"
            return report
    except subprocess.TimeoutExpired:
        report["ok"] = False
        report["error"] = "package_upgrade_timeout"
        return report
    except Exception as exc:  # noqa: BLE001
        report["ok"] = False
        report["error"] = str(exc)
        return report

    # Re-read version (importlib caches; re-import to see new)
    try:
        from importlib.metadata import version

        new_version = version("scubiee")
    except Exception:  # noqa: BLE001
        new_version = "unknown"
    report["new_version"] = new_version

    if new_version == old_version:
        report["already_latest"] = True

    # 2. Restart daemon with new code
    restart = restart_daemon_if_stale()
    report["daemon_restart"] = restart

    # 3. Run migrations
    try:
        from pipeline.migrate import migrate_all

        migration = migrate_all()
        report["migration"] = migration
    except Exception as exc:  # noqa: BLE001
        report["migration"] = {"ok": False, "error": str(exc)}

    # 4. Clear update check cache
    _save_update_check({
        "latest": new_version,
        "current": new_version,
        "checked_at": time.time(),
    })

    return report
