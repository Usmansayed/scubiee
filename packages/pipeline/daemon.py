"""Daemon lifecycle: start/stop/pid/lock for the Context Engine HTTP service."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from pipeline.client import DEFAULT_URL, EngineClient, engine_url


def _home() -> Path:
    from pipeline.project_id import context_engine_home

    return context_engine_home()


def pid_path() -> Path:
    return _home() / "engine.pid"


def lock_path() -> Path:
    return _home() / "engine.lock"


def log_path() -> Path:
    return _home() / "engine.log"


def meta_path() -> Path:
    return _home() / "engine.json"


def default_host_port() -> tuple[str, int]:
    url = engine_url()
    host, port = "127.0.0.1", 8765
    try:
        from urllib.parse import urlparse

        u = urlparse(url)
        if u.hostname:
            host = u.hostname
        if u.port:
            port = int(u.port)
    except Exception:  # noqa: BLE001
        pass
    return host, port


def is_running() -> bool:
    return EngineClient().healthy()


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
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


def _read_lock_pid() -> int | None:
    path = lock_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return int(data.get("pid") or 0) or None
    except Exception:  # noqa: BLE001
        try:
            return int(path.read_text(encoding="utf-8").strip())
        except Exception:  # noqa: BLE001
            return None


def acquire_lock(pid: int, *, url: str, repo: str) -> dict[str, Any]:
    """Write engine.lock. Clear stale lock if previous pid is dead."""
    _home().mkdir(parents=True, exist_ok=True)
    existing = _read_lock_pid()
    if existing is not None:
        if is_running():
            return {
                "ok": False,
                "already_running": True,
                "url": engine_url(),
                "lock_pid": existing,
            }
        if _pid_alive(existing) and existing != pid:
            return {
                "ok": False,
                "error": f"engine.lock held by live pid {existing} (not healthy)",
                "hint": "Stop with: ctx engine stop",
                "lock_pid": existing,
            }
        # stale
        try:
            lock_path().unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass

    payload = {"pid": pid, "url": url, "repo": repo, "acquired_at": time.time()}
    lock_path().write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, **payload}


def release_lock() -> None:
    try:
        lock_path().unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass
    try:
        pid_path().unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


def start_daemon(
    repo: Path | str | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
    wait_s: float = 90.0,
) -> dict[str, Any]:
    """Spawn Context Engine in background if not already healthy."""
    if is_running():
        return {"ok": True, "already_running": True, "url": engine_url()}

    # Stale lock with dead pid → clear; live lock without health → refuse
    existing = _read_lock_pid()
    if existing is not None and _pid_alive(existing) and not is_running():
        return {
            "ok": False,
            "error": f"engine.lock held by pid {existing} but /health is down",
            "hint": "ctx engine stop  or check engine.log",
            "log": str(log_path()),
        }

    h, p = default_host_port()
    host = host or h
    port = int(port or p)
    repo_s = str(Path(repo).resolve()) if repo else str(Path.cwd().resolve())

    _home().mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["CTX_ENGINE_URL"] = f"http://{host}:{port}"
    env["PYTHONUTF8"] = "1"
    env.setdefault("CTX_REPO", repo_s)
    # Always propagate isolated home for sims / multi-instance
    if os.environ.get("CTX_HOME"):
        env["CTX_HOME"] = os.environ["CTX_HOME"]

    cmd = [
        sys.executable,
        "-u",
        "-m",
        "pipeline",
        "engine",
        "run",
        repo_s,
        "--host",
        host,
        "--port",
        str(port),
    ]
    log_f = open(log_path(), "a", encoding="utf-8")  # noqa: SIM115
    log_f.write(f"\n--- start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    log_f.flush()

    kwargs: dict[str, Any] = {
        "env": env,
        "stdout": log_f,
        "stderr": log_f,
        "stdin": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **kwargs)  # noqa: S603
    # Child owns the log fd; parent can close its copy after spawn
    try:
        log_f.close()
    except Exception:  # noqa: BLE001
        pass

    meta = {
        "pid": proc.pid,
        "url": f"http://{host}:{port}",
        "repo": repo_s,
        "started_at": time.time(),
        "log": str(log_path()),
        "ctx_home": env.get("CTX_HOME") or str(_home()),
    }
    lock = acquire_lock(proc.pid, url=meta["url"], repo=repo_s)
    if not lock.get("ok") and lock.get("already_running"):
        return lock

    meta_path().write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    pid_path().write_text(str(proc.pid), encoding="utf-8")

    deadline = time.time() + wait_s
    client = EngineClient(f"http://{host}:{port}")
    while time.time() < deadline:
        if client.healthy():
            return {"ok": True, "started": True, **meta}
        time.sleep(0.4)
    return {
        "ok": False,
        "error": "daemon started but health check timed out",
        **meta,
        "hint": f"Check {log_path()} or run: ctx engine run .  (foreground)",
    }


def stop_daemon() -> dict[str, Any]:
    client = EngineClient()
    try:
        client.post("/v1/shutdown", {})
    except Exception:  # noqa: BLE001
        pass
    # Kill by pid file and/or lock pid
    pids: set[int] = set()
    pid_file = pid_path()
    if pid_file.is_file():
        try:
            pids.add(int(pid_file.read_text(encoding="utf-8").strip()))
        except Exception:  # noqa: BLE001
            pass
    lock_pid = _read_lock_pid()
    if lock_pid:
        pids.add(lock_pid)
    for pid in pids:
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
    release_lock()
    time.sleep(0.5)
    return {"ok": True, "running": is_running()}


def force_restart_daemon(repo: Path | str | None = None) -> dict[str, Any]:
    """Kill hung/dead engine (even if lock pid is alive) and start fresh.

    Used by the watchdog sidecar — not by casual ensure_daemon.
    """
    meta: dict[str, Any] = {}
    if meta_path().is_file():
        try:
            meta = json.loads(meta_path().read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            meta = {}

    host, port = default_host_port()
    if meta.get("url"):
        try:
            from urllib.parse import urlparse

            u = urlparse(str(meta["url"]))
            if u.hostname:
                host = u.hostname
            if u.port:
                port = int(u.port)
        except Exception:  # noqa: BLE001
            pass

    repo_s = (
        str(Path(repo).resolve())
        if repo
        else str(meta.get("repo") or Path.cwd().resolve())
    )

    # Best-effort kill whatever holds the lock / pid
    stop_daemon()
    # Extra: clear refuse path for hung lock
    existing = _read_lock_pid()
    if existing is not None and _pid_alive(existing):
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(existing), "/F"],
                    capture_output=True,
                    check=False,
                )
            else:
                os.kill(existing, 9)
        except Exception:  # noqa: BLE001
            pass
    release_lock()
    time.sleep(2.0)

    result = start_daemon(repo_s, host=host, port=port, wait_s=120.0)
    result["forced"] = True
    return result


def ensure_daemon(
    repo: Path | str | None = None,
    *,
    force_if_hung: bool = True,
) -> dict[str, Any]:
    if is_running():
        return {"ok": True, "already_running": True, "url": engine_url()}
    # If hung (lock alive, health down), optionally force restart.
    # MCP request paths should pass force_if_hung=False — force_restart can
    # block for minutes and looked like agent "hangs" in A/B runs.
    existing = _read_lock_pid()
    if existing is not None and _pid_alive(existing) and not is_running():
        if force_if_hung:
            return force_restart_daemon(repo)
        return {
            "ok": False,
            "hung": True,
            "pid": existing,
            "url": engine_url(),
            "hint": "daemon lock alive but /health down; restart outside MCP",
        }
    return start_daemon(repo)
