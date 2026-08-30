"""Stop scubiee-related processes so Windows can delete uv tool files."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from pipeline.project_id import context_engine_home


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


def _pid_in_our_ancestry(pid: int, self_pid: int | None = None) -> bool:
    """True if *pid* is us or an ancestor (taskkill /T on it would kill unlock)."""
    me = os.getpid() if self_pid is None else self_pid
    if pid == me:
        return True
    try:
        import psutil

        cur = me
        for _ in range(64):
            try:
                cur = psutil.Process(cur).ppid()
            except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
                break
            if not cur or cur <= 0:
                break
            if cur == pid:
                return True
    except Exception:  # noqa: BLE001
        return False
    return False


def _terminate_pid_no_tree(pid: int) -> None:
    """Kill *pid* and its children except our own process tree."""
    me = os.getpid()
    try:
        import psutil

        proc = psutil.Process(pid)
        for child in proc.children(recursive=True):
            if child.pid == me or _pid_in_our_ancestry(child.pid, me):
                continue
            try:
                child.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if pid != me and not _pid_in_our_ancestry(pid, me):
            proc.kill()
        return
    except Exception:  # noqa: BLE001
        pass
    if os.name == "nt":
        # No /T — tree kill can take down the unlock process via a parent python.
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def stop_processes_under(
    root: Path,
    *,
    grace_s: float = 1.0,
    exclude_pids: set[int] | None = None,
) -> dict[str, Any]:
    """Terminate processes locking files under *root* (Windows-safe).

    Never kills the current process or its ancestors. Critical for
    ``scubiee unlock-tool`` (runs from uv-tool python; a parent python shim
    often also lives under the same tool dir — ``taskkill /T`` on it suicides).
    """
    skip = set(exclude_pids or ())
    skip.add(os.getpid())
    killed: list[int] = []
    failed: list[int] = []
    skipped: list[int] = []
    for pid in processes_under(root):
        if pid in skip or _pid_in_our_ancestry(pid):
            skipped.append(pid)
            continue
        try:
            _terminate_pid_no_tree(pid)
            killed.append(pid)
        except OSError:
            failed.append(pid)
    if grace_s:
        time.sleep(min(grace_s, 2.0))
    remaining = [
        p for p in processes_under(root) if p not in skip and not _pid_in_our_ancestry(p)
    ]
    return {
        "root": str(root),
        "killed": killed,
        "failed": failed,
        "skipped": skipped,
        "remaining": remaining,
        "ok": not remaining,
    }


def stop_uv_tool_processes(python: Path | None = None) -> dict[str, Any]:
    root = uv_tool_root(python)
    if root is None:
        return {"ok": True, "skipped": "not_uv_tool"}
    return stop_processes_under(root, exclude_pids={os.getpid()})


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
        "scubiee",
    )
    return any(m in cmdline for m in markers)


def safe_terminate_pid(pid: int, *, grace_s: float = 1.0) -> dict[str, Any]:
    """Terminate *pid* only when it matches CE; never kill ourselves or ancestors."""
    from pipeline.daemon import _pid_alive

    if not _pid_alive(pid):
        return {"pid": pid, "ok": True, "skipped": "not_alive"}
    if pid == os.getpid() or _pid_in_our_ancestry(pid):
        return {"pid": pid, "ok": True, "skipped": "self_or_ancestor"}
    if not is_context_engine_process(pid):
        return {"pid": pid, "ok": False, "skipped": "not_context_engine"}
    try:
        _terminate_pid_no_tree(pid)
        return {"pid": pid, "ok": True, "terminated": True}
    except OSError as exc:
        return {"pid": pid, "ok": False, "error": str(exc)}


def _cmdline_matches_ce(cmdline: list[str] | None) -> bool:
    if not cmdline:
        return False
    joined = " ".join(str(x) for x in cmdline).lower().replace("/", "\\")
    needles = (
        "scubiee",
        "scubiee-mcp",
        "ctx-mcp",
        r"uv\tools\scubiee",
        "context-engine",
        ".scubiee",
        "pipeline.mcp_locate",
        "pipeline.mcp_server",
        "pipeline.__main__",
        "pipeline.engine",
        "pipeline.watchdog",
        "pipeline.server",
        "pipeline.daemon",
        "pipeline.sync_loop",
    )
    return any(n in joined for n in needles)


def _exe_matches_scubiee(exe: str | None) -> bool:
    if not exe:
        return False
    low = str(exe).lower().replace("/", "\\")
    return (
        "scubiee" in low
        or "ctx-mcp" in low
        or r"uv\tools\scubiee" in low
        or "context-engine" in low
    )


def enumerate_scubiee_processes(*, exclude_self: bool = True) -> list[dict[str, Any]]:
    """Return PIDs that look like Scubiee daemon/MCP/engine (not arbitrary python)."""
    my_pid = os.getpid()
    found: list[dict[str, Any]] = []
    try:
        import psutil
    except ImportError:
        return found

    for proc in psutil.process_iter(["pid", "exe", "cmdline", "name"]):
        try:
            info = proc.info
            pid = int(info["pid"])
            if exclude_self and (pid == my_pid or _pid_in_our_ancestry(pid)):
                continue
            cmdline = info.get("cmdline") or []
            exe = info.get("exe") or ""
            if (
                is_context_engine_process(pid)
                or _exe_matches_scubiee(exe)
                or _cmdline_matches_ce(cmdline)
            ):
                found.append(
                    {
                        "pid": pid,
                        "exe": exe,
                        "cmdline": " ".join(str(x) for x in cmdline)[:240],
                    }
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError, ValueError):
            continue
    return found


def kill_all_scubiee_processes(
    *,
    exclude_self: bool = True,
    rounds: int = 3,
) -> dict[str, Any]:
    """Kill every Scubiee-related process (for wipe --all after state is gone)."""
    actions: dict[str, Any] = {}
    actions["stop_engine_workers"] = stop_engine_worker_processes()
    actions["stop_all"] = stop_all_context_engine_processes()

    killed_rounds: list[list[int]] = []
    for _ in range(max(1, rounds)):
        round_killed: list[int] = []
        for proc in enumerate_scubiee_processes(exclude_self=exclude_self):
            pid = int(proc["pid"])
            result = safe_terminate_pid(pid, grace_s=0.5)
            if result.get("terminated"):
                round_killed.append(pid)
        killed_rounds.append(round_killed)
        if not enumerate_scubiee_processes(exclude_self=exclude_self):
            break
        time.sleep(0.75)

    root = uv_tool_root()
    if root is not None:
        skip = {os.getpid()} if exclude_self else set()
        actions["stop_uv_tool"] = stop_processes_under(root, exclude_pids=skip)

    remaining = enumerate_scubiee_processes(exclude_self=exclude_self)
    actions["killed_rounds"] = killed_rounds
    actions["remaining"] = remaining
    actions["remaining_pids"] = [p["pid"] for p in remaining]
    actions["ok"] = not remaining
    actions["self_pid"] = os.getpid()
    return actions


def stop_engine_worker_processes() -> dict[str, Any]:
    """Terminate orphan ``python -m pipeline.engine`` workers (not this CLI)."""
    killed: list[int] = []
    skipped: list[int] = []
    my_pid = os.getpid()
    try:
        import psutil
    except ImportError:
        return {"ok": True, "killed": [], "skipped": "no_psutil"}

    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            info = proc.info
            pid = int(info["pid"])
            if pid == my_pid:
                continue
            cmdline = info.get("cmdline") or []
            joined = " ".join(str(x) for x in cmdline).lower()
            if "pipeline.engine" not in joined:
                continue
            result = safe_terminate_pid(pid, grace_s=1.5)
            if result.get("terminated"):
                killed.append(pid)
            else:
                skipped.append(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError, ValueError):
            continue
    return {"ok": True, "killed": sorted(set(killed)), "skipped": sorted(set(skipped))}


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
    home = ctx_home or context_engine_home()
    home_s = str(home.resolve()).lower() if home.exists() else ""
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
                exe = info.get("exe") or ""
                matches = (
                    _cmdline_matches_ce(cmdline)
                    or _exe_matches_scubiee(exe)
                    or is_context_engine_process(pid)
                )
                if not matches and (not home_s or home_s not in joined):
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
    remaining = enumerate_scubiee_processes(exclude_self=True)
    actions["remaining"] = remaining
    actions["remaining_pids"] = [p["pid"] for p in remaining]
    # ok if only this wipe/stop CLI remains (excluded from enumerate).
    actions["ok"] = not remaining
    actions["self_pid"] = my_pid
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


_ACCESS_DENIED_HINT = (
    "Admin/reboot will not help — file locks, not ACLs. "
    "Quit Cursor (or disable Scubiee MCP), then run: "
    "scubiee unlock-tool  OR  "
    "powershell -ExecutionPolicy Bypass -File scripts/uninstall-uv-scubiee.ps1"
)


def disable_mcp_to_prevent_respawn(*, project: Path | None = None) -> dict[str, Any]:
    """Disable Scubiee in global + optional project MCP so hosts don't respawn lockers."""
    from pipeline.pause_resume import _disable_mcp_for_tool, _disable_mcp_json
    from pipeline.tool_registry import TOOLS

    disabled: list[str] = []
    for tool in TOOLS:
        try:
            disabled.extend(_disable_mcp_for_tool(tool))
        except Exception:  # noqa: BLE001
            continue

    # Project pins (Cursor/Kiro/etc.) respawn independently of global MCP.
    roots: list[Path] = []
    if project is not None:
        roots.append(Path(project).resolve())
    try:
        roots.append(Path.cwd().resolve())
    except OSError:
        pass
    seen: set[str] = set()
    project_targets: tuple[tuple[tuple[str, ...], str, str], ...] = (
        ((".cursor",), "mcp.json", "mcpServers"),
        ((".kiro", "settings"), "mcp.json", "mcpServers"),
        ((".vscode",), "mcp.json", "servers"),
        ((".cline",), "mcp.json", "mcpServers"),
        ((".roo",), "mcp.json", "mcpServers"),
    )
    for root in roots:
        key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        for dirs, fname, json_key in project_targets:
            path = root.joinpath(*dirs, fname)
            if _disable_mcp_json(path, json_key):
                disabled.append(str(path))

    return {"ok": True, "disabled": sorted(set(disabled))}


