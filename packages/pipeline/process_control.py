"""Stop scubiee-related processes so Windows can delete uv tool files."""

from __future__ import annotations

import json
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
    from pipeline.process_job import hidden_run

    out = hidden_run(
        ["wmic", "process", "get", "ProcessId,ExecutablePath", "/FORMAT:CSV"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
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


def _protected_process_tree_pids(self_pid: int | None = None) -> set[int]:
    """PIDs that must never be killed during stop/wipe (this CLI + tree)."""
    me = os.getpid() if self_pid is None else self_pid
    protected = {me}
    try:
        import psutil

        proc = psutil.Process(me)
        for ancestor in proc.parents():
            protected.add(ancestor.pid)
        for child in proc.children(recursive=True):
            protected.add(child.pid)
    except Exception:  # noqa: BLE001
        pass
    return protected


def _pid_is_protected(pid: int, self_pid: int | None = None) -> bool:
    if pid in _protected_process_tree_pids(self_pid):
        return True
    return _pid_in_our_ancestry(pid, self_pid)


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
        from pipeline.process_job import taskkill_silent

        taskkill_silent(int(pid), tree=False)
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
    skip.update(_protected_process_tree_pids())
    killed: list[int] = []
    failed: list[int] = []
    skipped: list[int] = []
    for pid in processes_under(root):
        if pid in skip or _pid_is_protected(pid):
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
        p for p in processes_under(root) if p not in skip and not _pid_is_protected(p)
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
        "pipeline engine",  # CLI: python -m pipeline engine run
        "pipeline.mcp_locate",
        "pipeline.mcp_server",
        "pipeline.watchdog",
        "pipeline watchdog",
        "pipeline.__main__",
        "scubiee",
    )
    return any(m in cmdline for m in markers)


def safe_terminate_pid(
    pid: int,
    *,
    grace_s: float = 1.0,
    allow_child: bool = False,
) -> dict[str, Any]:
    """Terminate *pid* only when it matches CE; never kill ourselves or ancestors.

    ``allow_child=True`` lets ``stop_daemon`` kill a spawned ``engine run`` child
    (protected-tree otherwise skips descendants, leaving ~1GB zombies).
    """
    from pipeline.daemon import _pid_alive

    if not _pid_alive(pid):
        return {"pid": pid, "ok": True, "skipped": "not_alive"}
    me = os.getpid()
    if pid == me:
        return {"pid": pid, "ok": True, "skipped": "self_or_ancestor"}
    if _pid_in_our_ancestry(pid, me):
        return {"pid": pid, "ok": True, "skipped": "self_or_ancestor"}
    if not allow_child and _pid_is_protected(pid):
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
        "pipeline.mcp_bridge",
        "mcp-bridge",
        "pipeline.__main__",
        "pipeline.engine",
        "pipeline engine",  # subcommand form (not import path)
        "pipeline.watchdog",
        "pipeline watchdog",
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
    """Return PIDs that look like Scubiee daemon/MCP/engine (not arbitrary python).

    Name-prefilter before cmdline — full cmdline scan of every process is too
    slow on Windows and hangs wipe/heal for minutes.
    """
    my_pid = os.getpid()
    found: list[dict[str, Any]] = []
    try:
        import psutil
    except ImportError:
        return found

    for proc in psutil.process_iter(["pid", "exe", "name"]):
        try:
            info = proc.info
            pid = int(info["pid"])
            name = str(info.get("name") or "").lower()
            exe = info.get("exe") or ""
            if not (
                any(tok in name for tok in ("python", "scubiee", "uv"))
                or _exe_matches_scubiee(exe)
            ):
                continue
            # Protection check is a full process-tree walk — only for survivors.
            if exclude_self and _pid_is_protected(pid, my_pid):
                continue
            cmdline = proc.cmdline() or []
            if (
                is_context_engine_process(pid)
                or _exe_matches_scubiee(exe)
                or _cmdline_matches_ce(cmdline)
            ):
                ppid = 0
                try:
                    ppid = int(proc.ppid() or 0)
                except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError, ValueError):
                    ppid = 0
                found.append(
                    {
                        "pid": pid,
                        "ppid": ppid,
                        "exe": exe,
                        "cmdline": " ".join(str(x) for x in cmdline)[:240],
                    }
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError, ValueError):
            continue
    return found


