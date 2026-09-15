"""Daemon lifecycle: start/stop/pid/lock for the Context Engine HTTP service."""

from __future__ import annotations

import json
import os
import signal
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


def start_request_path() -> Path:
    return _home() / "engine.start_request"


# MCP stamps a start request, then the orphan watchdog should pick it up
# within the supervisor cooldown (~20s) plus engine boot. Older leftovers
# from a killed reconnect storm must not keep cold-starting the engine.
START_REQUEST_MAX_AGE_S = 180.0


def note_engine_start_request(*, repo: str | None = None) -> None:
    """Ask the orphan watchdog to cold-start the engine (no console from MCP)."""
    try:
        _home().mkdir(parents=True, exist_ok=True)
        payload = {"repo": repo or "", "at": time.time()}
        start_request_path().write_text(json.dumps(payload) + "\n", encoding="utf-8")
    except OSError:
        pass


def start_request_is_actionable(
    req: dict[str, Any] | None,
    *,
    now: float | None = None,
    clients: int = 0,
) -> bool:
    """True when a consumed start_request should still spawn the engine."""
    if not req:
        return False
    if int(clients or 0) > 0:
        return True
    try:
        stamped = float(req.get("at") or 0.0)
    except (TypeError, ValueError):
        stamped = 0.0
    if stamped <= 0:
        return False
    age = (time.time() if now is None else now) - stamped
    return age <= START_REQUEST_MAX_AGE_S


def consume_engine_start_request() -> dict[str, Any] | None:
    path = start_request_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        data = {}
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    return data if isinstance(data, dict) else {}


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
    """True when the engine process is up.

    Prefer a cheap PID/lock check first. Cold prewarm can make ``/health``
    timeout even while the daemon is alive — treating that as "not running"
    caused MCP warm thrash and false WARM_TIMEOUT in the host sim.
    """
    existing = _read_lock_pid()
    if existing is not None and _pid_alive(existing):
        return True
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
                "hint": "Stop with: scubiee engine stop",
                "lock_pid": existing,
            }
        # stale
        try:
            lock_path().unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass

    payload = {"pid": pid, "url": url, "repo": repo, "acquired_at": time.time()}
    from pipeline.artifact_guard import atomic_write_text

    atomic_write_text(lock_path(), json.dumps(payload, indent=2) + "\n")
    return {"ok": True, **payload}


def validate_daemon_binding(repo: Path | str) -> dict[str, Any]:
    """Compare requested repo against the live daemon lock/health binding."""
    target = Path(repo).resolve()
    healthy = is_running()
    lock_pid = _read_lock_pid()
    lock_repo = None
    try:
        raw = json.loads(lock_path().read_text(encoding="utf-8")) if lock_path().is_file() else {}
        if isinstance(raw, dict) and raw.get("repo"):
            lock_repo = str(Path(str(raw["repo"])).resolve())
    except (OSError, json.JSONDecodeError, ValueError):
        return {
            "ok": False,
            "reason": "lock_corrupt",
            "healthy": healthy,
            "repair": "scubiee engine stop; remove ~/.scubiee/engine.lock if stale",
            "repo": str(target),
        }
    bound = lock_repo
    if healthy:
        try:
            from pipeline.client import EngineClient

            health = EngineClient().get("/health")
            if health.get("repo"):
                bound = str(Path(str(health["repo"])).resolve())
        except Exception:  # noqa: BLE001
            pass
    matched = bound is not None and Path(bound).resolve() == target
    return {
        "ok": bool(healthy and matched),
        "healthy": healthy,
        "matched": matched,
        "bound_repo": bound,
        "repo": str(target),
        "lock_pid": lock_pid,
        "repair": (
            None
            if healthy and matched
            else f"scubiee engine ensure {target}  # reopen so soft search binds this workspace"
        ),
    }


def release_lock() -> None:
    try:
        lock_path().unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass
    try:
        pid_path().unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