def _rmtree_with_retries(
    path: Path,
    *,
    attempts: int = 5,
    delay_s: float = 0.5,
) -> dict[str, Any]:
    """Delete *path* with backoff.

    On Windows, **rename-aside first** then delete the trash. In-place
    ``rmtree`` can remove ``Lib/`` then fail on locked ``python.exe``, leaving
    a half-deleted env where ``scubiee`` raises ModuleNotFoundError.
    """
    attempts_log: list[dict[str, Any]] = []
    last_err = ""
    for i in range(max(1, attempts)):
        if not path.exists():
            return {"ok": True, "attempts": attempts_log, "path": str(path)}

        if os.name == "nt":
            trash = path.with_name(f"{path.name}.trash-{os.getpid()}-{i}")
            try:
                path.rename(trash)
                attempts_log.append({"n": i + 1, "action": "rename", "ok": True, "to": str(trash)})
                try:
                    shutil.rmtree(trash, ignore_errors=True)
                except OSError as exc:
                    last_err = str(exc)
                    attempts_log.append(
                        {"n": i + 1, "action": "rmtree_trash", "ok": False, "error": last_err}
                    )
                    # Original path is free even if trash delete is deferred.
                    _schedule_delete_after_exit(trash, os.getpid())
                if not path.exists():
                    return {"ok": True, "attempts": attempts_log, "path": str(path)}
            except OSError as exc:
                last_err = str(exc)
                attempts_log.append({"n": i + 1, "action": "rename", "ok": False, "error": last_err})
        else:
            try:
                shutil.rmtree(path, ignore_errors=False)
                if not path.exists():
                    attempts_log.append({"n": i + 1, "action": "rmtree", "ok": True})
                    return {"ok": True, "attempts": attempts_log, "path": str(path)}
            except OSError as exc:
                last_err = str(exc)
                attempts_log.append({"n": i + 1, "action": "rmtree", "ok": False, "error": last_err})

        stop_all_context_engine_processes()
        time.sleep(delay_s * (i + 1))

    return {
        "ok": not path.exists(),
        "attempts": attempts_log,
        "path": str(path),
        "error": None if not path.exists() else (last_err or "rmtree_failed"),
    }


