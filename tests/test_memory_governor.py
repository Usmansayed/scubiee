from __future__ import annotations

import time
from unittest.mock import MagicMock

from pipeline.memory_governor import (
    EMBED_IDLE_DEMOTE_S,
    LOCATE_ONLY_TARGET_MB,
    SERVE_1REPO_TARGET_MB,
    SERVE_2REPO_TARGET_MB,
    SERVE_MULTI_SESSION_TARGET_MB,
    MemoryGovernor,
    reset_governor_for_tests,
    resolve_desired_tier,
    get_governor,
)


def test_resolve_desired_tier_indexing_first() -> None:
    assert resolve_desired_tier(repo_count=2, max_sessions=3, total_sessions=4, indexing=True) == "indexing"


def test_resolve_desired_tier_two_repos() -> None:
    assert resolve_desired_tier(repo_count=2, max_sessions=1, total_sessions=1, indexing=False) == "serve_2repo"


def test_resolve_desired_tier_multi_session() -> None:
    assert (
        resolve_desired_tier(repo_count=1, max_sessions=2, total_sessions=2, indexing=False)
        == "serve_multi_session"
    )


def test_resolve_desired_tier_single_repo() -> None:
    assert resolve_desired_tier(repo_count=1, max_sessions=1, total_sessions=1, indexing=False) == "serve_1repo"


def test_governor_starts_locate_only_on_refresh(monkeypatch) -> None:
    monkeypatch.setenv("CTX_CE_RSS_CAP_MB", "9999")
    gov = MemoryGovernor()
    hub = MagicMock()
    hub.list_status.return_value = [{"project_id": "p1"}]
    runtime = MagicMock()
    runtime.sessions = {"s1"}
    runtime.indexing = False
    runtime.engine = None
    hub.get.return_value = runtime

    tier = gov.refresh_from_hub(hub)
    assert tier == "locate_only"
    assert gov.desired_tier == "serve_1repo"
    assert gov.active_tier == "locate_only"
    assert gov.config().rss_target_mb == LOCATE_ONLY_TARGET_MB


def test_governor_promotes_on_semantic(monkeypatch) -> None:
    import os

    monkeypatch.delenv("CTX_CE_RSS_CAP_MB", raising=False)
    gov = MemoryGovernor()
    gov.desired_tier = "serve_1repo"
    gov.apply_tier("locate_only")

    gov.ensure_semantic_tier()
    assert gov.active_tier == "serve_1repo"
    assert os.environ["CTX_CE_RSS_CAP_MB"] == str(SERVE_1REPO_TARGET_MB)


def test_embed_idle_demote_defaults_to_lifecycle_idle(monkeypatch) -> None:
    monkeypatch.delenv("CTX_EMBED_IDLE_DEMOTE_S", raising=False)
    monkeypatch.delenv("CTX_ENGINE_IDLE_S", raising=False)
    from pipeline.memory_governor import embed_idle_demote_s

    assert embed_idle_demote_s() == 25.0


def test_governor_demotes_after_semantic_idle(monkeypatch) -> None:
    reset_governor_for_tests()
    monkeypatch.setenv("CTX_EMBED_IDLE_DEMOTE_S", "10")
    gov = MemoryGovernor()
    gov.desired_tier = "serve_1repo"
    gov.apply_tier("serve_1repo")
    gov.last_semantic_at = time.time() - 20

    released = []

    def _release() -> int:
        released.append(True)
        return 1

    monkeypatch.setattr("pipeline.engine.release_embedders", _release)

    result = gov.maybe_demote_idle(now=time.time())
    assert result is not None
    assert result["action"] == "demote_serve"
    assert result.get("engines_dropped") is True
    assert gov.active_tier == "locate_only"
    assert released == [True]


def test_governor_indexing_sets_cap(monkeypatch) -> None:
    gov = MemoryGovernor()
    gov.set_indexing(True)
    assert gov.active_tier == "indexing"
    assert gov.config().rss_target_mb == 800


def test_governor_status_breakdown() -> None:
    gov = MemoryGovernor()
    gov.chunk_count = 5000
    gov.embedder_loaded = False
    gov.repo_count = 1
    status = gov.status()
    assert status["active_tier"] == "locate_only"
    assert "breakdown_mb" in status
    assert status["breakdown_mb"]["embedder"] == 0.0
    assert status["allocation_hint"]


def test_get_governor_singleton() -> None:
    reset_governor_for_tests()
    assert get_governor() is get_governor()


def test_refresh_multi_session_target() -> None:
    gov = MemoryGovernor()
    hub = MagicMock()
    hub.list_status.return_value = [{"project_id": "p1"}]
    runtime = MagicMock()
    runtime.sessions = {"a", "b"}
    runtime.indexing = False
    runtime.engine = MagicMock(texts=["x"] * 100)
    hub.get.return_value = runtime

    gov.ensure_semantic_tier()
    gov.refresh_from_hub(hub)
    assert gov.desired_tier == "serve_multi_session"
    assert gov.config("serve_multi_session").rss_target_mb == SERVE_MULTI_SESSION_TARGET_MB


def test_refresh_two_repos_target() -> None:
    gov = MemoryGovernor()
    hub = MagicMock()
    hub.list_status.return_value = [{"project_id": "p1"}, {"project_id": "p2"}]
    runtimes = [
        MagicMock(sessions=set(), indexing=False, engine=None),
        MagicMock(sessions=set(), indexing=False, engine=None),
    ]
    hub.get.side_effect = runtimes

    gov.ensure_semantic_tier()
    gov.refresh_from_hub(hub)
    assert gov.desired_tier == "serve_2repo"
    assert gov.config("serve_2repo").rss_target_mb == SERVE_2REPO_TARGET_MB


def test_demote_after_index_returns_to_locate_without_recent_semantic(monkeypatch) -> None:
    monkeypatch.setenv("CTX_EMBED_IDLE_DEMOTE_S", str(int(EMBED_IDLE_DEMOTE_S)))
    gov = MemoryGovernor()
    gov.set_indexing(True)
    gov.repo_count = 1
    gov.desired_tier = "serve_1repo"
    gov.last_semantic_at = None
    monkeypatch.setattr("pipeline.engine.release_embedders", lambda: 0)

    tier = gov.demote_after_index()
    assert tier == "locate_only"
    assert gov.indexing is False