def pid_working_set_mb(pid: int) -> float | None:
    """Working set / RSS for *pid* in MiB (Windows Task Manager Memory column)."""
    if pid <= 0:
        return None
    try:
        import psutil

        return float(psutil.Process(int(pid)).memory_info().rss) / (1024 * 1024)
    except Exception:  # noqa: BLE001
        return None


def _frontend_parent_gone(pid: int) -> bool:
    """True when the MCP/bridge parent IDE process is dead (orphan worker)."""
    try:
        import psutil
    except ImportError:
        return False
    try:
        proc = psutil.Process(int(pid))
        ppid = int(proc.ppid() or 0)
    except Exception:  # noqa: BLE001
        return False
    if ppid <= 0:
        return True
    if os.name == "nt" and ppid in {0, 4}:
        return True
    try:
        parent = psutil.Process(ppid)
        if not parent.is_running():
            return True
        status = str(parent.status() or "").lower()
        return "zombi" in status
    except Exception:  # noqa: BLE001
        return True


def sweep_orphan_scubiee_frontends(
    *,
    keep_pids: set[int] | None = None,
) -> dict[str, Any]:
    """Kill MCP/bridge workers whose parent process is gone.

    Does not touch ``pipeline engine run`` or watchdog — those have detached
    parents by design. Closed IDEs must not leave ~1GB mcp python zombies.
    """
    keep = {int(p) for p in (keep_pids or set()) if int(p) > 0}
    keep.add(os.getpid())
    killed: list[int] = []
    skipped: list[dict[str, Any]] = []
    for proc in enumerate_scubiee_processes(exclude_self=True):
        pid = int(proc["pid"])
        if pid in keep:
            skipped.append({"pid": pid, "reason": "keep"})
            continue
        if not (_is_mcp_worker_process(proc) or _is_mcp_bridge_process(proc)):
            continue
        if not _frontend_parent_gone(pid):
            skipped.append({"pid": pid, "reason": "parent_alive"})
            continue
        result = safe_terminate_pid(pid, grace_s=0.8)
        if result.get("terminated"):
            killed.append(pid)
        else:
            skipped.append({"pid": pid, "reason": result.get("skipped") or result.get("error")})
    return {
        "ok": True,
        "killed": killed,
        "skipped": skipped,
    }


def _is_mcp_bridge_process(proc: dict[str, Any]) -> bool:
    cmdline = str(proc.get("cmdline") or "").lower().replace("/", "\\")
    exe = str(proc.get("exe") or "").lower().replace("/", "\\")
    return "mcp-bridge" in cmdline or "mcp_bridge" in cmdline or "mcp-bridge" in exe


def _is_mcp_worker_process(proc: dict[str, Any]) -> bool:
    if _is_mcp_bridge_process(proc):
        return False
    cmdline = str(proc.get("cmdline") or "").lower().replace("/", "\\")
    exe = str(proc.get("exe") or "").lower().replace("/", "\\")
    return (
        "scubiee-mcp" in cmdline
        or "scubiee-mcp" in exe
        or "pipeline.mcp_locate" in cmdline
        or "pipeline.mcp_server" in cmdline
    )


def kill_mcp_worker_processes(*, exclude_bridge: bool = True) -> dict[str, Any]:
    """Kill MCP worker processes; keep ``scubiee-mcp-bridge`` alive for hot reload."""
    killed: list[int] = []
    skipped: list[int] = []
    for proc in enumerate_scubiee_processes(exclude_self=True):
        pid = int(proc["pid"])
        if exclude_bridge and _is_mcp_bridge_process(proc):
            skipped.append(pid)
            continue
        if not _is_mcp_worker_process(proc):
            continue
        result = safe_terminate_pid(pid, grace_s=0.5)
        if result.get("terminated"):
            killed.append(pid)

    remaining_workers = [
        p
        for p in enumerate_scubiee_processes(exclude_self=True)
        if _is_mcp_worker_process(p) and not (exclude_bridge and _is_mcp_bridge_process(p))
    ]
    return {
        "ok": not remaining_workers,
        "killed": killed,
        "skipped_bridge_pids": skipped,
        "remaining_pids": [int(p["pid"]) for p in remaining_workers],
    }


def _pid_alive(pid: int) -> bool:
    from pipeline.daemon import _pid_alive as _alive

    try:
        return bool(_alive(int(pid)))
    except Exception:  # noqa: BLE001
        return False