def _running_from_uv_tool(root: Path | None, python: Path | None = None) -> bool:
    """True when *this* process's interpreter lives under the uv tool root.

    *python* is ignored for the check — it only selects which tool dir to remove.
    Using it here falsely triggered rename/schedule when unlocking from conda/system
    Python while passing an explicit tool interpreter path.
    """
    if root is None:
        return False
    del python  # selection only; see docstring
    return _exe_under_root(str(Path(sys.executable)), root)


def _schedule_delete_after_exit(path: Path, wait_pid: int) -> dict[str, Any]:
    """Detach a cleaner that waits for *wait_pid* then deletes *path*."""
    path_s = str(path)
    if os.name == "nt":
        lit = path_s.replace("'", "''")
        ps = (
            f"Wait-Process -Id {int(wait_pid)} -ErrorAction SilentlyContinue; "
            f"Start-Sleep -Seconds 2; "
            f"$p = '{lit}'; "
            "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
            "Where-Object { $_.ExecutablePath -and $_.ExecutablePath -like ($p + '*') } | "
            "ForEach-Object { taskkill /PID $_.ProcessId /T /F 2>$null | Out-Null }; "
            "Start-Sleep -Seconds 1; "
            "Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue"
        )
        flags = 0
        if hasattr(subprocess, "DETACHED_PROCESS"):
            flags |= subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            flags |= subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        # CREATE_NO_WINDOW
        flags |= 0x08000000
        subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps,
            ],
            close_fds=True,
            creationflags=flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        return {
            "ok": True,
            "scheduled": True,
            "waiter": "powershell",
            "path": path_s,
            "wait_pid": wait_pid,
        }

    import shlex

    script = (
        f"while kill -0 {int(wait_pid)} 2>/dev/null; do sleep 0.5; done; "
        f"sleep 1; rm -rf {shlex.quote(path_s)}"
    )
    subprocess.Popen(
        ["/bin/bash", "-c", script],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )
    return {
        "ok": True,
        "scheduled": True,
        "waiter": "bash",
        "path": path_s,
        "wait_pid": wait_pid,
    }


