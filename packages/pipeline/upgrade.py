"""Upgrade lifecycle for Scubiee.

Handles:
- Checking PyPI for newer versions (cached, max once per 24h)
- Version-aware upgrade supervisor (quiesce → swap → migrate → rebind → health)
- Daemon version mismatch detection and restart
- Post-upgrade migrations and MCP/rules refresh
"""

from __future__ import annotations

import json
import os
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

    # Version mismatch -- restart on upgrade transition path (bypass idle debounce).
    try:
        from pipeline.daemon import force_restart_daemon, stop_daemon_for_upgrade
        from pipeline.lifecycle_runtime import (
            begin_upgrade_transition,
            complete_upgrade_transition,
            upgrade_in_progress,
        )

        if not upgrade_in_progress():
            begin_upgrade_transition(version=iv)
        stop_daemon_for_upgrade()
        result = force_restart_daemon(upgrade=True)
        if result.get("ok"):
            complete_upgrade_transition(version=iv)
        else:
            from pipeline.lifecycle_runtime import abort_upgrade_transition

            abort_upgrade_transition(reason="restart_failed")
        return {
            "ok": result.get("ok", False),
            "action": "restarted",
            "old_version": dv,
            "new_version": iv,
            "restart": result,
        }
    except Exception as exc:  # noqa: BLE001
        try:
            from pipeline.lifecycle_runtime import abort_upgrade_transition

            abort_upgrade_transition(reason="restart_exception")
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "action": "restart_failed", "error": str(exc)}


def do_upgrade(
    *,
    pre_release: bool = False,
    check_only: bool = False,
    connect: bool = True,
    repair: bool = False,
    reindex: bool = False,
    skip_package: bool = False,
) -> dict[str, Any]:
    """Run the version-aware upgrade supervisor (one-command upgrade).

    Phases: detect → plan → snapshot → quiesce → swap → migrate → rebind → health.
    See ``pipeline.upgrade_supervisor.run_upgrade``.
    """
    from pipeline.upgrade_supervisor import run_upgrade

    report = run_upgrade(
        pre_release=pre_release,
        check_only=check_only,
        connect=connect,
        repair=repair,
        reindex=reindex,
        skip_package=skip_package,
    )
    # Compatibility keys for existing CLI/TTY formatting
    if "daemon" in report and "daemon_restart" not in report:
        report["daemon_restart"] = report["daemon"]
    if report.get("new_version") and report.get("old_version"):
        if report["new_version"] == report["old_version"] and not report.get("swap", {}).get(
            "skipped"
        ):
            report["already_latest"] = True
        elif report.get("swap", {}).get("skipped"):
            report["already_latest"] = True
    if report.get("quiesce") is not None:
        report["pre_stop"] = bool((report.get("quiesce") or {}).get("ok", True))
    if report.get("swap") and not report["swap"].get("skipped"):
        report["pip"] = report["swap"]
    return report