def _is_durable_engine_process(proc: dict[str, Any]) -> bool:
    """Engine daemon / logon supervisor / watchdog — must survive IDE close."""
    cmdline = str(proc.get("cmdline") or "").lower().replace("/", "\\")
    return (
        "pipeline engine run" in cmdline
        or "pipeline engine supervisor" in cmdline
        or "pipeline engine watchdog" in cmdline
        or "-m pipeline engine run" in cmdline
        or "-m pipeline engine supervisor" in cmdline
        or "pipeline.watchdog" in cmdline
        or "-m pipeline watchdog" in cmdline
        or "_boot_watchdog.pyw" in cmdline
        or "_boot_supervisor.pyw" in cmdline
    )


def reap_orphaned_mcp_processes(*, keep_pids: set[int] | None = None) -> dict[str, Any]:
    """Kill MCP bridge/worker trees whose parent is gone (Cursor close leftover).

    Never touches engine run / supervisor / watchdog.
    """
    keep = {int(p) for p in (keep_pids or set())}
    keep.add(int(os.getpid()))
    killed: list[int] = []
    skipped: list[int] = []
    for proc in enumerate_scubiee_processes(exclude_self=True):
        pid = int(proc["pid"])
        if pid in keep:
            skipped.append(pid)
            continue
        if _is_durable_engine_process(proc):
            skipped.append(pid)
            continue
        if not (_is_mcp_bridge_process(proc) or _is_mcp_worker_process(proc)):
            continue
        ppid = int(proc.get("ppid") or 0)
        if ppid > 0 and _pid_alive(ppid):
            skipped.append(pid)
            continue
        result = safe_terminate_pid(pid, grace_s=0.5, allow_child=True)
        if result.get("terminated"):
            killed.append(pid)
        else:
            skipped.append(pid)
    remaining = [
        p
        for p in enumerate_scubiee_processes(exclude_self=True)
        if (_is_mcp_bridge_process(p) or _is_mcp_worker_process(p))
        and not _is_durable_engine_process(p)
        and not _pid_alive(int(p.get("ppid") or 0))
        and int(p["pid"]) not in keep
    ]
    return {
        "ok": not remaining,
        "killed": killed,
        "skipped": skipped,
        "remaining_pids": [int(p["pid"]) for p in remaining],
    }


def kill_all_scubiee_processes(
    *,
    exclude_self: bool = True,
    exclude_bridge: bool = False,
    rounds: int = 3,
) -> dict[str, Any]:
    """Kill every Scubiee-related process (for wipe --all after state is gone).

    When ``exclude_bridge`` is true, ``scubiee-mcp-bridge`` stdio proxies stay alive
    so IDE MCP sessions survive upgrade quiesce and hot-reload can respawn workers.
    """
    actions: dict[str, Any] = {"exclude_bridge": exclude_bridge}
    actions["stop_engine_workers"] = stop_engine_worker_processes()
    actions["stop_all"] = stop_all_context_engine_processes()

    skipped_bridge: list[int] = []
    killed_rounds: list[list[int]] = []
    for _ in range(max(1, rounds)):
        round_killed: list[int] = []
        for proc in enumerate_scubiee_processes(exclude_self=exclude_self):
            pid = int(proc["pid"])
            if exclude_bridge and _is_mcp_bridge_process(proc):
                skipped_bridge.append(pid)
                continue
            result = safe_terminate_pid(pid, grace_s=0.5)
            if result.get("terminated"):
                round_killed.append(pid)
        killed_rounds.append(round_killed)
        remaining_now = [
            p
            for p in enumerate_scubiee_processes(exclude_self=exclude_self)
            if not (exclude_bridge and _is_mcp_bridge_process(p))
        ]
        if not remaining_now:
            break
        time.sleep(0.75)

    root = uv_tool_root()
    if root is not None:
        skip = _protected_process_tree_pids() if exclude_self else set()
        if exclude_bridge:
            skip.update(skipped_bridge)
        actions["stop_uv_tool"] = stop_processes_under(root, exclude_pids=skip)

    remaining = [
        p
        for p in enumerate_scubiee_processes(exclude_self=exclude_self)
        if not (exclude_bridge and _is_mcp_bridge_process(p))
    ]
    actions["killed_rounds"] = killed_rounds
    actions["skipped_bridge_pids"] = sorted(set(skipped_bridge))
    actions["remaining"] = remaining
    actions["remaining_pids"] = [p["pid"] for p in remaining]
    actions["ok"] = not remaining
    actions["self_pid"] = os.getpid()
    return actions