def force_remove_uv_tool_dir(
    *,
    python: Path | None = None,
    stop_first: bool = True,
) -> dict[str, Any]:
    """Last-resort delete when ``uv tool uninstall`` fails on Windows locks."""
    root = uv_tool_root(python)
    if root is None:
        return {"ok": True, "skipped": "not_uv_tool"}
    stop: dict[str, Any] = {"ok": True, "skipped": "stop_first=false"}
    if stop_first:
        stop = stop_all_context_engine_processes()

    if not root.exists():
        shims = remove_tool_shims()
        return {"ok": True, "root": str(root), "stop": stop, "shims": shims}

    # Running *from* the tool env: we lock python.exe ourselves. Rename-aside so
    # the original path is free for reinstall, then delete trash after we exit.
    if _running_from_uv_tool(root, python):
        trash = root.with_name(f"{root.name}.trash-{os.getpid()}")
        rename_err = None
        try:
            root.rename(trash)
            target = trash
        except OSError as exc:
            rename_err = str(exc)
            target = root
        schedule = _schedule_delete_after_exit(target, os.getpid())
        shims = remove_tool_shims()
        return {
            "ok": not root.exists() or bool(schedule.get("ok")),
            "scheduled": True,
            "renamed_to": str(trash) if rename_err is None else None,
            "rename_error": rename_err,
            "schedule": schedule,
            "root": str(root),
            "stop": stop,
            "shims": shims,
            "hint": (
                "Unlock finishes after this process exits. Then reinstall: "
                "uv tool install --force scubiee --index-url https://pypi.org/simple"
            ),
        }

    remove = _rmtree_with_retries(root)
    if not remove.get("ok"):
        return {
            "ok": False,
            "error": "rmtree_failed",
            "detail": remove.get("error"),
            "remove": remove,
            "stop": stop,
            "hint": _ACCESS_DENIED_HINT,
        }
    shims = remove_tool_shims()
    return {
        "ok": not root.exists(),
        "root": str(root),
        "stop": stop,
        "remove": remove,
        "shims": shims,
    }


