from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request

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
    assert payload == {"ok": True, "project_id": "ce_repo", "pinned": True}
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
