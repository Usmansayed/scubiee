from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest


def _request(url: str, *, method: str = "GET", payload: dict | None = None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


@pytest.fixture
def isolated_ce_home(tmp_path, monkeypatch):
    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("CTX_DASHBOARD_SEED", "dashboard-api-test")
    return home


@pytest.fixture
def dashboard_http(isolated_ce_home):
    from pipeline.dashboard_server import create_dashboard_server

    server = create_dashboard_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_overview_is_served_on_loopback(dashboard_http):
    status, payload = _request(f"{dashboard_http}/ce-dashboard/api/overview")

    assert status == 200
    assert payload["ok"] is True
    assert "repositories" in payload


def test_mutation_rejects_non_loopback_client(isolated_ce_home):
    from pipeline.dashboard_server import DashboardAPI

    status, payload = DashboardAPI().dispatch(
        "POST",
        "/ce-dashboard/api/repos/initialize",
        {"path": "."},
        client_host="192.0.2.10",
    )

    assert status == 403
    assert payload["ok"] is False
    assert payload["error"] == "loopback client required"


def test_mutation_rejects_cross_origin_loopback_request(dashboard_http):
    body = json.dumps({"admission_mode": "mcp_cli"}).encode("utf-8")
    request = urllib.request.Request(
        f"{dashboard_http}/ce-dashboard/api/settings",
        data=body,
        method="POST",
        headers={
            "Content-Type": "text/plain",
            "Origin": "https://attacker.example",
        },
    )

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(request, timeout=5)

    assert exc_info.value.code == 403
    assert json.loads(exc_info.value.read().decode("utf-8")) == {
        "ok": False,
        "code": "cross_origin_forbidden",
        "error": "same-origin request required",
    }


def test_local_mutation_without_origin_remains_supported(isolated_ce_home):
    from pipeline.dashboard_server import DashboardAPI

    status, payload = DashboardAPI().dispatch(
        "POST",
        "/ce-dashboard/api/settings",
        {"admission_mode": "mcp_cli"},
        client_host="127.0.0.1",
    )

    assert status == 200
    assert payload["settings"]["registration_mode"] == "mcp_cli"


def test_mutation_accepts_localhost_origin_for_loopback_server(isolated_ce_home):
    from pipeline.dashboard_server import DashboardAPI

    status, payload = DashboardAPI().dispatch(
        "POST",
        "/ce-dashboard/api/settings",
        {"admission_mode": "mcp_cli"},
        client_host="127.0.0.1",
        origin="http://localhost:61696",
        server_origin="http://127.0.0.1:61696",
    )

    assert status == 200
    assert payload["settings"]["registration_mode"] == "mcp_cli"


def test_health_includes_classified_repairs(isolated_ce_home, monkeypatch):
    from pipeline.dashboard_server import DashboardAPI

    monkeypatch.setattr(
        "pipeline.doctor.doctor_all",
        lambda: {
            "ok": False,
            "repositories": [
                {
                    "ok": False,
                    "repo": "C:/repo",
                    "project_id": "ce_repo",
                    "repairs": ["scubiee engine ensure C:/repo"],
                }
            ],
        },
    )
    monkeypatch.setattr(
        "pipeline.doctor.plan_repairs",
        lambda _root=None, report=None: [
            {
                "id": "bind_daemon",
                "kind": "safe",
                "detail": "scubiee engine ensure C:/repo",
            }
        ],
    )

    status, payload = DashboardAPI().dispatch(
        "GET",
        "/ce-dashboard/api/doctor",
        client_host="127.0.0.1",
    )

    assert status == 200
    assert payload["ok"] is True
    assert payload["dashboard_identity"]
    assert payload["repairs"]
    assert payload["repairs"][0]["kind"] == "safe"


def test_repair_route_applies_safe_actions_only(isolated_ce_home, monkeypatch):
    from pipeline.dashboard_server import DashboardAPI

    called: list[str] = []

    monkeypatch.setattr(
        "pipeline.doctor.apply_safe_repairs",
        lambda root: called.append(str(root))
        or {
            "ok": True,
            "applied": [{"id": "bind_daemon", "kind": "safe"}],
            "manual": [],
            "repo": str(root),
        },
    )
    monkeypatch.setattr(
        "pipeline.doctor.apply_safe_repairs_all",
        lambda: {
            "ok": True,
            "applied": [{"id": "bind_daemon", "kind": "safe", "repo": "C:/repo"}],
            "manual": [{"id": "init_repair", "kind": "manual"}],
        },
    )

    status, payload = DashboardAPI().dispatch(
        "POST",
        "/ce-dashboard/api/repair",
        {},
        client_host="127.0.0.1",
    )

    assert status == 200
    assert payload["ok"] is True
    assert payload["applied"][0]["id"] == "bind_daemon"
    assert payload["manual"][0]["kind"] == "manual"
    assert called == []


def test_settings_toggles_admission_mode(dashboard_http):
    status, changed = _request(
        f"{dashboard_http}/ce-dashboard/api/settings",
        method="POST",
        payload={"admission_mode": "mcp_cli"},
    )
    assert status == 200
    assert changed["settings"]["registration_mode"] == "mcp_cli"

    status, current = _request(f"{dashboard_http}/ce-dashboard/api/settings")
    assert status == 200
    assert current["settings"]["registration_mode"] == "mcp_cli"


def test_forget_route_requires_confirm(dashboard_http):
    status, payload = _request(
        f"{dashboard_http}/ce-dashboard/api/repos/ce_missing/forget",
        method="POST",
        payload={},
    )

    assert status == 400
    assert payload["ok"] is False
    assert "confirm" in payload["error"].lower()


def test_dashboard_lists_root_and_action_fields(isolated_ce_home, tmp_path):
    from pipeline.dashboard_server import DashboardAPI
    from pipeline.project_id import _norm_path
    from pipeline.repo_lifecycle import initialize_repo

    repo = tmp_path / "listed"
    repo.mkdir()
    project_id = initialize_repo(repo, index=False)["project_id"]

    status, payload = DashboardAPI().dispatch(
        "GET",
        "/ce-dashboard/api/repos",
        client_host="127.0.0.1",
    )

    assert status == 200
    listed = payload["repositories"][0]
    assert listed["project_id"] == project_id
    assert _norm_path(listed["root"]) == _norm_path(repo)
    assert listed["primary_path"] == listed["root"]
    assert listed["path"] == listed["root"]
    assert listed["paused"] is False
    assert listed["forget_allowed"] is False
    assert "indexed" in listed


def test_dashboard_pause_and_resume_use_listed_root(isolated_ce_home, tmp_path):
    from pipeline.dashboard_server import DashboardAPI
    from pipeline.repo_lifecycle import initialize_repo, managed_state

    repo = tmp_path / "ops"
    repo.mkdir()
    project_id = initialize_repo(repo, index=False)["project_id"]
    api = DashboardAPI()

    paused_status, paused = api.dispatch(
        "POST",
        f"/ce-dashboard/api/repos/{project_id}/pause",
        {},
        client_host="127.0.0.1",
    )
    assert paused_status == 200
    assert paused["ok"] is True
    assert paused["paused"] is True
    assert managed_state(repo) == "paused"

    resumed_status, resumed = api.dispatch(
        "POST",
        f"/ce-dashboard/api/repos/{project_id}/resume",
        {},
        client_host="127.0.0.1",
    )
    assert resumed_status == 200
    assert resumed["ok"] is True
    assert resumed["paused"] is False
    assert managed_state(repo) == "active"


def test_dashboard_forget_removes_active_repo(isolated_ce_home, tmp_path):
    from pipeline.dashboard_server import DashboardAPI
    from pipeline.project_id import load_registry
    from pipeline.repo_lifecycle import initialize_repo, list_managed_repos

    repo = tmp_path / "keep-source"
    repo.mkdir()
    (repo / "app.py").write_text("print('hi')\n", encoding="utf-8")
    created = initialize_repo(repo, index=False)
    project_id = created["project_id"]
    store = created["store_dir"]

    status, payload = DashboardAPI().dispatch(
        "POST",
        f"/ce-dashboard/api/repos/{project_id}/forget",
        {"confirm": project_id},
        client_host="127.0.0.1",
    )

    assert status == 200
    assert payload["ok"] is True
    assert payload["forgotten"] is True
    assert "message" in payload
    assert project_id not in (load_registry().get("projects") or {})
    assert list_managed_repos() == []
    assert (repo / "app.py").is_file()
    assert not Path(store).exists()


def test_graph_api_returns_nodes_for_indexed_repo(
    dashboard_http, tmp_path, monkeypatch
):
    from pipeline import repo_lifecycle

    root = tmp_path / "indexed-repo"
    graph_dir = root / "graphify-out"
    graph_dir.mkdir(parents=True)
    graph_path = graph_dir / "graph.json"
    graph_document = {
        "directed": True,
        "multigraph": False,
        "graph": {},
        "nodes": [
            {"id": "module:api", "label": "api.py", "type": "file"},
            {"id": "function:serve", "label": "serve", "type": "function"},
        ],
        "links": [
            {
                "source": "module:api",
                "target": "function:serve",
                "type": "defines",
            }
        ],
    }
    original = json.dumps(graph_document, sort_keys=True)
    graph_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        repo_lifecycle,
        "list_managed_repos",
        lambda: [
            {
                "project_id": "ce_indexed",
                "primary_path": str(root),
                "indexed": True,
            }
        ],
    )

    status, payload = _request(
        f"{dashboard_http}/ce-dashboard/api/graph/ce_indexed"
    )

    assert status == 200
    assert payload["project_id"] == "ce_indexed"
    assert payload["nodes"] == graph_document["nodes"]
    assert payload["edges"] == graph_document["links"]
    assert graph_path.read_text(encoding="utf-8") == original


