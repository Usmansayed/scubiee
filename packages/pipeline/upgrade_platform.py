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
    from pipeline.process_control import release_scubiee_process_locks

    report: dict[str, Any] = {
        "ok": True,
        "platform": platform_name(),
        "phases": [],
    }

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
    except TypeError:
        # Older signature without strip_mcp — fall back then note.
        release = release_scubiee_process_locks(project=project)
        report["release"] = release
        report["phases"].append("release_locks_legacy")
        report["warning"] = "strip_mcp kw unsupported; MCP may have been stripped"
        if not release.get("ok", True):
            report["ok"] = False
            report["error"] = "processes_still_running"
    except Exception as exc:  # noqa: BLE001
        report["ok"] = False
        report["error"] = str(exc)
        return report

    host, port = engine_host_port()
    # Best-effort stop daemon if still up
    try:
        from pipeline.daemon import stop_daemon

        stop_daemon()
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
    """Start or force-restart daemon so it is never left down after upgrade."""
    from pipeline.daemon import ensure_daemon, force_restart_daemon, is_running
    from pipeline.upgrade import daemon_version, installed_version

    target = Path(repo).resolve() if repo else Path.cwd().resolve()
    report: dict[str, Any] = {"ok": False, "repo": str(target)}

    if is_running():
        dv = daemon_version()
        iv = installed_version()
        if dv is not None and dv != iv:
            restarted = force_restart_daemon(target)
            report["action"] = "force_restarted"
            report["restart"] = restarted
            report["ok"] = bool(restarted.get("ok"))
            return report
        # Already running correct version
        report["action"] = "already_running"
        report["ok"] = True
        report["daemon_version"] = dv
        return report

    # No daemon — start one (fixes prior no_daemon false success)
    started = ensure_daemon(target)
    if started.get("ok"):
        report["action"] = "started"
        report["ensure"] = started
        report["ok"] = True
        return report

    # ensure failed — try force restart path
    restarted = force_restart_daemon(target)
    report["action"] = "force_restart_fallback"
    report["restart"] = restarted
    report["ensure"] = started
    report["ok"] = bool(restarted.get("ok"))
    return report


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
        result["health"] = health
        dv = health.get("version") or daemon_version()
        result["daemon_version"] = dv
        result["ok"] = bool(health.get("ok", True)) and (dv is None or dv == iv)
        if dv is not None and dv != iv:
            result["error"] = "daemon_version_mismatch"
        return result
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
        return result


def package_swap_commands(*, pre_release: bool = False) -> list[list[str]]:
    """Ordered install commands. Prefer force install for uv tool (reliable bump)."""
    import shutil

    from pipeline.process_control import is_uv_tool_install

    uv = shutil.which("uv")
    cmds: list[list[str]] = []
    if is_uv_tool_install() and uv:
        force = [uv, "tool", "install", "--force", "scubiee", "--index-url", "https://pypi.org/simple"]
        if pre_release:
            force.append("--prerelease=allow")
        cmds.append(force)
        # Fallback if force unavailable on older uv
        upgrade = [uv, "tool", "upgrade", "scubiee"]
        if pre_release:
            upgrade.append("--prerelease=allow")
        cmds.append(upgrade)
    elif uv:
        cmds.append(
            [uv, "pip", "install", "--upgrade", "--python", sys.executable, "scubiee"]
        )
    else:
        cmds.append([sys.executable, "-m", "pip", "install", "--upgrade", "scubiee"])
    return cmds
