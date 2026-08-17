"""Auto request admission, session attribution, and status observability."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


def _repo(tmp_path: Path, name: str) -> Path:
    repo = tmp_path / name
    repo.mkdir()
    (repo / "main.py").write_text("value = 1\n", encoding="utf-8")
    return repo


def _managed_repo(tmp_path: Path, name: str) -> Path:
    from pipeline.repo_lifecycle import initialize_repo

    repo = _repo(tmp_path, name)
    result = initialize_repo(repo, index=False)
    assert result["ok"] is True
    return repo


def _stub_warming(manager, monkeypatch: pytest.MonkeyPatch) -> None:
    def warm(root: Path) -> dict:
        manager.repo = Path(root).resolve()
        manager.warm_state = "ready"
        manager.warming = False
        manager._save_active_runtime()
        return {
            "ok": True,
            "repo": str(manager.repo),
            "project_id": manager.project_id,
            "warm_state": "ready",
        }

    monkeypatch.setattr(manager, "_warm_registered", warm)


@pytest.fixture
def ce_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    monkeypatch.setenv("CTX_REGISTRATION_MODE", "automatic")
    monkeypatch.setenv("CTX_AUTO_INDEX", "0")
    return home


def test_auto_limit_refuses_excess_discovered_repositories(
    ce_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline.ce_service import RuntimeManager

    monkeypatch.setenv("CTX_AUTO_MAX_REPOS", "3")
    monkeypatch.setenv("CTX_AUTO_LARGE_REPO_FILES", "100")
    repos = [_managed_repo(tmp_path, f"repo-{number}") for number in range(20)]
    manager = RuntimeManager()
    _stub_warming(manager, monkeypatch)

    outcomes = [
        manager.admit_request(repo, client="cursor", session_id=f"s-{number}")
        for number, repo in enumerate(repos)
    ]

    assert [item["status"] for item in outcomes[:3]] == ["activated"] * 3
    assert {item["status"] for item in outcomes[3:]} == {"paused"}
    assert {item["pause_reason"] for item in outcomes[3:]} == {"auto_limit"}
    assert len(manager.hub.list_status()) == 3
    assert manager.status(repos[3])["pause_reason"] == "auto_limit"


def test_large_repository_auto_admission_is_refused(
    ce_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline.ce_service import RuntimeManager

    repo = _managed_repo(tmp_path, "large")
    for number in range(6):
        (repo / f"file_{number}.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setenv("CTX_AUTO_LARGE_REPO_FILES", "5")
    manager = RuntimeManager()

    result = manager.admit_request(repo, client="cursor", session_id="large-session")

    assert result["status"] == "paused"
    assert result["pause_reason"] == "large_repo"
    assert result["file_count"] == 7
    assert manager.hub.list_status() == []


def test_same_repo_clients_share_runtime_and_keep_session_metadata(
    ce_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline.ce_service import RuntimeManager

    repo = _managed_repo(tmp_path, "shared")
    manager = RuntimeManager()
    _stub_warming(manager, monkeypatch)

    cursor = manager.admit_request(repo, client="cursor", session_id="cursor-session")
    claude = manager.admit_request(
        repo / ".", client="claude-code", session_id="claude-session"
    )

    assert cursor["project_id"] == claude["project_id"]
    assert len(manager.hub.list_status()) == 1
    sessions = manager.hub.list_status()[0]["session_metadata"]
    assert sessions["cursor-session"]["client"] == "cursor"
    assert sessions["claude-session"]["client"] == "claude-code"
    assert cursor["session_authored"] is True
    assert claude["session_authored"] is True


def test_session_end_keeps_shared_runtime_while_another_session_remains(
    ce_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline.ce_service import RuntimeManager

    repo = _managed_repo(tmp_path, "sessions")
    manager = RuntimeManager()
    _stub_warming(manager, monkeypatch)
    first = manager.admit_request(repo, client="cursor", session_id="one")
    manager.admit_request(repo, client="cursor", session_id="two")

    ended = manager.end_session(repo, "one")

    assert ended["remaining_sessions"] == 1
    runtime = manager.hub.get(first["project_id"])
    assert runtime is not None
    assert runtime.priority == "active"
    assert runtime.sessions == {"two"}


def test_never_index_authorization_wins_before_runtime_creation(
    ce_home: Path, tmp_path: Path
) -> None:
    from pipeline.ce_service import RuntimeManager
    from pipeline.repo_lifecycle import never_index_repo

    repo = _repo(tmp_path, "forbidden")
    never_index_repo(repo, reason="private")
    manager = RuntimeManager()

    result = manager.admit_request(repo, client="cursor", session_id="blocked")

    assert result["status"] == "never_index"
    assert manager.hub.list_status() == []


def test_unmanaged_request_requires_initialize_without_minting_state(
    ce_home: Path, tmp_path: Path
) -> None:
    from pipeline.ce_service import RuntimeManager
    from pipeline.project_id import id_file_path, load_registry

    repo = _repo(tmp_path, "unmanaged")

    result = RuntimeManager().admit_request(repo, client="cursor", session_id="new")

    assert result["status"] == "requires_initialize"
    assert load_registry()["projects"] == {}
    assert not id_file_path(repo).exists()


def test_server_start_does_not_activate_repo_before_path_bearing_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline import server

    repo = _repo(tmp_path, "ide-open")
    opened: list[Path] = []

    class Runtime:
        def open_repo(self, root, *, background):
            opened.append(Path(root))

        @staticmethod
        def shutdown() -> None:
            return None

    class Httpd:
        def __init__(self, address, handler):
            self.address = address
            self.handler = handler

        @staticmethod
        def serve_forever() -> None:
            return None

    monkeypatch.setattr(server, "get_context_engine", lambda: Runtime())
    monkeypatch.setattr(server, "ThreadingHTTPServer", Httpd)
    monkeypatch.setattr("pipeline.daemon.acquire_lock", lambda *args, **kwargs: None)
    monkeypatch.setattr("pipeline.daemon.release_lock", lambda: None)

    server.run_server(repo)

    assert opened == []


def test_status_exposes_complete_repo_observability_contract(
    ce_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline.ce_service import RuntimeManager

    repo = _managed_repo(tmp_path, "observed")
    manager = RuntimeManager()
    _stub_warming(manager, monkeypatch)
    admitted = manager.admit_request(repo, client="cursor", session_id="status-session")
    runtime = manager.hub.get(admitted["project_id"])
    assert runtime is not None

    class Keeper:
        running = True
        last_result = {"finished_at": 123.0}

        @staticmethod
        def status() -> dict:
            return {
                "running": True,
                "dirty": {
                    "paths": {
                        "main.py": {"state": "dirty", "reason": "editor_save"},
                        "new.py": {"state": "overlay_ready", "reason": "write"},
                    }
                },
                "publish_pending": True,
                "sync_status": "dirty",
                "last_probe": {"at": 120.0},
                "last_sync": {"finished_at": 123.0},
            }

    runtime.keeper = Keeper()
    manager._load_runtime_facade(runtime)

    status = manager.status(repo)

    expected = {
        "lifecycle",
        "sessions",
        "dirty",
        "pending",
        "scheduler_queue",
        "current_files",
        "pause_reason",
        "timestamps",
        "storage_bytes",
    }
    assert expected <= status.keys()
    assert status["lifecycle"] == "active"
    assert status["sessions"][0]["session_id"] == "status-session"
    assert status["current_files"] == ["main.py", "new.py"]
    assert status["pending"]["publish"] is True
    assert status["pending"]["dirty_count"] == 2
    assert isinstance(status["scheduler_queue"]["queue_depth"], int)
    assert isinstance(status["storage_bytes"]["bytes_used"], int)


def test_client_injects_workspace_and_optional_session_telemetry(
    tmp_path: Path,
) -> None:
    from pipeline.client import EngineClient

    repo = _repo(tmp_path, "client")
    client = EngineClient(
        "http://example.invalid",
        workspace_path=str(repo),
        client="cursor",
        session_id="client-session",
    )

    captured: dict = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        @staticmethod
        def read() -> bytes:
            return b'{"ok": true}'

    def open_request(request, timeout):
        captured.update(json.loads(request.data.decode("utf-8")))
        return Response()

    with patch("urllib.request.urlopen", side_effect=open_request):
        assert client.search("where")["ok"] is True

    assert captured["path"] == str(repo.resolve())
    assert captured["client"] == "cursor"
    assert captured["session_id"] == "client-session"

    with pytest.raises(ValueError, match="workspace path"):
        EngineClient("http://example.invalid").search("missing")
