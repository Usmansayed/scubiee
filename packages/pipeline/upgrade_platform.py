"""Cross-OS platform helpers for Scubiee upgrade quiesce / verify / rebind.

Windows: file locks + taskkill. macOS/Linux: SIGTERM→SIGKILL + atomic-safe swaps.
Never treat machine reboot as a success path.
"""

from __future__ import annotations

import os
import socket
import sys
import time
from pathlib import Path
from typing import Any


def platform_name() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def engine_host_port() -> tuple[str, int]:
    from pipeline.daemon import default_host_port

    return default_host_port()


def port_in_use(host: str, port: int) -> bool:
    """True if something is listening (or we cannot bind) on host:port."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(0.5)
            # Connect probe is more reliable than bind for "is server up"
            try:
                sock.connect((host if host not in ("0.0.0.0", "::") else "127.0.0.1", port))
                return True
            except OSError:
                return False
    except OSError:
        return False


def quiesce_for_upgrade(*, project: Path | None = None) -> dict[str, Any]:
    """Stub MCP (do not strip) → stop Scubiee processes → free port.

    Uses strip_mcp=False so a failed package swap can still restore via reconnect.
    """
    from pipeline.lifecycle_runtime import begin_upgrade_transition
    from pipeline.process_control import release_scubiee_process_locks
    from pipeline.upgrade import installed_version

    report: dict[str, Any] = {
        "ok": True,
        "platform": platform_name(),
        "phases": [],
    }
    report["upgrade_transition"] = begin_upgrade_transition(version=installed_version())
    report["phases"].append("upgrade_begin")

    # Prefer halt-style release: stub MCP, kill processes, do NOT strip keys.
    try:
        release = release_scubiee_process_locks(
            project=project,
            strip_mcp=False,
        )
        report["release"] = release
        report["phases"].append("release_locks")
        if not release.get("ok", True):
            report["ok"] = False
            report["error"] = release.get("error") or "processes_still_running"
            report["hint"] = release.get("hint")
            from pipeline.lifecycle_runtime import abort_upgrade_transition

            report["upgrade_abort"] = abort_upgrade_transition(reason="release_failed")
            return report
    except TypeError:
        # Older signature without strip_mcp — fall back then note.
        release = release_scubiee_process_locks(project=project)
        report["release"] = release
        report["phases"].append("release_locks_legacy")
        report["warning"] = "strip_mcp kw unsupported; MCP may have been stripped"
        if not release.get("ok", True):
            report["ok"] = False
            report["error"] = "processes_still_running"
            from pipeline.lifecycle_runtime import abort_upgrade_transition

            report["upgrade_abort"] = abort_upgrade_transition(reason="release_failed")
            return report
    except Exception as exc:  # noqa: BLE001
        report["ok"] = False
        report["error"] = str(exc)
        from pipeline.lifecycle_runtime import abort_upgrade_transition

        report["upgrade_abort"] = abort_upgrade_transition(reason="quiesce_exception")
        return report

    host, port = engine_host_port()
    # Best-effort stop daemon if still up
    try:
        from pipeline.daemon import stop_daemon_for_upgrade

        report["stop_daemon"] = stop_daemon_for_upgrade()
        report["phases"].append("stop_daemon")
    except Exception as exc:  # noqa: BLE001
        report["stop_daemon_error"] = str(exc)

    # Multi-round verify (Windows lockers often respawn once)
    for attempt in range(3):
        verify = verify_quiesced(host=host, port=port)
        report["verify"] = verify
        if verify.get("ok"):
            break
        time.sleep(0.8 * (attempt + 1))
        try:
            from pipeline.process_control import kill_all_scubiee_processes

            kill_all_scubiee_processes(exclude_bridge=True)
            report["phases"].append(f"kill_round_{attempt + 1}")
        except Exception as exc:  # noqa: BLE001
            report["kill_error"] = str(exc)

    report["ok"] = bool((report.get("verify") or {}).get("ok"))
    if not report["ok"]:
        report["error"] = report.get("error") or "quiesce_verify_failed"
        report["hint"] = (
            report.get("hint")
            or "Quit IDE MCP sessions holding the tool dir, run `scubiee halt`, then retry. "
            "A computer restart is not required if processes are stopped."
        )
        from pipeline.lifecycle_runtime import abort_upgrade_transition

        report["upgrade_abort"] = abort_upgrade_transition(reason="quiesce_failed")
    return report


def verify_quiesced(*, host: str | None = None, port: int | None = None) -> dict[str, Any]:
    """Postconditions before package swap."""
    if host is None or port is None:
        host, port = engine_host_port()

    remaining: list[dict[str, Any]] = []
    try:
        from pipeline.process_control import enumerate_scubiee_processes

        remaining = list(enumerate_scubiee_processes() or [])
    except Exception:  # noqa: BLE001
        try:
            from pipeline.process_control import list_scubiee_processes

            remaining = list(list_scubiee_processes() or [])
        except Exception:  # noqa: BLE001
            remaining = []

    listening = port_in_use(host, port)
    tool_writable = True
    tool_error = None
    try:
        from pipeline.process_control import is_uv_tool_install, uv_tool_root

        if is_uv_tool_install():
            root = uv_tool_root()
            if root is not None and Path(root).exists():
                probe = Path(root) / ".upgrade_write_probe"
                try:
                    probe.write_text("ok", encoding="utf-8")
                    probe.unlink(missing_ok=True)
                except OSError as exc:
                    tool_writable = False
                    tool_error = str(exc)
    except Exception as exc:  # noqa: BLE001
        tool_error = str(exc)

    ok = (not remaining) and (not listening) and tool_writable
    return {
        "ok": ok,
        "platform": platform_name(),
        "remaining_processes": remaining,
        "port": port,
        "port_in_use": listening,
        "tool_dir_writable": tool_writable,
        "tool_dir_error": tool_error,
    }


def ensure_daemon_after_upgrade(repo: Path | str | None = None) -> dict[str, Any]:
    """Always bounce the daemon onto the newly installed package after upgrade."""
    from pipeline.daemon import force_restart_daemon, stop_daemon_for_upgrade
    from pipeline.lifecycle_runtime import (
        begin_upgrade_transition,
        complete_upgrade_transition,
        upgrade_in_progress,
    )
    from pipeline.upgrade import daemon_version, installed_version

    target = Path(repo).resolve() if repo else Path.cwd().resolve()
    iv = installed_version()
    transition_begin = None
    if not upgrade_in_progress():
        transition_begin = begin_upgrade_transition(version=iv)

    try:
        stop_daemon_for_upgrade()
    except Exception:  # noqa: BLE001
        pass

    restarted = force_restart_daemon(target, upgrade=True)
    ok = bool(restarted.get("ok"))
    lifecycle = None
    if ok:
        try:
            lifecycle = complete_upgrade_transition(version=iv)
        except Exception:  # noqa: BLE001
            lifecycle = None
    else:
        try:
            from pipeline.lifecycle_runtime import abort_upgrade_transition

            lifecycle = abort_upgrade_transition(reason="restart_failed")
        except Exception:  # noqa: BLE001
            lifecycle = None

    dv = daemon_version()
    action = "restarted_after_upgrade" if ok else "restart_failed_after_upgrade"
    return {
        "ok": ok,
        "action": action,
        "repo": str(target),
        "installed_version": iv,
        "daemon_version": dv,
        "version_match": dv == iv if dv is not None else None,
        "restart": restarted,
        "transition_begin": transition_begin,
        "lifecycle": lifecycle,
        "hint": (
            "Daemon restarted on the new package. Quit and reopen your IDE once "
            "so MCP reloads the bridge — no other steps required."
        )
        if ok
        else "Run `scubiee engine start` then reload IDE MCP.",
    }


def health_check(*, timeout: float = 5.0) -> dict[str, Any]:
    """Readiness probe: daemon health + version match."""
    from pipeline.upgrade import daemon_version, installed_version

    iv = installed_version()
    result: dict[str, Any] = {
        "ok": False,
        "installed_version": iv,
        "platform": platform_name(),
    }
    try:
        from pipeline.client import EngineClient

        client = EngineClient(timeout=timeout)
        health = client.get("/health")
        dv = health.get("version")
        result["daemon_version"] = dv
        result["health"] = health
        result["ok"] = bool(health.get("ok")) and dv == iv
        if dv and dv != iv:
            result["error"] = "version_mismatch"
            result["hint"] = "Run `scubiee engine restart` or `scubiee upgrade` again."
        elif not health.get("ok"):
            result["error"] = "health_not_ok"
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
        result["hint"] = "Run `scubiee engine start`."
    return result


def package_swap_commands(*, pre_release: bool = False) -> list[list[str]]:
    """Return ordered install commands for the active platform/channel."""
    import shutil

    uv = shutil.which("uv") or "uv"
    spec = "scubiee" if pre_release else "scubiee"
    force = [uv, "tool", "install", "--force", spec, "--index-url", "https://pypi.org/simple"]
    if pre_release:
        force.append("--pre")
    return [force]