def _cmdline_is_engine_run(
    cmdline: list[str] | None,
    *,
    port: int | None = None,
) -> bool:
    """True for ``python -m pipeline engine run …`` (not watchdog / other subcommands)."""
    if not cmdline:
        return False
    parts = [str(x).lower() for x in cmdline]
    joined = " ".join(parts)
    if "pipeline engine run" not in joined and "pipeline.engine" not in joined:
        return False
    if "pipeline engine watchdog" in joined or "pipeline.watchdog" in joined:
        return False
    if port is None:
        return True
    # Match explicit --port N when present; bare runs default to 8765.
    port_s = str(int(port))
    for i, tok in enumerate(parts):
        if tok in {"--port", "-p"} and i + 1 < len(parts):
            return parts[i + 1] == port_s
    return int(port) == 8765


def enumerate_engine_run_pids(*, port: int | None = None) -> list[int]:
    """PIDs whose cmdline is an engine ``run`` worker (optionally filtered by port).

    On Windows, prefer lock/pid files + ``netstat`` only — full process cmdline
    scans take tens of seconds and made heal/stop look hung.
    """
    found: list[int] = []
    try:
        from pipeline.daemon import _read_lock_pid, pid_path

        lock_pid = _read_lock_pid()
        if lock_pid:
            found.append(int(lock_pid))
        path = pid_path()
        if path.is_file():
            try:
                found.append(int(path.read_text(encoding="utf-8").strip()))
            except (OSError, ValueError):
                pass
    except Exception:  # noqa: BLE001
        pass

    if port is not None:
        found.extend(pids_listening_on_port(int(port)))

    if os.name == "nt" and not (os.environ.get("CTX_ENGINE_ENUM_FULL") or "").strip():
        # Skip psutil cmdline walk on Windows (too slow under load).
        # Tests can set CTX_ENGINE_ENUM_FULL=1 to exercise the full scan.
        return sorted(set(p for p in found if p > 0))

    try:
        import psutil
    except ImportError:
        return sorted(set(p for p in found if p > 0))

    my_pid = os.getpid()
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            info = proc.info
            pid = int(info["pid"])
            name = str(info.get("name") or "").lower()
            if not any(tok in name for tok in ("python", "scubiee")):
                continue
            if pid == my_pid or _pid_is_protected(pid):
                continue
            cmdline = proc.cmdline() or []
            if _cmdline_is_engine_run(cmdline, port=port):
                found.append(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError, ValueError):
            continue
    return sorted(set(p for p in found if p > 0))


def pids_listening_on_port(port: int) -> list[int]:
    """Best-effort: PIDs with a LISTEN socket on *port* (Windows orphan catch).

    Prefer ``netstat`` on Windows — ``psutil.net_connections()`` can stall for
    minutes under heavy connection tables / AccessDenied scans.
    """
    found: list[int] = []
    port_s = str(int(port))
    if os.name == "nt":
        try:
            proc = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            for line in (proc.stdout or "").splitlines():
                # TCP    0.0.0.0:8765    0.0.0.0:0    LISTENING    1234
                if "LISTENING" not in line.upper():
                    continue
                parts = line.split()
                if len(parts) < 5:
                    continue
                local = parts[1]
                if not (local.endswith(":" + port_s) or local.endswith("]." + port_s)):
                    # IPv6 forms like [::]:8765
                    if ":" + port_s not in local and local.rstrip().endswith(port_s) is False:
                        continue
                    if not local.endswith(":" + port_s):
                        continue
                try:
                    found.append(int(parts[-1]))
                except ValueError:
                    continue
            return sorted(set(found))
        except (OSError, subprocess.TimeoutExpired):
            return []

    try:
        import psutil
    except ImportError:
        return found
    try:
        for conn in psutil.net_connections(kind="inet"):
            try:
                if conn.status != psutil.CONN_LISTEN:
                    continue
                laddr = conn.laddr
                if not laddr or int(getattr(laddr, "port", 0) or 0) != int(port):
                    continue
                if conn.pid:
                    found.append(int(conn.pid))
            except (AttributeError, TypeError, ValueError, psutil.AccessDenied):
                continue
    except (psutil.AccessDenied, OSError):
        return sorted(set(found))
    return sorted(set(found))


