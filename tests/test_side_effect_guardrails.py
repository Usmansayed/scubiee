"""Regression: read-only / diagnostic paths must not auto-enroll repos."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.graphify_mcp_tools import resolve_graph_json
from pipeline.project_id import peek_project
from pipeline.repo_runtime import RepoHub
from pipeline.store import PipelineStore


def test_peek_project_never_writes_id_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()

    assert peek_project(repo) is None
    assert not (repo / ".scubiee").exists()


def test_pipeline_store_resolve_never_writes_id_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()

    store = PipelineStore(repo, resolve=True)
    assert store.project_id is None
    assert not (repo / ".scubiee").exists()


def test_repo_hub_ensure_refuses_unenrolled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()

    hub = RepoHub()
    with pytest.raises(RuntimeError, match="not enrolled"):
        hub.ensure(repo)


def test_graphify_resolve_does_not_create_scubiee(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    graph = repo / "graphify-out"
    graph.mkdir()
    (graph / "graph.json").write_text("{}", encoding="utf-8")

    path = resolve_graph_json(repo)
    assert path.is_file()
    assert not (repo / ".scubiee").exists()


def test_ce_service_health_does_not_bind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pipeline.ce_service import RuntimeManager

    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()

    svc = RuntimeManager()
    svc.repo = repo
    svc.health()
    assert not (repo / ".scubiee").exists()