def prepare_uv_tool_directory_for_swap(
    *,
    python: Path | None = None,
    project: Path | None = None,
    remove_dir: bool = False,
) -> dict[str, Any]:
    """MCP-off → stop lockers → optional force-remove. Call before uv tool install/upgrade."""
    mcp = disable_mcp_to_prevent_respawn(project=project)
    stop = stop_all_context_engine_processes()
    report: dict[str, Any] = {
        "ok": bool(stop.get("ok", True)),
        "mcp": mcp,
        "stop": stop,
    }
    if remove_dir:
        forced = force_remove_uv_tool_dir(python=python, stop_first=False)
        report["force_remove"] = forced
        report["ok"] = bool(forced.get("ok"))
        if not report["ok"]:
            report["error"] = forced.get("error", "tool_dir_still_locked")
            report["hint"] = forced.get("hint") or _ACCESS_DENIED_HINT
    elif not report["ok"]:
        report["error"] = "processes_still_running"
        report["hint"] = _ACCESS_DENIED_HINT
    return report


def unlock_uv_tool_env(*, python: Path | None = None, project: Path | None = None) -> dict[str, Any]:
    """Public API for ``scubiee unlock-tool`` — free the uv tool dir without uninstalling."""
    report = prepare_uv_tool_directory_for_swap(
        python=python,
        project=project,
        remove_dir=True,
    )
    forced = report.get("force_remove") or {}
    if forced.get("scheduled"):
        report["scheduled"] = True
        report["ok"] = True
        report["hint"] = forced.get("hint") or report.get("hint")
    return report


def uv_tool_uninstall(*, python: Path | None = None) -> dict[str, Any]:
    """MCP-off → stop locks → ``uv tool uninstall scubiee`` → force-remove if needed."""
    root = uv_tool_root(python)
    prep = prepare_uv_tool_directory_for_swap(python=python, remove_dir=False)
    stop = prep.get("stop") or {}
    uv = shutil.which("uv")
    if not uv:
        return {"ok": False, "error": "uv_not_found", "prep": prep, "stop": stop}
    proc = subprocess.run(
        [uv, "tool", "uninstall", "scubiee"],
        capture_output=True,
        text=True,
        check=False,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    ok = proc.returncode == 0
    if root and root.exists():
        forced = force_remove_uv_tool_dir(python=python, stop_first=True)
        if not forced.get("ok"):
            return {
                "ok": False,
                "error": forced.get("error", "tool_dir_still_locked"),
                "prep": prep,
                "stop": stop,
                "uv_output": out.strip()[-500:],
                "forced": forced,
                "hint": forced.get("hint") or _ACCESS_DENIED_HINT,
            }
        ok = True
    shims = remove_tool_shims()
    if shims.get("failed"):
        ok = False
    return {
        "ok": ok and (root is None or not root.exists()),
        "prep": prep,
        "stop": stop,
        "shims": shims,
        "uv_returncode": proc.returncode,
        "uv_output": out.strip()[-500:],
    }