def kill_all_engine_daemons(*, port: int = 8765, wait_s: float = 5.0) -> dict[str, Any]:
    """Hard-stop every engine ``run`` on *port* — PID + port sweep (no soft HTTP).

    Soft ``/v1/shutdown`` is intentionally omitted: a half-dead listener on Windows
    can accept the TCP connect and stall until the client timeout (minutes), which
    made ``scubiee heal`` / stop look hung. Hard kill + port sweep is enough.
    """
    from pipeline.daemon import is_running, release_lock

    killed: list[int] = []

    for pid in enumerate_engine_run_pids(port=port):
        result = safe_terminate_pid(pid, grace_s=1.0, allow_child=True)
        if result.get("terminated"):
            killed.append(pid)
        elif result.get("skipped") == "not_context_engine":
            # Force if cmdline matched engine run but marker check lagged.
            try:
                if os.name == "nt":
                    from pipeline.process_job import taskkill_silent

                    taskkill_silent(int(pid), tree=True)
                else:
                    os.kill(pid, 9)
                killed.append(pid)
            except OSError:
                pass
            except subprocess.TimeoutExpired:
                pass

    for pid in pids_listening_on_port(port):
        if pid in killed or pid == os.getpid() or _pid_in_our_ancestry(pid):
            continue
        if is_context_engine_process(pid) or pid in enumerate_engine_run_pids(port=None):
            result = safe_terminate_pid(pid, grace_s=0.5, allow_child=True)
            if result.get("terminated"):
                killed.append(pid)
            else:
                try:
                    if os.name == "nt":
                        from pipeline.process_job import taskkill_silent

                        taskkill_silent(int(pid), tree=True)
                    else:
                        os.kill(pid, 9)
                    killed.append(pid)
                except OSError:
                    pass
                except subprocess.TimeoutExpired:
                    pass

    try:
        release_lock()
    except Exception:  # noqa: BLE001
        pass

    deadline = time.time() + max(0.5, float(wait_s))
    while time.time() < deadline:
        still = enumerate_engine_run_pids(port=port)
        healthy = False
        try:
            healthy = is_running()
        except Exception:  # noqa: BLE001
            healthy = False
        if not still and not healthy:
            break
        for pid in still:
            if pid not in killed:
                safe_terminate_pid(pid, grace_s=0.3)
                killed.append(pid)
        time.sleep(0.25)

    still_pids = enumerate_engine_run_pids(port=port)
    still_healthy = False
    try:
        still_healthy = is_running()
    except Exception:  # noqa: BLE001
        still_healthy = False
    return {
        "ok": not still_pids and not still_healthy,
        "killed": sorted(set(killed)),
        "remaining_pids": still_pids,
        "still_healthy": still_healthy,
        "port": int(port),
    }


def stop_engine_worker_processes() -> dict[str, Any]:
    """Terminate orphan engine ``run`` / ``pipeline.engine`` workers (not this CLI)."""
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
            if not (
                "pipeline.engine" in joined
                or "pipeline engine run" in joined
                or ("pipeline engine" in joined and "watchdog" not in joined)
            ):
                continue
            if "watchdog" in joined:
                continue
            result = safe_terminate_pid(pid, grace_s=1.5)
            if result.get("terminated"):
                killed.append(pid)
            else:
                skipped.append(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError, ValueError):
            continue
    return {
        "ok": True,
        "killed": sorted(set(killed)),
        "skipped": sorted(set(skipped)),
    }


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
        for proc in psutil.process_iter(["pid", "exe", "name"]):
            try:
                info = proc.info
                pid = int(info["pid"])
                if pid == my_pid:
                    continue  # Never kill ourselves (wipe, stop, etc.)
                name = str(info.get("name") or "").lower()
                exe = info.get("exe") or ""
                # Reading cmdline for every process costs ~10s on Windows.
                if not (
                    any(tok in name for tok in ("python", "scubiee", "uv"))
                    or _exe_matches_scubiee(exe)
                ):
                    continue
                cmdline = proc.cmdline() or []
                joined = " ".join(str(x) for x in cmdline).lower()
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
    "You do not need to quit Cursor: `scubiee halt` then `scubiee unlock-tool` "
    "(or powershell -ExecutionPolicy Bypass -File scripts/uninstall-uv-scubiee.ps1). "
    "Quit the IDE only if those still fail."
)


