"""Dedicated loopback-only HTTP server for the CE operator dashboard."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import unquote, urlparse

from pipeline.dashboard_port import (
    PRIVATE_PORT_MAX,
    PRIVATE_PORT_MIN,
    DashboardLock,
    allocate_dashboard_port,
)

DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_BASE = "/ce-dashboard"
API_BASE = f"{DASHBOARD_BASE}/api"
DASHBOARD_IDENTITY = "context-engine-operator-dashboard-v1"
_LOGGER = logging.getLogger(__name__)
_UI_ROOT = Path(__file__).with_name("dashboard_ui")
_STATIC_ASSETS = {
    f"{DASHBOARD_BASE}/": ("index.html", "text/html; charset=utf-8"),
    f"{DASHBOARD_BASE}/index.html": ("index.html", "text/html; charset=utf-8"),
    f"{DASHBOARD_BASE}/styles.css": ("styles.css", "text/css; charset=utf-8"),
    f"{DASHBOARD_BASE}/storage_render.js": (
        "storage_render.js",
        "application/javascript; charset=utf-8",
    ),
    f"{DASHBOARD_BASE}/app.js": ("app.js", "application/javascript; charset=utf-8"),
}
_START_LOCK_NAME = "dashboard.starting"


class PublicAPIError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message

    def payload(self) -> dict[str, Any]:
        return {"ok": False, "code": self.code, "error": self.message}


def _is_loopback(host: str) -> bool:
    return host in {"127.0.0.1", "::1", "localhost"}


def _repo_path(project_id: str, repositories: list[dict[str, Any]]) -> Path:
    for repo in repositories:
        if str(repo.get("project_id")) != project_id:
            continue
        value = repo.get("primary_path") or repo.get("path")
        if not value:
            paths = repo.get("paths")
            value = paths[0] if isinstance(paths, list) and paths else None
        if value:
            return Path(str(value))
    raise FileNotFoundError(f"unknown project_id: {project_id}")


class DashboardAPI:
    """Small dispatch layer shared by HTTP integration and focused unit tests."""

    def dispatch(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
        *,
        client_host: str,
    ) -> tuple[int, dict[str, Any]]:
        method = method.upper()
        data = data or {}
        if method != "GET" and not _is_loopback(client_host):
            return 403, {"ok": False, "error": "loopback client required"}
        if not path.startswith(f"{API_BASE}/") and path != API_BASE:
            return 404, {"ok": False, "error": "not found"}

        suffix = path[len(API_BASE) :].strip("/")
        try:
            if method == "GET":
                return self._get(suffix)
            if method == "POST":
                return self._post(suffix, data)
            return 405, {"ok": False, "error": "method not allowed"}
        except PublicAPIError as exc:
            return exc.status, exc.payload()
        except FileNotFoundError:
            _LOGGER.warning("dashboard API resource lookup failed", exc_info=True)
            return 404, {
                "ok": False,
                "code": "not_found",
                "error": "resource not found",
            }
        except PermissionError:
            _LOGGER.warning("dashboard API operation forbidden", exc_info=True)
            return 403, {
                "ok": False,
                "code": "forbidden",
                "error": "operation not permitted",
            }
        except (TypeError, ValueError):
            _LOGGER.warning("dashboard API request validation failed", exc_info=True)
            return 400, {
                "ok": False,
                "code": "invalid_request",
                "error": "invalid request",
            }
        except OSError:
            _LOGGER.exception("dashboard API operation conflict")
            return 409, {
                "ok": False,
                "code": "operation_conflict",
                "error": "operation could not be completed",
            }
        except Exception:  # noqa: BLE001
            _LOGGER.exception("dashboard API internal failure")
            return 500, {
                "ok": False,
                "code": "internal_error",
                "error": "internal server error",
            }

    def _get(self, suffix: str) -> tuple[int, dict[str, Any]]:
        from pipeline.repo_lifecycle import list_managed_repos

        if suffix == "overview":
            repositories = list_managed_repos()
            states: dict[str, int] = {}
            for repo in repositories:
                state = str(repo.get("presence") or repo.get("state") or "active")
                states[state] = states.get(state, 0) + 1
            return 200, {
                "ok": True,
                "repositories": {
                    "managed": len(repositories),
                    "states": states,
                },
                "dashboard": dashboard_status(include_health=False),
            }
        if suffix == "repos":
            return 200, {"ok": True, "repositories": list_managed_repos()}
        if suffix == "health":
            from pipeline.doctor import doctor_report

            return 200, {
                "ok": True,
                "dashboard_identity": DASHBOARD_IDENTITY,
                "dashboard_pid": os.getpid(),
                "doctor": doctor_report(),
            }
        if suffix == "storage":
            from pipeline.storage_policy import collect_unused_repos, repo_storage_status

            repositories = list_managed_repos()
            statuses = [
                repo_storage_status(str(repo["project_id"]))
                for repo in repositories
                if repo.get("project_id")
            ]
            return 200, {
                "ok": True,
                "repositories": statuses,
                "eviction": collect_unused_repos(dry_run=True),
            }
        if suffix == "runtime":
            from pipeline.doctor import doctor_report

            runtime: dict[str, Any] = doctor_report()
            try:
                from pipeline.resources import get_resource_manager

                runtime["resources"] = get_resource_manager().status()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("dashboard runtime resource lookup failed")
                runtime["resources"] = {
                    "ok": False,
                    "code": "runtime_unavailable",
                    "error": "runtime resources unavailable",
                }
            return 200, {"ok": True, "runtime": runtime}
        if suffix == "settings":
            from pipeline.settings import load_prefs, prefs_path

            settings = load_prefs()
            settings["prefs_path"] = str(prefs_path())
            return 200, {"ok": True, "settings": settings}
        return 404, {"ok": False, "error": "not found"}

    def _post(
        self, suffix: str, data: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        from pipeline import repo_lifecycle as lifecycle

        if suffix == "settings":
            from pipeline.settings import load_prefs, save_prefs, set_registration_mode

            mode = data.get("admission_mode", data.get("registration_mode"))
            if mode is not None:
                if mode not in {"automatic", "mcp_cli"}:
                    raise PublicAPIError(
                        400,
                        "invalid_admission_mode",
                        "admission mode must be automatic or mcp_cli",
                    )
                set_registration_mode(str(mode))
            prefs = load_prefs()
            if "missing_retention_seconds" in data:
                retention = float(data["missing_retention_seconds"])
                if retention < 0:
                    raise PublicAPIError(
                        400,
                        "invalid_retention",
                        "missing retention must be non-negative",
                    )
                prefs["missing_retention_seconds"] = retention
            if "auto_max_repositories" in data:
                maximum = int(data["auto_max_repositories"])
                if maximum < 1:
                    raise PublicAPIError(
                        400,
                        "invalid_auto_limit",
                        "automatic repository limit must be positive",
                    )
                admission = dict(prefs.get("auto_admission") or {})
                admission["max_repositories"] = maximum
                prefs["auto_admission"] = admission
            save_prefs(prefs)
            return 200, {"ok": True, "settings": load_prefs()}

        if suffix == "shutdown":
            return 200, {"ok": True, "stopping": True, "pid": os.getpid()}

        if suffix == "repos/initialize":
            value = data.get("path")
            if not value:
                raise PublicAPIError(400, "path_required", "path is required")
            result = lifecycle.initialize_repo(
                Path(str(value)),
                index=data.get("index", True) is not False,
                always_allow=data.get("always_allow", True) is not False,
            )
            return 200 if result.get("ok") else 409, result

        parts = [unquote(part) for part in suffix.split("/") if part]
        if len(parts) != 3 or parts[0] != "repos":
            return 404, {"ok": False, "error": "not found"}
        project_id, action = parts[1], parts[2]
        if action == "forget":
            confirm = str(data.get("confirm") or "").strip()
            if not confirm:
                raise PublicAPIError(
                    400,
                    "confirmation_required",
                    "confirmation is required to forget a repository",
                )
            result = lifecycle.forget_repo(project_id, confirm=confirm)
        elif action == "locate":
            value = data.get("path")
            if not value:
                raise PublicAPIError(400, "path_required", "path is required")
            result = lifecycle.locate_repo(project_id, Path(str(value)))
        elif action == "clear-index":
            result = lifecycle.clear_index_repo(project_id)
        elif action in {"pin", "unpin"}:
            from pipeline.project_id import load_registry, save_registry

            registry = load_registry()
            projects = registry.get("projects")
            entry = projects.get(project_id) if isinstance(projects, dict) else None
            if not isinstance(entry, dict):
                raise FileNotFoundError(f"unknown project_id: {project_id}")
            pinned = bool(data.get("pinned", True)) if action == "pin" else False
            entry["pinned"] = pinned
            save_registry(registry)
            result = {"ok": True, "project_id": project_id, "pinned": pinned}
        else:
            repositories = lifecycle.list_managed_repos()
            root = _repo_path(project_id, repositories)
            handlers = {
                "unmanage": lambda: lifecycle.remove_repo(root, delete_store=False),
                "pause": lambda: lifecycle.pause_repo(root, reason=data.get("reason")),
                "resume": lambda: lifecycle.resume_repo(root),
                "sync": lambda: lifecycle.sync_now_repo(root),
                "rebuild": lambda: lifecycle.rebuild_repo(root),
            }
            handler = handlers.get(action)
            if handler is None:
                return 404, {"ok": False, "error": "unknown lifecycle action"}
            result = handler()
        return 200 if result.get("ok", True) else 409, result


class DashboardHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class DashboardHandler(BaseHTTPRequestHandler):
    api = DashboardAPI()

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.environ.get("CTX_DASHBOARD_LOG"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _write_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _write_static(self, path: str) -> bool:
        asset = _STATIC_ASSETS.get(path)
        if asset is None:
            return False
        filename, content_type = asset
        try:
            body = (_UI_ROOT / filename).read_bytes()
        except OSError:
            _LOGGER.exception("dashboard UI asset unavailable: %s", filename)
            self._write_json(
                500,
                {
                    "ok": False,
                    "code": "ui_asset_unavailable",
                    "error": "dashboard UI asset unavailable",
                },
            )
            return True
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)
        return True

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length > 1_048_576:
            raise ValueError("request body too large")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            value = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid JSON body") from exc
        if not isinstance(value, dict):
            raise ValueError("JSON object required")
        return value

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            self.send_response(302)
            self.send_header("Location", f"{DASHBOARD_BASE}/")
            self.end_headers()
            return
        if path == DASHBOARD_BASE:
            self.send_response(302)
            self.send_header("Location", f"{DASHBOARD_BASE}/")
            self.end_headers()
            return
        if self._write_static(path):
            return
        status, payload = self.api.dispatch(
            "GET", path, client_host=str(self.client_address[0])
        )
        self._write_json(status, payload)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            data = self._read_json()
        except ValueError:
            _LOGGER.warning("dashboard JSON request rejected", exc_info=True)
            self._write_json(
                400,
                {
                    "ok": False,
                    "code": "invalid_json",
                    "error": "invalid JSON request",
                },
            )
            return
        status, payload = self.api.dispatch(
            "POST", path, data, client_host=str(self.client_address[0])
        )
        self._write_json(status, payload)
        if status == 200 and path == f"{API_BASE}/shutdown":
            threading.Thread(target=self.server.shutdown, daemon=True).start()


def create_dashboard_server(*, port: int) -> DashboardHTTPServer:
    """Create an unstarted server bound exclusively to IPv4 loopback."""
    return DashboardHTTPServer((DASHBOARD_HOST, int(port)), DashboardHandler)


def _seed() -> str:
    return os.environ.get("CTX_DASHBOARD_SEED") or f"{Path.home()}:{sys.executable}"


def _fetch_health(url: str, *, timeout: float = 0.5) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(
            f"{url.rstrip('/')}/api/health", timeout=timeout
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) and payload.get("ok") else None


def _expected_dashboard_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "http"
        and parsed.hostname == DASHBOARD_HOST
        and parsed.username is None
        and parsed.password is None
        and port is not None
        and PRIVATE_PORT_MIN <= port <= PRIVATE_PORT_MAX
        and parsed.netloc == f"{DASHBOARD_HOST}:{port}"
        and parsed.path == DASHBOARD_BASE
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
    )


def _health_matches_process(health: dict[str, Any] | None, pid: int) -> bool:
    return bool(
        health
        and health.get("dashboard_identity") == DASHBOARD_IDENTITY
        and int(health.get("dashboard_pid") or -1) == pid
    )


def _validated_dashboard_state(
    state: dict[str, Any],
) -> tuple[int, str, dict[str, Any]] | None:
    try:
        pid = int(state["pid"])
        url = str(state["url"])
    except (KeyError, TypeError, ValueError):
        return None
    if not _expected_dashboard_url(url):
        return None
    health = _fetch_health(url)
    if not _health_matches_process(health, pid) or not _pid_alive(pid):
        return None
    return pid, url, health


def _clear_stale_state(lock: DashboardLock, state: dict[str, Any]) -> None:
    lock.release_if_owner(state.get("pid"))  # type: ignore[arg-type]


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(
            process_query_limited_information, False, wintypes.DWORD(pid)
        )
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def dashboard_status(*, include_health: bool = True) -> dict[str, Any]:
    lock = DashboardLock()
    state = lock.read()
    if not state:
        return {"ok": True, "running": False}
    validated = _validated_dashboard_state(state)
    if validated is None:
        _clear_stale_state(lock, state)
        return {"ok": True, "running": False, "stale": True}
    _pid, _url, health = validated
    result = {**state, "ok": True, "running": True}
    if include_health:
        result["health"] = health
    return result


@contextmanager
def _launch_guard(timeout: float = 15.0) -> Iterator[None]:
    path = DashboardLock().path.with_name(_START_LOCK_NAME)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, f"{os.getpid()} {time.time()}".encode("ascii"))
            os.close(descriptor)
            break
        except FileExistsError:
            try:
                stale = time.time() - path.stat().st_mtime > timeout
            except OSError:
                stale = False
            if stale:
                path.unlink(missing_ok=True)
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError("timed out waiting for dashboard startup lock")
            time.sleep(0.05)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def start_dashboard(*, open_browser: bool = True) -> dict[str, Any]:
    """Start or reuse the detached dashboard process."""
    with _launch_guard():
        current = dashboard_status()
        if current.get("running"):
            result = {**current, "reused": True}
        else:
            port = allocate_dashboard_port(_seed())
            url = f"http://{DASHBOARD_HOST}:{port}{DASHBOARD_BASE}"
            command = [
                sys.executable,
                "-m",
                "pipeline.dashboard_server",
                "--serve",
                "--port",
                str(port),
            ]
            kwargs: dict[str, Any] = {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "close_fds": True,
            }
            if os.name == "nt":
                kwargs["creationflags"] = (
                    subprocess.CREATE_NEW_PROCESS_GROUP
                    | subprocess.DETACHED_PROCESS
                )
            else:
                kwargs["start_new_session"] = True
            process = subprocess.Popen(command, **kwargs)
            deadline = time.monotonic() + 10.0
            health = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                health = _fetch_health(url)
                if _health_matches_process(health, process.pid):
                    break
                time.sleep(0.05)
            if not _health_matches_process(health, process.pid):
                if process.poll() is None:
                    process.terminate()
                raise RuntimeError("dashboard server failed to become healthy")
            state = DashboardLock().acquire(url, process.pid)
            result = {
                **state,
                "ok": True,
                "running": True,
                "reused": False,
                "health": health,
            }
    if open_browser:
        webbrowser.open(str(result["url"]))
    return result


def stop_dashboard() -> dict[str, Any]:
    """Ask the owned dashboard process to stop and clear its state."""
    state = DashboardLock().read()
    if not state:
        return {"ok": True, "running": False, "stopped": False}
    validated = _validated_dashboard_state(state)
    if validated is None:
        _clear_stale_state(DashboardLock(), state)
        return {
            "ok": True,
            "running": False,
            "stopped": False,
            "stale": True,
        }
    pid, url, _health = validated
    request = urllib.request.Request(
        f"{url.rstrip('/')}/api/shutdown",
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=2):
            pass
    except OSError:
        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
    deadline = time.monotonic() + 5.0
    while _pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    DashboardLock().release_if_owner(pid)
    return {
        "ok": not _pid_alive(pid),
        "running": _pid_alive(pid),
        "stopped": not _pid_alive(pid),
        "pid": pid,
    }


def _serve(port: int) -> int:
    server = create_dashboard_server(port=port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int)
    args = parser.parse_args(argv)
    if not args.serve or args.port is None:
        parser.error("--serve and --port are required")
    return _serve(args.port)


if __name__ == "__main__":
    raise SystemExit(main())