def test_pin_route_updates_registry(isolated_ce_home, monkeypatch):
    from pipeline.dashboard_server import DashboardAPI
    from pipeline import project_id, repo_lifecycle

    registry = {
        "projects": {
            "ce_repo": {
                "paths": ["C:/repo"],
                "managed": True,
                "pinned": False,
            }
        }
    }
    saved: list[dict] = []
    monkeypatch.setattr(project_id, "load_registry", lambda: registry)
    monkeypatch.setattr(project_id, "save_registry", lambda value: saved.append(value))
    monkeypatch.setattr(
        repo_lifecycle,
        "list_managed_repos",
        lambda: [{"project_id": "ce_repo", "primary_path": "C:/repo"}],
    )

    status, payload = DashboardAPI().dispatch(
        "POST",
        "/ce-dashboard/api/repos/ce_repo/pin",
        {"pinned": True},
        client_host="127.0.0.1",
    )

    assert status == 200
    assert payload["ok"] is True
    assert payload["project_id"] == "ce_repo"
    assert payload["pinned"] is True
    assert saved[-1]["projects"]["ce_repo"]["pinned"] is True


def test_api_error_does_not_expose_internal_exception(isolated_ce_home, monkeypatch):
    from pipeline import repo_lifecycle
    from pipeline.dashboard_server import DashboardAPI

    sentinel = "SENTINEL C:/private/operator-store"

    def fail_list():
        raise OSError(sentinel)

    monkeypatch.setattr(repo_lifecycle, "list_managed_repos", fail_list)

    status, payload = DashboardAPI().dispatch(
        "GET",
        "/ce-dashboard/api/repos",
        client_host="127.0.0.1",
    )

    assert status == 409
    assert payload == {
        "ok": False,
        "code": "operation_conflict",
        "error": "operation could not be completed",
    }
    assert sentinel not in json.dumps(payload)