_PROCESS_STILL_RUNNING_HINT = (
    "An IDE still holds a Scubiee MCP child (Cursor/Claude often ignore disable "
    "and respawn from memory). You do not need to quit the tool: "
    "`scubiee halt` already rewired MCP to a no-op. If files stay locked, run "
    "`scubiee unlock-tool` (renames the uv dir aside). Quit the IDE only as a last resort."
)

_MCP_STUB_SETTLE_S = 1.5
_MCP_STUB_POLL_MAX_S = 12.0


def _wait_for_lockers_gone(*, max_s: float) -> dict[str, Any]:
    """Poll until Scubiee worker PIDs clear (Cursor may respawn briefly after stub)."""
    t0 = time.time()
    last: list[int] = []
    while time.time() - t0 < max_s:
        last = [p["pid"] for p in enumerate_scubiee_processes(exclude_self=True)]
        if not last:
            return {"ok": True, "waited_s": round(time.time() - t0, 3), "remaining_pids": []}
        time.sleep(0.4)
    return {
        "ok": False,
        "waited_s": round(time.time() - t0, 3),
        "remaining_pids": last,
    }


def mcp_noop_command() -> tuple[str, list[str]]:
    """Command that exits immediately — safe for MCP hosts to respawn."""
    if os.name == "nt":
        return "cmd", ["/c", "exit", "0"]
    return "true", []


def _stub_server_entry(entry: dict[str, Any]) -> bool:
    """Rewrite one MCP server dict so a host respawn cannot lock Scubiee files.

    Only rewrite command/args to a no-op. Do **not** set ``enabled: false`` or
    ``disabled: true`` — Cursor stores that in UI state (``disabledMcpServers``)
    and leaves the toggle off after unlock/upgrade even when pins are restored.
    """
    cmd, args = mcp_noop_command()
    changed = False
    existing_cmd = entry.get("command")
    if isinstance(existing_cmd, list):
        new_cmd = [cmd, *args]
        if existing_cmd != new_cmd:
            entry["command"] = new_cmd
            changed = True
    else:
        if existing_cmd != cmd:
            entry["command"] = cmd
            changed = True
        if list(entry.get("args") or []) != args:
            entry["args"] = args
            changed = True
    # Keep enabled/disabled flags alone — restore_live_mcp_pins / connect clear them.
    return changed


def _servers_dict_from_json(data: dict[str, Any], key: str) -> dict[str, Any] | None:
    if key in data and isinstance(data[key], dict):
        return data[key]
    if "." in key:
        cur: Any = data
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
        return cur if isinstance(cur, dict) else None
    return None


