"""Store write lock prevents concurrent index corruption."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest


@pytest.fixture
def ce_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    return home


def test_store_write_lock_serializes_threads(tmp_path: Path) -> None:
    from pipeline.store_lock import store_write_lock

    store = tmp_path / "store"
    store.mkdir()
    order: list[str] = []
    barrier = threading.Barrier(2)

    def worker(name: str) -> None:
        barrier.wait()
        with store_write_lock(store, timeout=5.0):
            order.append(f"{name}-in")
            time.sleep(0.05)
            order.append(f"{name}-out")

    t1 = threading.Thread(target=worker, args=("a",))
    t2 = threading.Thread(target=worker, args=("b",))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)
    assert not t1.is_alive() and not t2.is_alive()
    assert order in (
        ["a-in", "a-out", "b-in", "b-out"],
        ["b-in", "b-out", "a-in", "a-out"],
    )


def test_save_chunks_uses_store_lock(ce_home: Path, tmp_path: Path) -> None:
    from pipeline.store import ChunkRecord, PipelineStore
    from pipeline.store_lock import store_lock_file

    repo = tmp_path / "repo"
    repo.mkdir()
    from pipeline.project_id import resolve_project

    ref = resolve_project(repo)
    store = PipelineStore(repo, base_dir=ref.store_dir, project_id=ref.project_id)
    chunk = ChunkRecord(
        id=0,
        file="a.py",
        start_line=1,
        end_line=1,
        symbol=None,
        text="x",
        enriched="x",
    )
    store.save_chunks([chunk])
    assert store.chunks_path.is_file()
    assert store_lock_file(store.base).is_file()


def test_initialize_repo_quiesces_before_index(ce_home: Path, tmp_path: Path) -> None:
    from unittest.mock import patch

    from pipeline.repo_lifecycle import initialize_repo

    repo = tmp_path / "repo"
    repo.mkdir()
    quiesce = patch("pipeline.store_lock.quiesce_background_indexing").start()
    with patch("pipeline.repo_lifecycle.index_is_usable", return_value=False), patch(
        "pipeline.indexer.index_repo"
    ) as index_repo:
        index_repo.return_value = type("S", (), {"chunks": 1})()
        out = initialize_repo(repo, confirm=True)
    quiesce.assert_called()
    assert out.get("ok") is True