def test_clear_index_route_passes_project_id_by_keyword(isolated_ce_home, monkeypatch):
    from pipeline import repo_lifecycle
    from pipeline.dashboard_server import DashboardAPI

    received: list[str] = []

    def clear_index_repo(*, project_id: str):
        received.append(project_id)
        return {"ok": True, "project_id": project_id}

    monkeypatch.setattr(repo_lifecycle, "clear_index_repo", clear_index_repo)

    status, payload = DashboardAPI().dispatch(
        "POST",
        "/ce-dashboard/api/repos/ce_repo/clear-index",
        client_host="127.0.0.1",
    )

    assert status == 200
    assert payload["ok"] is True
    assert payload["project_id"] == "ce_repo"
    assert received == ["ce_repo"]


def test_dashboard_forget_uses_configured_missing_retention(
    isolated_ce_home, tmp_path
):
    from pipeline.project_id import load_registry, save_registry
    from pipeline.repo_lifecycle import forget_repo, initialize_repo
    from pipeline.settings import save_prefs

    repo = tmp_path / "repo"
    repo.mkdir()
    project_id = initialize_repo(repo, index=False)["project_id"]
    registry = load_registry()
    registry["projects"][project_id]["paths"] = [str(tmp_path / "gone")]
    registry["projects"][project_id]["missing_since"] = 0.0
    save_registry(registry)
    save_prefs({"missing_retention_seconds": 1e20})

    payload = forget_repo(project_id, confirm=project_id, retention_s=1e20)

    assert payload["ok"] is False
    assert payload["error"] == "forget_not_allowed"