def _stub_mcp_json_file(path: Path, key: str) -> bool:
    from pipeline.branding import MCP_SERVER_NAMES

    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    servers = _servers_dict_from_json(data, key)
    if not isinstance(servers, dict):
        return False
    changed = False
    for name in MCP_SERVER_NAMES:
        entry = servers.get(name)
        if isinstance(entry, dict) and _stub_server_entry(entry):
            changed = True
    if not changed:
        return False
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def _stub_mcp_toml_file(path: Path) -> bool:
    """Best-effort Codex-style TOML: point [mcp_servers.scubiee] at a no-op."""
    from pipeline.branding import MCP_SERVER_NAME

    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    marker = f"[mcp_servers.{MCP_SERVER_NAME}]"
    if marker not in text:
        return False
    cmd, args = mcp_noop_command()
    args_toml = ", ".join(f'"{a}"' for a in args)
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    in_section = False
    replaced_cmd = False
    replaced_args = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped == marker or stripped == f'[mcp_servers."{MCP_SERVER_NAME}"]'
        if in_section and stripped.startswith("command"):
            out.append(f'command = "{cmd}"\n' if not line.endswith("\r\n") else f'command = "{cmd}"\r\n')
            replaced_cmd = True
            continue
        if in_section and stripped.startswith("args"):
            out.append(f"args = [{args_toml}]\n")
            replaced_args = True
            continue
        out.append(line)
    if not replaced_cmd:
        return False
    if args and not replaced_args:
        # Insert args after command inside the section.
        rebuilt: list[str] = []
        inserted = False
        in_section = False
        for line in out:
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                in_section = stripped == marker or stripped == f'[mcp_servers."{MCP_SERVER_NAME}"]'
            rebuilt.append(line)
            if in_section and stripped.startswith("command") and not inserted:
                rebuilt.append(f"args = [{args_toml}]\n")
                inserted = True
        out = rebuilt
    new_text = "".join(out)
    if new_text == text:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def _yaml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _stub_mcp_continue_yaml(path: Path) -> bool:
    """Rewrite Continue YAML Scubiee command/args to a no-op.

    Handles both ``.continue/config.yaml`` (marked list) and standalone
    ``.continue/mcpServers/scubiee.yaml``.
    """
    from pipeline.branding import CONTINUE_YAML_MARKER, MCP_SERVER_NAME

    if not path.is_file() or path.suffix.lower() not in {".yaml", ".yml"}:
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    if MCP_SERVER_NAME not in text and CONTINUE_YAML_MARKER not in text:
        return False
    cmd, args = mcp_noop_command()
    args_yaml = ", ".join(_yaml_quote(a) for a in args)
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    in_scubiee = False
    replaced = False
    for line in lines:
        stripped = line.strip()
        indent = line[: len(line) - len(line.lstrip(" \t"))] if line.strip() else ""
        if CONTINUE_YAML_MARKER in line or (
            stripped.startswith("- name:") and MCP_SERVER_NAME in stripped
        ):
            in_scubiee = True
        elif in_scubiee and stripped.startswith("- name:") and MCP_SERVER_NAME not in stripped:
            in_scubiee = False
        elif in_scubiee and stripped and not line.startswith((" ", "\t")) and CONTINUE_YAML_MARKER not in line:
            in_scubiee = False
        if in_scubiee and stripped.startswith("command:"):
            nl = "\r\n" if line.endswith("\r\n") else "\n"
            out.append(f"{indent}command: {_yaml_quote(cmd)}{nl}")
            replaced = True
            continue
        if in_scubiee and stripped.startswith("args:"):
            nl = "\r\n" if line.endswith("\r\n") else "\n"
            out.append(f"{indent}args: [{args_yaml}]{nl}")
            replaced = True
            continue
        out.append(line)
    if not replaced:
        return False
    new_text = "".join(out)
    if new_text == text:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def _mcp_config_roots(*, project: Path | None = None) -> list[Path]:
    from pipeline.managed_repos import managed_repo_paths

    roots: list[Path] = []
    if project is not None:
        roots.append(Path(project).resolve())
    try:
        roots.append(Path.cwd().resolve())
    except OSError:
        pass
    for repo in managed_repo_paths(enrolled_only=False):
        roots.append(Path(repo).resolve())
    seen: set[str] = set()
    unique: list[Path] = []
    for root in roots:
        rkey = str(root).replace("\\", "/").lower()
        if rkey in seen:
            continue
        seen.add(rkey)
        unique.append(root)
    return unique


def stub_mcp_commands_to_noop(*, project: Path | None = None) -> dict[str, Any]:
    """Point every Scubiee MCP entry at a no-op so hosts can stay open.

    Cursor/Claude often ignore ``disabled`` and respawn from the last command.
    A no-op spawn exits immediately and does not lock ``uv/tools/scubiee``.
    """
    from pipeline.tool_registry import TOOL_MAP, resolve_mcp_legacy_global_paths, resolve_mcp_project_write_targets

    stubbed: list[str] = []
    for tool in TOOL_MAP.values():
        for path, schema, key in resolve_mcp_legacy_global_paths(tool):
            if not path.is_file():
                continue
            if schema == "codex" or path.suffix.lower() == ".toml":
                if _stub_mcp_toml_file(path):
                    stubbed.append(str(path))
            elif schema == "continue" or path.suffix.lower() in {".yaml", ".yml"}:
                if _stub_mcp_continue_yaml(path):
                    stubbed.append(str(path))
            elif _stub_mcp_json_file(path, key or "mcpServers"):
                stubbed.append(str(path))
        for root in _mcp_config_roots(project=project):
            for path, schema, key in resolve_mcp_project_write_targets(tool, root):
                if not path.is_file():
                    continue
                if schema == "codex" or path.suffix.lower() == ".toml":
                    if _stub_mcp_toml_file(path):
                        stubbed.append(str(path))
                elif schema == "continue" or path.suffix.lower() in {".yaml", ".yml"}:
                    if _stub_mcp_continue_yaml(path):
                        stubbed.append(str(path))
                elif _stub_mcp_json_file(path, key or "mcpServers"):
                    stubbed.append(str(path))
    return {"ok": True, "stubbed": sorted(set(stubbed))}


