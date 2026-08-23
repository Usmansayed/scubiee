"""Stop scubiee-related processes so Windows can delete uv tool files."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def uv_tool_root(python: Path | None = None) -> Path | None:
    """Return ``.../uv/tools/scubiee`` when *python* is a uv tool interpreter."""
    py = (python or Path(sys.executable)).resolve()
    parts = py.parts
    for i, part in enumerate(parts):
        if part == "tools" and i + 1 < len(parts):
            return Path(*parts[: i + 2])
    return None


def is_uv_tool_install(python: Path | None = None) -> bool:
    root = uv_tool_root(python)
    if root is None:
        return False
    return (root / "uv-receipt.toml").is_file() or (root / "pyvenv.cfg").is_file()


def _exe_under_root(exe: str | None, root: Path) -> bool:
    if not exe:
        return False
    try:
        return str(Path(exe).resolve()).lower().startswith(str(root.resolve()).lower())
    except OSError:
        return str(exe).lower().startswith(str(root.resolve()).lower())


def processes_under(root: Path) -> list[int]:
    """PIDs whose main executable lives under *root*."""
    root_s = str(root.resolve()).lower()
    pids: list[int] = []
    try:
        import psutil
    except ImportError:
        psutil = None  # type: ignore[assignment]

    if psutil is not None:
        for proc in psutil.process_iter(["pid", "exe", "cmdline"]):
            try:
                info = proc.info
                exe = info.get("exe")
                if _exe_under_root(exe, root):
                    pids.append(int(info["pid"]))
                    continue
                cmdline = info.get("cmdline") or []
                joined = " ".join(str(x) for x in cmdline).lower()
                if root_s in joined:
                    pids.append(int(info["pid"]))
            except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError, ValueError):
                continue
        return sorted(set(pids))

    if os.name != "nt":
        return pids
    out = subprocess.run(
        ["wmic", "process", "get", "ProcessId,ExecutablePath", "/FORMAT:CSV"],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in (out.stdout or "").splitlines():
        if not line.strip() or line.startswith("Node"):
            continue
        parts = line.split(",")
        if len(parts) < 3:
            continue
        exe = parts[1].strip()
        pid_s = parts[2].strip()
        if not pid_s.isdigit():
            continue
        if _exe_under_root(exe, root):
            pids.append(int(pid_s))
    return sorted(set(pids))


def stop_processes_under(root: Path, *, grace_s: float = 1.0) -> dict[str, Any]:
    """Terminate processes locking files under *root* (Windows-safe)."""
    killed: list[int] = []
    failed: list[int] = []
    for pid in processes_under(root):
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                )
            else:
                os.kill(pid, 15)
                deadline = time.time() + grace_s
                while time.time() < deadline:
                    try:
                        os.kill(pid, 0)
                        time.sleep(0.1)
                    except OSError:
                        break
                else:
                    os.kill(pid, 9)
            killed.append(pid)
        except OSError:
            failed.append(pid)
    if grace_s:
        time.sleep(min(grace_s, 2.0))
    remaining = processes_under(root)
    return {
        "root": str(root),
        "killed": killed,
        "failed": failed,
        "remaining": remaining,
        "ok": not remaining,
    }


def stop_uv_tool_processes(python: Path | None = None) -> dict[str, Any]:
    root = uv_tool_root(python)
    if root is None:
        return {"ok": True, "skipped": "not_uv_tool"}
    return stop_processes_under(root)


def process_cmdline(pid: int) -> str:
    """Best-effort command line for *pid* (lowercase on Windows)."""
    try:
        import psutil

        proc = psutil.Process(pid)
        parts = proc.cmdline()
        return " ".join(str(x) for x in parts).lower()
    except Exception:  # noqa: BLE001
        return ""


def is_context_engine_process(pid: int) -> bool:
    """True only when *pid* looks like CE daemon/MCP/watchdog (not arbitrary reuse)."""
    if pid <= 0:
        return False
    try:
        import psutil

        proc = psutil.Process(pid)
        name = (proc.name() or "").lower()
    except Exception:  # noqa: BLE001
        name = ""
    cmdline = process_cmdline(pid)
    if not cmdline and not name:
        return False
    if _cmdline_matches_ce(cmdline.split() if cmdline else None):
        return True
    needles = (
        "python",
        "python.exe",
        "scubiee",
        "ctx-mcp",
    )
    if name not in needles and "python" not in name:
        return False
    markers = (
        "pipeline.server",
        "pipeline.engine",
        "pipeline.mcp_locate",
        "pipeline.mcp_server",
        "pipeline.watchdog",
        "pipeline.__main__",
        "context-engine",
        "scubiee",
    )
    return any(m in cmdline for m in markers)


def safe_terminate_pid(pid: int, *, grace_s: float = 1.0) -> dict[str, Any]:
    """Terminate *pid* only when it matches CE; never kill unrelated processes."""
    from pipeline.daemon import _pid_alive

    if not _pid_alive(pid):
        return {"pid": pid, "ok": True, "skipped": "not_alive"}
    if not is_context_engine_process(pid):
        return {"pid": pid, "ok": False, "skipped": "not_context_engine"}
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:
            os.kill(pid, 15)
            deadline = time.time() + grace_s
            while time.time() < deadline and _pid_alive(pid):
                time.sleep(0.1)
            if _pid_alive(pid):
                os.kill(pid, 9)
        return {"pid": pid, "ok": True, "terminated": True}
    except OSError as exc:
        return {"pid": pid, "ok": False, "error": str(exc)}


def _cmdline_matches_ce(cmdline: list[str] | None) -> bool:
    if not cmdline:
        return False
    joined = " ".join(str(x) for x in cmdline).lower()
    needles = (
        "scubiee",
        "ctx-mcp",
        "context-engine",
        r"uv\tools\scubiee",
        "pipeline.mcp_server",
        "pipeline.__main__",
        "pipeline.engine",
        "pipeline.watchdog",
    )
    return any(n in joined for n in needles)


def stop_all_context_engine_processes(*, ctx_home: Path | None = None) -> dict[str, Any]:
    """Stop daemon, watchdog, MCP, and anything locking the uv tool env."""
    actions: dict[str, Any] = {}
    my_pid = os.getpid()
    try:
        from pipeline.watchdog import stop_watchdog

        actions["stop_watchdog"] = stop_watchdog()
    except Exception as exc:  # noqa: BLE001
        actions["stop_watchdog"] = {"ok": False, "error": str(exc)}

    try:
        from pipeline.daemon import stop_daemon

        actions["stop_daemon"] = stop_daemon()
    except Exception as exc:  # noqa: BLE001
        actions["stop_daemon"] = {"ok": False, "error": str(exc)}

    actions["stop_uv_tool_processes"] = stop_uv_tool_processes()

    extra_killed: list[int] = []
    extra_failed: list[int] = []
    home_s = str((ctx_home or Path.home() / ".context-engine").resolve()).lower()
    try:
        import psutil
    except ImportError:
        psutil = None  # type: ignore[assignment]

    if psutil is not None:
        for proc in psutil.process_iter(["pid", "exe", "cmdline"]):
            try:
                info = proc.info
                pid = int(info["pid"])
                if pid == my_pid:
                    continue  # Never kill ourselves (wipe, stop, etc.)
                cmdline = info.get("cmdline") or []
                joined = " ".join(str(x) for x in cmdline).lower()
                if not _cmdline_matches_ce(cmdline) and home_s not in joined:
                    continue
                result = safe_terminate_pid(pid, grace_s=1.0)
                if result.get("terminated"):
                    extra_killed.append(pid)
                elif result.get("skipped") == "not_context_engine":
                    extra_failed.append(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError, ValueError):
                extra_failed.append(int(info.get("pid") or 0))
    time.sleep(1.0)
    actions["extra_killed"] = sorted(set(extra_killed))
    actions["extra_failed"] = sorted(set(x for x in extra_failed if x))
    root = uv_tool_root()
    remaining = [p for p in (processes_under(root) if root else []) if p != my_pid]
    actions["remaining"] = remaining
    actions["ok"] = not remaining
    return actions


def remove_tool_shims() -> dict[str, Any]:
    """Remove uv tool shims that break when the env is half-deleted."""
    local_bin = Path.home() / ".local" / "bin"
    removed: list[str] = []
    failed: list[str] = []
    for name in ("scubiee.exe", "scubiee", "ctx.exe", "ctx", "ctx-mcp.exe", "ctx-mcp"):
        shim = local_bin / name
        if not shim.exists():
            continue
        try:
            shim.unlink(missing_ok=True)
            removed.append(str(shim))
        except OSError:
            failed.append(str(shim))
    return {"removed": removed, "failed": failed, "ok": not failed}


def force_remove_uv_tool_dir(*, python: Path | None = None) -> dict[str, Any]:
    """Last-resort delete when ``uv tool uninstall`` fails on Windows locks."""
    root = uv_tool_root(python)
    if root is None:
        return {"ok": True, "skipped": "not_uv_tool"}
    stop = stop_all_context_engine_processes()
    if root.exists():
        try:
            shutil.rmtree(root, ignore_errors=False)
        except OSError as exc:
            try:
                shutil.rmtree(root, ignore_errors=True)
            except OSError:
                pass
            if root.exists():
                return {
                    "ok": False,
                    "error": "rmtree_failed",
                    "detail": str(exc),
                    "stop": stop,
                    "hint": "Quit Cursor completely (MCP holds python.exe), then re-run wipe.",
                }
    shims = remove_tool_shims()
    return {"ok": not root.exists(), "root": str(root), "stop": stop, "shims": shims}


def uv_tool_uninstall(*, python: Path | None = None) -> dict[str, Any]:
    """Stop locks, then ``uv tool uninstall scubiee``."""
    root = uv_tool_root(python)
    stop = stop_all_context_engine_processes()
    uv = shutil.which("uv")
    if not uv:
        return {"ok": False, "error": "uv_not_found", "stop": stop}
    proc = subprocess.run(
        [uv, "tool", "uninstall", "scubiee"],
        capture_output=True,
        text=True,
        check=False,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    ok = proc.returncode == 0
    if root and root.exists():
        forced = force_remove_uv_tool_dir(python=python)
        if not forced.get("ok"):
            return {
                "ok": False,
                "error": forced.get("error", "tool_dir_still_locked"),
                "stop": stop,
                "uv_output": out.strip()[-500:],
                "forced": forced,
                "hint": (
                    "Quit Cursor completely (MCP keeps python.exe open), then run: "
                    "powershell -ExecutionPolicy Bypass -File scripts/uninstall-uv-scubiee.ps1"
                ),
            }
        ok = True
    shims = remove_tool_shims()
    if shims.get("failed"):
        ok = False
    return {
        "ok": ok and (root is None or not root.exists()),
        "stop": stop,
        "shims": shims,
        "uv_returncode": proc.returncode,
        "uv_output": out.strip()[-500:],
    }