def test_stop_stale_state_never_signals_unrelated_live_pid(
    isolated_ce_home, monkeypatch
):
    import pipeline.dashboard_server as dashboard_server
    from pipeline.dashboard_port import DashboardLock

    unrelated_pid = os.getpid()
    DashboardLock().acquire(
        "http://127.0.0.1:54321/ce-dashboard",
        unrelated_pid,
    )
    monkeypatch.setattr(
        dashboard_server,
        "_fetch_health",
        lambda url, timeout=0.5: {
            "ok": True,
            "dashboard_pid": unrelated_pid,
        },
    )
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(
        dashboard_server.os,
        "kill",
        lambda pid, sig: signals.append((pid, sig)),
    )
    alive = iter([True, False, False, False])
    monkeypatch.setattr(
        dashboard_server,
        "_pid_alive",
        lambda pid: next(alive, False),
    )

    result = dashboard_server.stop_dashboard()

    assert result["running"] is False
    assert result["stale"] is True
    assert signals == []
    assert DashboardLock().read() is None


def test_stop_revalidates_ownership_before_fallback_signal(
    isolated_ce_home, monkeypatch
):
    import pipeline.dashboard_server as dashboard_server
    from pipeline.dashboard_port import DashboardLock

    pid = os.getpid()
    state = DashboardLock().acquire(
        "http://127.0.0.1:54321/ce-dashboard",
        pid,
    )
    validated = iter([(pid, state["url"], {}), None])
    monkeypatch.setattr(
        dashboard_server,
        "_validated_dashboard_state",
        lambda _state: next(validated),
    )
    monkeypatch.setattr(
        dashboard_server.urllib.request,
        "urlopen",
        lambda _request, timeout: (_ for _ in ()).throw(OSError("unreachable")),
    )
    alive = iter([True, False, False, False])
    monkeypatch.setattr(
        dashboard_server,
        "_pid_alive",
        lambda _pid: next(alive, False),
    )
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(
        dashboard_server.os,
        "kill",
        lambda target_pid, sig: signals.append((target_pid, sig)),
    )

    result = dashboard_server.stop_dashboard()

    assert result["stopped"] is False
    assert result["stale"] is True
    assert signals == []


def test_dashboard_cli_status_prints_json(monkeypatch, capsys):
    import pipeline.dashboard_server as dashboard_server
    from pipeline.__main__ import main

    monkeypatch.setattr(
        dashboard_server,
        "dashboard_status",
        lambda: {"ok": True, "running": True, "url": "http://127.0.0.1:54321/ce-dashboard"},
    )

    assert main(["dashboard", "--status"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["running"] is True
    assert payload["url"].endswith("/ce-dashboard")


def test_resolve_spawn_dashboard_pid_accepts_windows_wrapper_pid() -> None:
    from pipeline.dashboard_server import _resolve_spawn_dashboard_pid

    health = {
        "ok": True,
        "dashboard_identity": "scubiee-operator-dashboard-v1",
        "dashboard_pid": 4242,
    }
    with patch("pipeline.dashboard_server._pid_alive", return_value=True):
        assert (
            _resolve_spawn_dashboard_pid(health, 1111, spawn_running=True) == 4242
            if __import__("os").name == "nt"
            else _resolve_spawn_dashboard_pid(health, 4242, spawn_running=True) == 4242
        )


def test_background_server_reuses_pid_and_stops(isolated_ce_home):
    from pipeline.dashboard_server import dashboard_status, start_dashboard, stop_dashboard

    first = None
    try:
        first = start_dashboard(open_browser=False)
        assert first["ok"] is True
        assert first["running"] is True
        assert first["url"].startswith("http://127.0.0.1:")
        status, overview = _request(f"{first['url']}/api/overview")
        assert status == 200
        assert overview["ok"] is True

        second = start_dashboard(open_browser=False)
        assert second["pid"] == first["pid"]
        assert second["reused"] is True
        assert dashboard_status()["running"] is True
    finally:
        stopped = stop_dashboard()

    assert stopped["ok"] is True
    assert dashboard_status()["running"] is False