def disable_mcp_to_prevent_respawn(*, project: Path | None = None) -> dict[str, Any]:
    """Remove/disable Scubiee MCP everywhere so hosts don't respawn lockers mid-wipe."""
    from pipeline.managed_repos import managed_repo_paths
    from pipeline.pause_resume import _disable_mcp_for_tool, _disable_mcp_json
    from pipeline.rules_installer import remove_mcp_config
    from pipeline.tool_registry import TOOL_MAP, resolve_mcp_project_write_targets

    disabled: list[str] = []
    for tool in TOOL_MAP.values():
        try:
            disabled.extend(_disable_mcp_for_tool(tool))
        except Exception:  # noqa: BLE001
            continue

    roots: list[Path] = []
    if project is not None:
        roots.append(Path(project).resolve())
    try:
        roots.append(Path.cwd().resolve())
    except OSError:
        pass
    for repo in managed_repo_paths(enrolled_only=False):
        roots.append(Path(repo).resolve())

    seen: set[str] = set()
    for root in roots:
        rkey = str(root).replace("\\", "/").lower()
        if rkey in seen:
            continue
        seen.add(rkey)
        for tool in TOOL_MAP.values():
            for path, schema, key in resolve_mcp_project_write_targets(tool, root):
                if not path.is_file():
                    continue
                try:
                    if remove_mcp_config(tool, path, schema=schema, key=key):
                        disabled.append(str(path))
                        continue
                except Exception:  # noqa: BLE001
                    pass
                if path.suffix == ".json":
                    if _disable_mcp_json(path, key):
                        disabled.append(str(path))

    return {"ok": True, "disabled": sorted(set(disabled))}


def release_scubiee_process_locks(
    *,
    project: Path | None = None,
    rounds: int = 5,
    strip_mcp: bool = True,
    settle_s: float | None = None,
) -> dict[str, Any]:
    """Stub MCP → wait for host reload → kill Scubiee PIDs.

    Hosts (Cursor, Claude Code, …) often ignore ``disabled`` and respawn the
    last command without quitting. Stubbing to a no-op means a respawn cannot
    lock ``uv/tools/scubiee``. Optional ``strip_mcp`` then removes the keys.
    """
    report: dict[str, Any] = {"ok": True}

    report["mcp_stub"] = stub_mcp_commands_to_noop(project=project)
    wait = _MCP_STUB_SETTLE_S if settle_s is None else max(0.0, settle_s)
    if wait:
        time.sleep(wait)

    try:
        from pipeline.lifecycle_runtime import DESIRED_STANDBY, set_desired_mode

        set_desired_mode(DESIRED_STANDBY)
    except Exception as exc:  # noqa: BLE001
        report["lifecycle_mode"] = {"ok": False, "error": str(exc)}

    report["kill"] = kill_all_scubiee_processes(exclude_self=True, rounds=rounds)
    # Second pass after settle — Cursor often respawns once from in-memory config.
    report["locker_poll"] = _wait_for_lockers_gone(max_s=_MCP_STUB_POLL_MAX_S)
    if not report["locker_poll"].get("ok"):
        report["kill_retry"] = kill_all_scubiee_processes(exclude_self=True, rounds=2)

    if strip_mcp:
        report["mcp"] = disable_mcp_to_prevent_respawn(project=project)

    remaining = list(
        (report.get("kill_retry") or report["kill"]).get("remaining_pids")
        or report["kill"].get("remaining_pids")
        or []
    )
    if remaining:
        report["ok"] = False
        report["remaining_pids"] = remaining
        report["hint"] = _PROCESS_STILL_RUNNING_HINT
    return report


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
    strip_mcp: bool = True,
) -> dict[str, Any]:
    """MCP-off → stop lockers → optional force-remove. Call before uv tool install/upgrade.

    Pass ``strip_mcp=False`` for upgrades that will reconnect (stub only; restore pins after swap).
    """
    release = release_scubiee_process_locks(project=project, strip_mcp=strip_mcp)
    report: dict[str, Any] = {
        "ok": bool(release.get("ok", True)),
        "mcp": release.get("mcp") or {},
        "stop": release.get("kill") or {},
        "process_release": release,
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
