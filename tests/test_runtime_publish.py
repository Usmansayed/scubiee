"""RuntimeManager publish-after-sync + IndexManager / health."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_BACKGROUND_SYNC", "0")
    from pipeline.ce_service import RuntimeManager

    # fresh singleton not needed — construct directly
    return RuntimeManager()


def test_publish_engine_bumps_generation(runtime, tmp_path: Path):
    repo = tmp_path / "proj"
    repo.mkdir()
    runtime.repo = repo
    fake = MagicMock()
    fake.texts = ["a", "b", "c"]

    with patch("pipeline.ce_service.clear_engines") as clear, patch(
        "pipeline.ce_service.load_engine", return_value=fake
    ) as load:
        g0 = runtime.generation
        out = runtime.publish_engine({"reason": "test"})
        assert out["ok"] is True
        assert runtime.generation == g0 + 1
        assert runtime.engine is fake
        assert runtime.last_sync_at is not None
        clear.assert_called()
        load.assert_called_with(repo, force_reload=True)

        out2 = runtime.publish_engine()
        assert runtime.generation == g0 + 2


def test_keeper_on_refresh_wired(runtime, tmp_path: Path):
    repo = tmp_path / "r"
    repo.mkdir()
    with patch.object(runtime, "_should_start_keeper", return_value=True):
        with patch("pipeline.ce_service.BackgroundSyncLoop") as Loop:
            loop = MagicMock()
            loop.running = False
            Loop.return_value = loop
            runtime._start_keeper(repo)
            Loop.assert_called_once()
            kwargs = Loop.call_args.kwargs
            assert kwargs.get("on_refresh") == runtime.publish_engine
            loop.start.assert_called_once()


def test_runtime_routes_live_events_to_active_keeper(runtime, tmp_path: Path):
    repo = tmp_path / "r"
    repo.mkdir()
    runtime.repo = repo
    loop = MagicMock()
    runtime.sync_loop = loop

    dirty = runtime.mark_dirty(["pkg/a.py"], reason="write")
    located = runtime.note_locate()

    assert dirty == {"ok": True, "paths": ["pkg/a.py"], "reason": "write"}
    assert located == {"ok": True}
    loop.mark_dirty.assert_called_once_with(["pkg/a.py"], reason="write")
    loop.note_locate.assert_called_once()


def test_sync_publishes_when_refreshed(runtime, tmp_path: Path, monkeypatch):
    repo = tmp_path / "r"
    repo.mkdir()
    runtime.repo = repo
    monkeypatch.setattr(
        runtime,
        "_gate",
        lambda root=None: None,
    )
    with patch.object(
        runtime.index,
        "sync",
        return_value={"ok": True, "refreshed": True, "files": ["a.py"]},
    ):
        with patch.object(
            runtime, "publish_engine", return_value={"ok": True, "generation": 1}
        ) as pub:
            out = runtime.sync(repo)
            pub.assert_called_once()
            assert out.get("published", {}).get("ok") is True


def test_health_includes_generation(runtime):
    h = runtime.health()
    assert h["ok"] is True
    assert "generation" in h
    assert "index_usable" in h
    assert "last_sync_at" in h


def test_index_deferred_from_manager(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "home"))
    from pipeline.index_manager import IndexManager
    from pipeline.indexer import IndexDeferred

    im = IndexManager()
    with patch(
        "pipeline.indexer.index_repo",
        side_effect=IndexDeferred("paused", pressure="critical"),
    ):
        out = im.full_index(tmp_path)
    assert out["ok"] is False
    assert out["deferred"] is True
    assert out["pressure"] == "critical"
