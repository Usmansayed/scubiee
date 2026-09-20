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
    monkeypatch.delenv("CTX_SCUBIEE_TOTAL_RSS_MB", raising=False)
    gov = MemoryGovernor()
    gov.desired_tier = "serve_1repo"
    gov.apply_tier("locate_only")

    gov.ensure_semantic_tier()
    assert gov.active_tier == "serve_1repo"
    assert os.environ["CTX_CE_RSS_CAP_MB"] == str(SERVE_1REPO_TARGET_MB)


def test_governor_does_not_smash_tree_rss_pin(monkeypatch) -> None:
    import os

    monkeypatch.setenv("CTX_SCUBIEE_TOTAL_RSS_MB", "1536")
    monkeypatch.delenv("CTX_CE_RSS_CAP_MB", raising=False)
    gov = MemoryGovernor()
    gov.apply_tier("locate_only")
    assert os.environ["CTX_CE_RSS_CAP_MB"] == "1536"
    gov.apply_tier("serve_1repo")
    assert os.environ["CTX_CE_RSS_CAP_MB"] == "1536"


def test_embed_idle_demote_defaults_to_ten_seconds(monkeypatch) -> None:
    monkeypatch.delenv("CTX_EMBED_IDLE_DEMOTE_S", raising=False)
    monkeypatch.delenv("CTX_ENGINE_IDLE_S", raising=False)
    from pipeline.memory_governor import embed_idle_demote_s

    assert embed_idle_demote_s() == 10.0


def test_force_demote_disconnect_unloads_immediately(monkeypatch) -> None:
    reset_governor_for_tests()
    released = []

    monkeypatch.setattr(
        "pipeline.engine.release_embedders",
        lambda: released.append(True) or 1,
    )
    monkeypatch.setattr("pipeline.engine.clear_engines", lambda: None)

    gov = MemoryGovernor()
    gov.desired_tier = "serve_1repo"
    gov.apply_tier("serve_1repo")
    gov.embedder_loaded = True
    out = gov.force_demote_disconnect()
    assert out["action"] == "demote_disconnect"
    assert gov.embedder_loaded is False
    assert gov.active_tier == "locate_only"
    assert released == [True]


def test_governor_demotes_after_semantic_idle(monkeypatch) -> None:
    reset_governor_for_tests()
    monkeypatch.setenv("CTX_EMBED_IDLE_DEMOTE_S", "10")
    now = time.time()
    monkeypatch.setattr("pipeline.lifecycle_runtime.active_client_count", lambda: 0)
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.load_policy",
        lambda: {"last_client_left_at": now - 20},
    )
    gov = MemoryGovernor()
    gov.desired_tier = "serve_1repo"
    gov.apply_tier("serve_1repo")
    gov.last_semantic_at = now - 20

    released = []

    def _release() -> int:
        released.append(True)
        return 1

    monkeypatch.setattr("pipeline.engine.release_embedders", _release)

    result = gov.maybe_demote_idle(now=now)
    assert result is not None
    assert result["action"] == "demote_serve"
    assert result.get("engines_dropped") is True
    assert gov.active_tier == "locate_only"
    assert released == [True]


def test_governor_holds_model_while_mcp_clients_connected(monkeypatch) -> None:
    """Idle IDE with live MCP must keep the embedder for instant map/pack."""
    reset_governor_for_tests()
    monkeypatch.setenv("CTX_EMBED_IDLE_DEMOTE_S", "10")
    monkeypatch.setattr("pipeline.lifecycle_runtime.active_client_count", lambda: 2)
    monkeypatch.setattr("pipeline.engine.release_embedders", lambda: (_ for _ in ()).throw(AssertionError("unload")))

    gov = MemoryGovernor()
    gov.desired_tier = "serve_1repo"
    gov.apply_tier("serve_1repo")
    gov.embedder_loaded = True
    gov.last_semantic_at = time.time() - 3600

    result = gov.maybe_demote_idle(now=time.time())
    assert result is not None
    assert result["action"] == "hold_mcp_clients"
    assert gov.active_tier == "serve_1repo"


def test_governor_demotes_after_disconnect_even_with_recent_semantic(monkeypatch) -> None:
    """After MCP leave + debounce, unload even if a late semantic query ran.

    Disconnect owns the clock — quiet tool idle while connected is held via
    active clients; CLI after close should not keep RAM forever.
    """
    reset_governor_for_tests()
    monkeypatch.setenv("CTX_DISCONNECT_DEBOUNCE_S", "10")
    now = time.time()
    monkeypatch.setattr("pipeline.lifecycle_runtime.active_client_count", lambda: 0)
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.load_policy",
        lambda: {"last_client_left_at": now - 3600},
    )
    monkeypatch.setattr("pipeline.engine.release_embedders", lambda: 0)
    monkeypatch.setattr("pipeline.engine.clear_engines", lambda: None)

    gov = MemoryGovernor()
    gov.desired_tier = "serve_1repo"
    gov.apply_tier("serve_1repo")
    gov.last_semantic_at = now

    result = gov.maybe_demote_idle(now=now)
    assert result is not None
    assert result["action"] == "demote_serve"
    assert gov.active_tier == "locate_only"


def test_governor_demotes_when_client_left_and_no_recent_query(monkeypatch) -> None:
    """The disconnect grace window still expires when nothing else happens."""
    reset_governor_for_tests()
    monkeypatch.setenv("CTX_EMBED_IDLE_DEMOTE_S", "10")
    now = time.time()
    monkeypatch.setattr("pipeline.lifecycle_runtime.active_client_count", lambda: 0)
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.load_policy",
        lambda: {"last_client_left_at": now - 3600},
    )
    monkeypatch.setattr("pipeline.engine.release_embedders", lambda: 0)

    gov = MemoryGovernor()
    gov.desired_tier = "serve_1repo"
    gov.apply_tier("serve_1repo")
    gov.last_semantic_at = now - 3600

    result = gov.maybe_demote_idle(now=now)
    assert result is not None
    assert result["action"] == "demote_serve"
    assert gov.active_tier == "locate_only"


def test_governor_indexing_sets_cap(monkeypatch) -> None:
    gov = MemoryGovernor()
    gov.set_indexing(True)
    assert gov.active_tier == "indexing"
    assert gov.config().rss_target_mb == 1000


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
    monkeypatch.setattr("pipeline.lifecycle_runtime.active_client_count", lambda: 0)
    gov = MemoryGovernor()
    gov.set_indexing(True)
    gov.repo_count = 1
    gov.desired_tier = "serve_1repo"
    gov.last_semantic_at = None
    monkeypatch.setattr("pipeline.engine.release_embedders", lambda: 0)

    tier = gov.demote_after_index()
    assert tier == "locate_only"
    assert gov.indexing is False


def test_demote_after_index_holds_embedder_while_mcp_clients_connected(monkeypatch) -> None:
    monkeypatch.setattr("pipeline.lifecycle_runtime.active_client_count", lambda: 2)
    released = {"n": 0}

    def _release() -> int:
        released["n"] += 1
        return 0

    monkeypatch.setattr("pipeline.engine.release_embedders", _release)
    gov = MemoryGovernor()
    gov.set_indexing(True)
    gov.repo_count = 1
    gov.desired_tier = "serve_1repo"
    gov.last_semantic_at = None
    gov.embedder_loaded = True

    tier = gov.demote_after_index()
    assert released["n"] == 0
    assert gov.embedder_loaded is True
    assert gov.indexing is False
    assert tier == gov.desired_tier