def release_lock_if_owner() -> None:
    """Clear lock/pid only when this process still owns ``engine.lock``.

    A previous engine's atexit must not erase the live engine's lock — that made
    the watchdog treat a healthy listener as ``pid_alive=False`` and force-restart.
    """
    owner = _read_lock_pid()
    if owner is not None and int(owner) != int(os.getpid()):
        return
    release_lock()


def _live_engine_identity() -> dict[str, Any] | None:
    """Best-effort identity for a live engine when lock/pid files are missing.

    Prefer lock / pid / meta before ``netstat``. Watchdog heal ticks every ~15s
    and must not spawn a console helper on the steady healthy path (R4 blink).
    """
    host, port = default_host_port()
    pid: int | None = None
    url = f"http://{host}:{port}"
    repo: str | None = None
    try:
        health = EngineClient(url, timeout=2.0).get("/health")
        if not isinstance(health, dict) or not health.get("ok"):
            return None
        if health.get("repo"):
            repo = str(Path(str(health["repo"])).resolve())
    except Exception:  # noqa: BLE001
        health = None

    lock_pid = _read_lock_pid()
    if lock_pid and _pid_alive(int(lock_pid)):
        return {
            "pid": int(lock_pid),
            "url": url,
            "repo": repo or str(Path.cwd().resolve()),
        }
    if pid_path().is_file():
        try:
            file_pid = int(pid_path().read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            file_pid = 0
        if file_pid and _pid_alive(file_pid):
            return {
                "pid": int(file_pid),
                "url": url,
                "repo": repo or str(Path.cwd().resolve()),
            }
    try:
        raw = meta_path().read_text(encoding="utf-8")
        meta = json.loads(raw) if raw else {}
        meta_pid = int(meta.get("pid") or 0)
        if meta_pid and _pid_alive(meta_pid):
            pid = meta_pid
            url = str(meta.get("url") or url)
            repo = repo or (str(meta.get("repo")) if meta.get("repo") else None)
            return {
                "pid": int(pid),
                "url": url,
                "repo": repo or str(Path.cwd().resolve()),
            }
    except Exception:  # noqa: BLE001
        pass

    # Last resort only — console-subsystem ``netstat`` (hidden_run, but still cost).
    try:
        from pipeline.process_control import pids_listening_on_port

        listeners = pids_listening_on_port(int(port))
        if listeners:
            pid = int(listeners[0])
    except Exception:  # noqa: BLE001
        pass
    if pid is None and health is None:
        return None
    if pid is None:
        return None
    return {
        "pid": pid,
        "url": url,
        "repo": repo or str(Path.cwd().resolve()),
    }


def write_engine_identity(pid: int, *, url: str, repo: str) -> dict[str, Any]:
    """Force-write lock / pid / meta to the live listener identity."""
    _home().mkdir(parents=True, exist_ok=True)
    from pipeline.artifact_guard import atomic_write_text

    payload = {
        "pid": int(pid),
        "url": str(url),
        "repo": str(repo),
        "acquired_at": time.time(),
    }
    atomic_write_text(lock_path(), json.dumps(payload, indent=2) + "\n")
    try:
        pid_path().write_text(str(int(pid)), encoding="utf-8")
    except OSError:
        pass
    try:
        meta: dict[str, Any] = {}
        if meta_path().is_file():
            raw = json.loads(meta_path().read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                meta = raw
        meta.update({"pid": int(pid), "url": str(url), "repo": str(repo)})
        atomic_write_text(meta_path(), json.dumps(meta, indent=2) + "\n")
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, **payload}


def bind_engine_identity_to_listener(
    *,
    url: str | None = None,
    repo: str | None = None,
) -> dict[str, Any]:
    """Prefer the TCP listener PID over the Windows wrapper Popen pid."""
    if not is_running():
        return {"ok": False, "bound": False, "reason": "not_healthy"}
    identity = _live_engine_identity()
    if not identity or not identity.get("pid"):
        return {"ok": False, "bound": False, "reason": "no_listener"}
    listener = int(identity["pid"])
    use_url = str(url or identity.get("url") or engine_url())
    use_repo = str(repo or identity.get("repo") or Path.cwd().resolve())
    existing = _read_lock_pid()
    if existing == listener and pid_path().is_file():
        try:
            if int(pid_path().read_text(encoding="utf-8").strip()) == listener:
                return {
                    "ok": True,
                    "bound": False,
                    "reason": "already_listener",
                    "pid": listener,
                }
        except (OSError, ValueError):
            pass
    written = write_engine_identity(listener, url=use_url, repo=use_repo)
    return {"ok": True, "bound": True, "pid": listener, **written}


def heal_engine_lock() -> dict[str, Any]:
    """Rewrite ``engine.lock`` / ``engine.pid`` to the live listener when missing or stale.

    Steady healthy path (watchdog ~15s): if lock already names a live PID and
    ``engine.pid`` matches, return immediately — do **not** spawn ``netstat``.
    """
    if not is_running():
        return {"ok": False, "healed": False, "reason": "not_healthy"}
    existing = _read_lock_pid()
    if existing is not None and _pid_alive(int(existing)):
        pid_matches = False
        try:
            if pid_path().is_file():
                pid_matches = int(pid_path().read_text(encoding="utf-8").strip()) == int(
                    existing
                )
        except (OSError, ValueError):
            pid_matches = False
        if pid_matches:
            return {
                "ok": True,
                "healed": False,
                "reason": "lock_present",
                "pid": int(existing),
            }
        try:
            pid_path().write_text(str(int(existing)), encoding="utf-8")
        except OSError:
            pass
        return {
            "ok": True,
            "healed": True,
            "reason": "pid_file_repaired",
            "pid": int(existing),
        }
    bound = bind_engine_identity_to_listener()
    if bound.get("bound"):
        return {
            "ok": True,
            "healed": True,
            "pid": bound.get("pid"),
            "reason": "bound_listener",
            "lock": bound,
        }
    if bound.get("reason") == "already_listener":
        return {
            "ok": True,
            "healed": False,
            "reason": "lock_present",
            "pid": bound.get("pid"),
        }
    identity = _live_engine_identity()
    if not identity or not identity.get("pid"):
        return {"ok": False, "healed": False, "reason": "no_identity"}
    written = write_engine_identity(
        int(identity["pid"]),
        url=str(identity.get("url") or engine_url()),
        repo=str(identity.get("repo") or Path.cwd()),
    )
    return {
        "ok": True,
        "healed": True,
        "pid": int(identity["pid"]),
        "lock": written,
    }


def reconcile_managed_repositories(*, reason: str = "daemon_recovery") -> dict[str, Any]:
    """Reload registry, dedupe git families, and Merkle-reconcile every managed repo."""
    from pipeline.git_family import reconcile_git_families
    from pipeline.repo_lifecycle import list_managed_repos
    from pipeline.sync_loop import BackgroundSyncLoop

    from pipeline.checkout_identity import reconcile_registry_copy_collisions

    copy_collisions = reconcile_registry_copy_collisions()
    family = reconcile_git_families().to_dict()
    managed = list_managed_repos()
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for entry in managed:
        root = Path(str(entry.get("root") or "")).resolve()
        if not root.is_dir():
            errors.append({"repo": str(root), "error": "managed repository is unavailable"})
            continue
        try:
            result = BackgroundSyncLoop(root).reconcile(reason=reason)
            results.append({"repo": str(root), **result})
        except Exception as exc:  # noqa: BLE001
            errors.append({"repo": str(root), "error": str(exc)})
    return {
        "git_family": family,
        "copy_collisions": copy_collisions,
        "managed": len(managed),
        "reconciled": len(results),
        "results": results,
        "errors": errors,
    }


def daemon_python() -> str:
    """Interpreter for the engine daemon — must have FastEmbed when accel requires it.

    ``start_daemon`` used to spawn ``sys.executable``. Calling force-restart from a
    conda shell without FastEmbed produced a healthy HTTP daemon that failed every
    map with ``fastembed is not installed``. Prefer ``CTX_PYTHON`` / the uv-tool
    scubiee env when the current interpreter cannot import fastembed.
    """
    override = (os.environ.get("CTX_DAEMON_PYTHON") or os.environ.get("CTX_PYTHON") or "").strip()
    if override and Path(override).is_file():
        return override

    def _has_fastembed(exe: str) -> bool:
        try:
            from pipeline.process_job import hidden_run

            r = hidden_run(
                [exe, "-c", "import importlib.util; import sys; "
                 "sys.exit(0 if importlib.util.find_spec('fastembed') else 1)"],
                capture_output=True,
                timeout=20,
                check=False,
            )
            return r.returncode == 0
        except Exception:  # noqa: BLE001
            return False

    current = sys.executable
    try:
        import importlib.util

        if importlib.util.find_spec("fastembed") is not None:
            return current
    except Exception:  # noqa: BLE001
        pass

    candidates: list[Path] = []
    appdata = os.environ.get("APPDATA") or ""
    home = Path.home()
    if appdata:
        candidates.append(Path(appdata) / "uv" / "tools" / "scubiee" / "Scripts" / "python.exe")
    candidates.append(home / ".local" / "share" / "uv" / "tools" / "scubiee" / "bin" / "python")
    # Same prefix as a running scubiee.exe shim often points at.
    local_bin = home / ".local" / "bin"
    if os.name == "nt":
        # uv tool shim lives next to Scripts via AppData path above.
        pass
    else:
        candidates.append(Path(sys.prefix) / "bin" / "python")

    for cand in candidates:
        if cand.is_file() and _has_fastembed(str(cand)):
            return str(cand)
    return current


def start_daemon(
    repo: Path | str | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
    wait_s: float = 90.0,
    force: bool = False,
) -> dict[str, Any]:
    """Spawn Context Engine in background if not already healthy.

    ``force=True`` (used by ``force_restart_daemon``) skips the hung-lock refuse
    path so a fresh worker can bind after a kill sweep.
    """
    # Guard: detect conflicting scubiee installations sharing ~/.scubiee
    from pipeline.install_guard import check_install_conflict, write_install_marker

    conflict = check_install_conflict()
    if conflict:
        print(f"[scubiee] WARNING: {conflict['hint']}", file=sys.stderr, flush=True)
        # Do NOT rewrite install_marker to this conflicting prefix — that makes
        # the next uv-tool / Cursor MCP look like the "intruder" and prolongs
        # the fight. Prefer the recorded install's interpreter for the spawn.
        recorded_exe = str(conflict.get("recorded_executable") or "").strip()
        if recorded_exe and Path(recorded_exe).is_file():
            os.environ.setdefault("CTX_DAEMON_PYTHON", recorded_exe)
        # If a healthy daemon is already up, never spawn a second one from
        # conda/source while uv owns the pin.
        if is_running() and not force:
            try:
                from pipeline.lifecycle_runtime import note_engine_transition

                note_engine_transition("start")
            except Exception:  # noqa: BLE001
                pass
            return {
                "ok": True,
                "already_running": True,
                "url": engine_url(),
                "install_conflict": conflict,
            }
    else:
        write_install_marker()

    if is_running() and not force:
        try:
            from pipeline.lifecycle_runtime import note_engine_transition

            note_engine_transition("start")
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "already_running": True, "url": engine_url()}

    # Live engine process without health: wait for the in-flight starter.
    # Never spawn a second python.exe — that flashes consoles and fights the first.
    existing = _read_lock_pid()
    if existing is None:
        try:
            existing = int(pid_path().read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            existing = None
    if existing is not None and _pid_alive(existing) and not is_running() and not force:
        if wait_s > 0:
            inflight_deadline = time.time() + wait_s
            while time.time() < inflight_deadline:
                if is_running():
                    try:
                        from pipeline.lifecycle_runtime import note_engine_transition

                        note_engine_transition("start")
                    except Exception:  # noqa: BLE001
                        pass
                    return {
                        "ok": True,
                        "already_running": True,
                        "waited_inflight": True,
                        "url": engine_url(),
                    }
                time.sleep(0.2)
        return {
            "ok": False,
            "error": f"engine.lock held by pid {existing} but /health is down",
            "hint": "scubiee engine stop  or check engine.log",
            "log": str(log_path()),
        }
    if force and existing is not None and _pid_alive(existing) and not is_running():
        try:
            if os.name == "nt":
                from pipeline.process_job import taskkill_silent

                taskkill_silent(int(existing), tree=True)
            else:
                os.kill(existing, 9)
        except Exception:  # noqa: BLE001
            pass
        release_lock()

    h, p = default_host_port()
    host = host or h
    port = int(port or p)
    repo_s = str(Path(repo).resolve()) if repo else str(Path.cwd().resolve())

    _home().mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["CTX_ENGINE_URL"] = f"http://{host}:{port}"
    env["PYTHONUTF8"] = "1"
    env["CTX_SCUBIEE_ROLE"] = "engine"
    env.setdefault("CTX_REPO", repo_s)
    # Always propagate isolated home for sims / multi-instance
    if os.environ.get("CTX_HOME"):
        env["CTX_HOME"] = os.environ["CTX_HOME"]

    from pipeline.process_job import background_python

    py = background_python()
    cmd = [
        py,
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
    # Default: background open AFTER listen (server.open_on_start). That overlaps
    # MCP initialize/worker spawn so soft_search_ready lands during connect, not
    # ~20s later. Sync open-before-listen is still forbidden (GIL starves /health).
    # Escape: CTX_ENGINE_OPEN_ON_START=0 restores --no-open (attach opens later).
    open_on_start = (os.environ.get("CTX_ENGINE_OPEN_ON_START") or "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    if not open_on_start:
        cmd.append("--no-open")
    env.setdefault("CTX_PYTHON", daemon_python())
    env.setdefault("CTX_EMBED_IDLE_DEMOTE_S", os.environ.get("CTX_EMBED_IDLE_DEMOTE_S") or "10")
    env.setdefault("CTX_DISCONNECT_DEBOUNCE_S", os.environ.get("CTX_DISCONNECT_DEBOUNCE_S") or "10")
    env.setdefault("CTX_ENGINE_IDLE_S", os.environ.get("CTX_ENGINE_IDLE_S") or "120")
    env.setdefault("CTX_ENGINE_TRANSITION_DEBOUNCE_S", os.environ.get("CTX_ENGINE_TRANSITION_DEBOUNCE_S") or "5")
    env.setdefault("CTX_EMBED_PREWARM", os.environ.get("CTX_EMBED_PREWARM") or "1")
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
        from pipeline.process_job import engine_popen_kwargs

        kwargs.update(engine_popen_kwargs())
    elif sys.platform != "darwin":
        kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(cmd, **kwargs)  # noqa: S603
    except PermissionError as exc:
        # WMI/pythonw parents often deny DETACHED+BREAKAWAY — soft retry.
        if os.name == "nt":
            from pipeline.process_job import engine_popen_kwargs

            kwargs.update(engine_popen_kwargs(soft=True))
            log_f.write(f"[daemon] soft spawn retry after PermissionError: {exc}\n")
            log_f.flush()
            proc = subprocess.Popen(cmd, **kwargs)  # noqa: S603
        else:
            raise
    except OSError as exc:
        # WinError 193: "%1 is not a valid Win32 application" — often a broken
        # pythonw redirector / shim. Fall back to python.exe, then soft flags.
        winerr = getattr(exc, "winerror", None)
        if os.name == "nt" and winerr == 193:
            from pipeline.process_job import engine_popen_kwargs

            py_console = daemon_python()
            if Path(cmd[0]).name.lower() != Path(py_console).name.lower():
                cmd = [py_console, *cmd[1:]]
                log_f.write(
                    f"[daemon] WinError 193 on pythonw — retry with {py_console}: {exc}\n"
                )
                log_f.flush()
                try:
                    proc = subprocess.Popen(cmd, **kwargs)  # noqa: S603
                except OSError as exc2:
                    kwargs.update(engine_popen_kwargs(soft=True))
                    kwargs["close_fds"] = False
                    log_f.write(
                        f"[daemon] soft spawn retry after WinError 193: {exc2}\n"
                    )
                    log_f.flush()
                    proc = subprocess.Popen(cmd, **kwargs)  # noqa: S603
            else:
                kwargs.update(engine_popen_kwargs(soft=True))
                kwargs["close_fds"] = False
                log_f.write(f"[daemon] soft spawn retry after WinError 193: {exc}\n")
                log_f.flush()
                proc = subprocess.Popen(cmd, **kwargs)  # noqa: S603
        else:
            raise
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

    # Stamp start immediately so idle sweeper does not kill a listen-first child
    # before /health is up (HTTP bind is ~3s; embedder/index lag much longer).
    try:
        from pipeline.lifecycle_runtime import note_engine_transition

        note_engine_transition("start")
    except Exception:  # noqa: BLE001
        pass
    if wait_s <= 0:
        return {"ok": True, "started": True, "health_pending": True, **meta}

    deadline = time.time() + wait_s
    client = EngineClient(f"http://{host}:{port}")
    while time.time() < deadline:
        if client.healthy():
            identity = bind_engine_identity_to_listener(url=meta["url"], repo=repo_s)
            if identity.get("pid"):
                meta["pid"] = int(identity["pid"])
                meta["identity_bound"] = bool(identity.get("bound"))
            try:
                from pipeline.lifecycle_runtime import note_engine_transition

                note_engine_transition("start")
            except Exception:  # noqa: BLE001
                pass
            # Do not Merkle-reconcile every managed repo on spawn — that raced
            # the agent's open/prewarm and pushed cold warm past 10s.
            return {
                "ok": True,
                "started": True,
                **meta,
                "registry_recovery": {"skipped": "agent_warm"},
            }
        time.sleep(0.4)
    return {
        "ok": False,
        "error": "daemon started but health check timed out",
        **meta,
        "hint": f"Check {log_path()} or run: scubiee engine run .  (foreground)",
    }


def stop_daemon(*, reason: str | None = None) -> dict[str, Any]:
    from pipeline.lifecycle_runtime import (
        TRANSITION_REASON_USER,
        note_engine_transition,
    )

    stop_reason = str(reason or TRANSITION_REASON_USER)
    host, port = default_host_port()
    # Short timeout — shutdown is best-effort; pid/sweep handle hard stop.
    client = EngineClient(timeout=3.0)
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
    from pipeline.process_control import kill_all_engine_daemons, safe_terminate_pid

    killed: list[int] = []
    skipped: list[dict[str, Any]] = []
    for pid in pids:
        result = safe_terminate_pid(pid, grace_s=2.0, allow_child=True)
        if result.get("terminated"):
            killed.append(pid)
        elif result.get("skipped") == "not_context_engine":
            skipped.append(result)
    # Always sweep orphans — prior stop only cleared lock pid and missed
    # ``python -m pipeline engine run`` workers still holding :8765.
    sweep = kill_all_engine_daemons(port=port, wait_s=5.0)
    killed.extend(sweep.get("killed") or [])
    release_lock()
    deadline = time.time() + 5.0
    while time.time() < deadline and is_running():
        time.sleep(0.2)
    still_running = is_running()
    if not still_running:
        try:
            note_engine_transition("stop", reason=stop_reason)
        except Exception:  # noqa: BLE001
            pass
    return {
        "ok": not still_running,
        "running": still_running,
        "killed": sorted(set(killed)),
        "skipped_pids": skipped,
        "sweep": sweep,
        "stop_reason": stop_reason,
    }


def stop_daemon_for_upgrade() -> dict[str, Any]:
    """Force-stop during package upgrade — bypasses normal idle debounce bookkeeping."""
    from pipeline.lifecycle_runtime import TRANSITION_REASON_UPGRADE

    return stop_daemon(reason=TRANSITION_REASON_UPGRADE)


def force_restart_daemon(repo: Path | str | None = None, *, upgrade: bool = False) -> dict[str, Any]:
    """Kill hung/dead engine (even if lock pid is alive) and start fresh.

    Used by the watchdog sidecar — not by casual ensure_daemon.
    When ``upgrade=True``, stop bookkeeping uses the upgrade transition path.
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
    if upgrade:
        stop_daemon_for_upgrade()
    else:
        stop_daemon()
    from pipeline.process_control import kill_all_engine_daemons

    sweep = kill_all_engine_daemons(port=port, wait_s=5.0)
    # Extra: clear refuse path for hung lock
    existing = _read_lock_pid()
    if existing is not None and _pid_alive(existing):
        try:
            if os.name == "nt":
                from pipeline.process_job import taskkill_silent

                taskkill_silent(int(existing), tree=True)
            else:
                os.kill(existing, 9)
        except Exception:  # noqa: BLE001
            pass
    release_lock()
    time.sleep(1.0)

    try:
        result = start_daemon(repo_s, host=host, port=port, wait_s=120.0, force=True)
    except OSError as exc:
        return {
            "ok": False,
            "forced": True,
            "sweep": sweep,
            "error": f"start_daemon_oserror:{exc}",
            "repo": repo_s,
            "url": f"http://{host}:{port}",
        }
    result["forced"] = True
    result["sweep"] = sweep
    return result


def _spawn_owner(explicit: str | None = None) -> str:
    raw = (explicit or os.environ.get("CTX_ENGINE_SPAWN_OWNER") or "direct").strip().lower()
    if raw in {"supervisor", "watchdog", "mcp"}:
        return "supervisor"
    return "direct"


def _ensure_already_running(
    repo: Path | str | None,
    *,
    version_adopt: dict[str, Any] | None = None,
    open_wait: bool = True,
) -> dict[str, Any]:
    try:
        bind_engine_identity_to_listener(
            repo=str(Path(repo).resolve()) if repo is not None else None
        )
    except Exception:  # noqa: BLE001
        pass
    target = Path(repo).resolve() if repo is not None else None
    if target is None:
        out = {"ok": True, "already_running": True, "url": engine_url()}
        if version_adopt is not None:
            out["version_adopt"] = version_adopt
        return out
    client = EngineClient(timeout=8.0 if not open_wait else 120.0)
    opened = client.open_repo(str(target), wait=open_wait)
    health = client.get("/health")
    bound_raw = health.get("repo")
    try:
        bound = Path(str(bound_raw)).resolve() if bound_raw else None
    except OSError:
        bound = None
    matched = bool(opened.get("ok", True) and bound == target)
    out = {
        "ok": matched,
        "already_running": True,
        "url": engine_url(),
        "repo": str(target),
        "bound_repo": str(bound) if bound is not None else bound_raw,
        "opened": opened,
        "error": None if matched else "running daemon did not bind requested repository",
    }
    if version_adopt is not None:
        out["version_adopt"] = version_adopt
        if version_adopt.get("action") == "restarted":
            out["already_running"] = False
            out["action"] = "version_restarted"
    return out


def _ensure_daemon_via_supervisor(repo: Path | str | None = None) -> dict[str, Any]:
    """Ask the detached supervisor to own engine spawn — never Popen from MCP."""
    from pipeline.lifecycle_runtime import (
        DESIRED_RUN,
        ensure_supervisor_detached,
        note_activity,
        set_desired_mode,
    )

    note_activity()
    set_desired_mode(DESIRED_RUN)
    try:
        from pipeline.daemon import note_engine_start_request

        note_engine_start_request(repo=str(Path(repo).resolve()) if repo else None)
    except Exception:  # noqa: BLE001
        pass
    supervisor = ensure_supervisor_detached()
    wait_s = float(os.environ.get("CTX_SUPERVISOR_ENGINE_WAIT_S") or "45")
    deadline = time.time() + max(5.0, wait_s)
    while time.time() < deadline:
        if is_running():
            out = _ensure_already_running(repo)
            out["spawn_owner"] = "supervisor"
            out["supervisor"] = supervisor
            return out
        time.sleep(0.4)
    return {
        "ok": False,
        "error": "supervisor_engine_timeout",
        "spawn_owner": "supervisor",
        "supervisor": supervisor,
        "url": engine_url(),
        "hint": "Run: scubiee engine ensure  (or scubiee setup) so the supervisor can start the engine",
    }


def ensure_daemon(
    repo: Path | str | None = None,
    *,
    force_if_hung: bool = True,
    spawn_owner: str | None = None,
    wait_s: float | None = None,
    open_wait: bool = True,
) -> dict[str, Any]:
    from pipeline.pause_resume import is_paused, is_resuming

    if is_paused() and not is_resuming():
        from pipeline.lifecycle_guard import globally_paused_hint

        return {
            "ok": False,
            "skipped": True,
            "reason": "globally_paused",
            "hint": globally_paused_hint(),
        }
    owner = _spawn_owner(spawn_owner)
    health_wait = 90.0 if wait_s is None else float(wait_s)
    try:
        from pipeline.watchdog import watchdog_enabled

        # Direct owner starts the engine itself — do not wait on a 15s
        # watchdog tick or WMI-spawn a supervisor just to cold-start.
        if watchdog_enabled() and owner != "direct":
            from pipeline.lifecycle_runtime import ensure_supervisor_detached

            ensure_supervisor_detached()
    except Exception:  # noqa: BLE001
        pass
    version_adopt: dict[str, Any] | None = None
    if is_running():
        # Version mismatch check: restart if daemon is running old code
        try:
            from pipeline.upgrade import daemon_version_matches, restart_daemon_if_stale

            if not daemon_version_matches():
                version_adopt = restart_daemon_if_stale()
                if version_adopt.get("ok") and version_adopt.get("action") == "restarted":
                    # Daemon was restarted with new version; re-check
                    time.sleep(1.0)
        except Exception:  # noqa: BLE001
            pass
        out = _ensure_already_running(
            repo, version_adopt=version_adopt, open_wait=open_wait
        )
        out["spawn_owner"] = owner
        return out
    # If hung (lock alive, health down), optionally force restart.
    # MCP request paths should pass force_if_hung=False — force_restart can
    # block for minutes and looked like agent "hangs" in A/B runs.
    existing = _read_lock_pid()
    if existing is not None and _pid_alive(existing) and not is_running():
        if force_if_hung and owner == "direct":
            return force_restart_daemon(repo)
        if wait_s is not None and health_wait > 0:
            poll_deadline = time.time() + health_wait
            while time.time() < poll_deadline:
                if is_running():
                    out = _ensure_already_running(repo, open_wait=open_wait)
                    out["spawn_owner"] = owner
                    out["waited_for_inflight"] = True
                    return out
                time.sleep(0.2)
        return {
            "ok": False,
            "hung": True,
            "pid": existing,
            "url": engine_url(),
            "spawn_owner": owner,
            "hint": "daemon lock alive but /health down; restart outside MCP",
        }
    if owner == "supervisor":
        return _ensure_daemon_via_supervisor(repo)
    from pipeline.lifecycle_runtime import note_activity

    note_activity()
    started = start_daemon(repo, wait_s=health_wait)
    started["spawn_owner"] = "direct"
    # open_on_start is best-effort in the daemon; explicitly bind when ensure
    # was asked to wait so soft_search_ready/chunks are usable after return.
    if (
        open_wait
        and repo is not None
        and started.get("ok")
        and not started.get("skipped")
    ):
        try:
            bound = _ensure_already_running(repo, open_wait=True)
            started["opened"] = bound.get("opened")
            if bound.get("ok") is False:
                started["bind_error"] = bound.get("error")
            else:
                started["ok"] = True
                started["repo"] = bound.get("repo") or started.get("repo")
        except Exception as exc:  # noqa: BLE001
            started["bind_error"] = str(exc)
    return started
