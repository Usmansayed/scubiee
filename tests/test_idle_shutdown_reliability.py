"""Reliability tests for MCP disconnect → stale client → daemon stop."""

from __future__ import annotations

from unittest.mock import MagicMock

from pipeline import lifecycle_runtime as life
from pipeline.memory_governor import MemoryGovernor, reset_governor_for_tests
from pipeline.server import _is_passive_http_path


def test_passive_http_paths_exclude_status_and_health() -> None:
    assert _is_passive_http_path("/health", method="GET")
    assert _is_passive_http_path("/v1/status", method="GET")
    assert _is_passive_http_path("/v1/status", method="POST")
    assert _is_passive_http_path("/status", method="POST")
    assert not _is_passive_http_path("/v1/search", method="POST")
    assert not _is_passive_http_path("/v1/open", method="POST")
    assert not _is_passive_http_path("/v1/client/register", method="POST")


def test_touch_client_extends_stale_deadline(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "25")
    monkeypatch.setattr(life, "_client_pid_trustworthy", lambda _meta: True)

    life.register_client("mcp:1", pid=1, now=100.0)
    assert life.touch_client("mcp:1", now=120.0) is True
    # 24s after touch — still alive; 25s — evicted.
    assert len(life.reconcile_clients(now=144.0)) == 1
    assert len(life.reconcile_clients(now=145.0)) == 0
    assert life.load_policy()["last_client_left_at"] == 145.0


def test_idle_stop_timeline_after_mcp_disconnect(tmp_path, monkeypatch) -> None:
    """Stale eviction (~25s) + leave anchor (~25s) → stop (~50s total)."""
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "25")
    monkeypatch.setattr(life, "_client_pid_trustworthy", lambda _meta: True)
    life.set_desired_mode(life.DESIRED_RUN)

    life.register_client("mcp:1", pid=1, now=0.0)
    life.unregister_client("mcp:1", now=0.0)
    assert life.load_policy()["last_client_left_at"] == 0.0

    assert life.should_idle_stop(now=24.0) is False
    assert life.should_idle_stop(now=25.0) is True


def test_stale_zombie_client_timeline(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "25")
    monkeypatch.setattr(life, "_client_pid_trustworthy", lambda _meta: True)
    life.set_desired_mode(life.DESIRED_RUN)

    life.register_client("mcp:1", pid=1, now=100.0)
    assert life.reconcile_clients(now=124.0)
    assert not life.reconcile_clients(now=125.0)
    assert life.load_policy()["last_client_left_at"] == 125.0
    assert life.should_idle_stop(now=149.0) is False
    assert life.should_idle_stop(now=150.0) is True


def test_apply_idle_policy_enters_standby_after_disconnect(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "25")
    monkeypatch.setattr(life, "_client_pid_trustworthy", lambda _meta: True)
    life.set_desired_mode(life.DESIRED_RUN)

    stopped = {"called": False}

    def fake_standby(**kwargs):
        stopped["called"] = True
        return {"ok": True, "policy": life.load_policy(), "engine": {"ok": True}}

    monkeypatch.setattr("pipeline.daemon.is_running", lambda: True)
    monkeypatch.setattr(life, "enter_standby", fake_standby)

    life.register_client("mcp:1", pid=1, now=1000.0)
    life.unregister_client("mcp:1", now=1000.0)
    result = life.apply_idle_policy(now=1025.0)
    assert result.get("action") == "standby"
    assert stopped["called"] is True


def test_apply_idle_policy_retries_stop_when_engine_survives_standby(
    tmp_path, monkeypatch
) -> None:
    """A failed stop must not wedge the engine on forever.

    ``enter_standby`` flips the mode to standby *before* stopping, and the
    engine's own idle sweeper cannot kill itself (``safe_terminate_pid`` skips
    ``self_or_ancestor``). That leaves mode=standby with a live engine; if the
    sweep treats standby as "nothing to do" it never retries and the engine
    outlives the IDE indefinitely.
    """
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "25")
    monkeypatch.setattr(life, "_client_pid_trustworthy", lambda _meta: True)

    stopped = {"called": False}

    def fake_standby(**kwargs):
        stopped["called"] = kwargs.get("stop_engine", False)
        return {"ok": True, "policy": life.load_policy(), "engine": {"ok": True}}

    monkeypatch.setattr("pipeline.daemon.is_running", lambda: True)
    monkeypatch.setattr(life, "enter_standby", fake_standby)

    life.register_client("mcp:1", pid=1, now=1000.0)
    life.unregister_client("mcp:1", now=1000.0)
    # Simulate the earlier sweep that flipped the mode but failed to kill it.
    life.set_desired_mode(life.DESIRED_STANDBY)

    result = life.apply_idle_policy(now=1025.0)
    assert result.get("action") == "standby", result
    assert stopped["called"] is True


def test_apply_idle_policy_noop_when_standby_and_no_engine(tmp_path, monkeypatch) -> None:
    """Standby with nothing running stays a cheap no-op."""
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "25")
    monkeypatch.setattr("pipeline.daemon.is_running", lambda: False)

    assert life.apply_idle_policy(now=1025.0).get("action") == "already_standby"


def test_note_activity_after_unregister_resets_leave_anchor(
    tmp_path, monkeypatch
) -> None:
    """Interactive use after disconnect clears leave anchor and restarts idle clock."""
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "30")

    life.register_client("mcp:1", pid=1, now=100.0)
    life.unregister_client("mcp:1", now=100.0)
    life.note_activity(now=120.0)
    assert life.load_policy()["last_client_left_at"] is None
    assert life.should_idle_stop(now=149.0) is False
    assert life.should_idle_stop(now=151.0) is True


def test_governor_ignores_hub_activity_when_no_mcp_clients(
    tmp_path, monkeypatch
) -> None:
    """Status/keeper hub touches must not block demotion after MCP gone."""
    reset_governor_for_tests()
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_EMBED_IDLE_DEMOTE_S", "10")
    monkeypatch.setattr(life, "active_client_count", lambda: 0)
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.idle_stop_debounced",
        lambda **_: None,
    )
    # No disconnect grace stamp — fall back to last_semantic_at.
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.load_policy",
        lambda: {"last_client_left_at": None},
    )

    fixed_now = 1000.0
    gov = MemoryGovernor()
    gov.desired_tier = "serve_1repo"
    gov.apply_tier("serve_1repo")
    gov.last_semantic_at = fixed_now - 20

    hub = MagicMock()
    hub.list_status.return_value = [{"project_id": "p1"}]
    runtime = MagicMock()
    runtime.last_activity_at = fixed_now  # would block if used
    hub.get.return_value = runtime

    monkeypatch.setattr("pipeline.engine.release_embedders", lambda: 0)
    result = gov.maybe_demote_idle(hub, now=fixed_now)
    assert result is not None
    assert result["action"] == "demote_serve"
    assert gov.active_tier == "locate_only"


def test_governor_holds_warm_through_disconnect_grace(
    tmp_path, monkeypatch
) -> None:
    """After MCP leaves, keep embedder warm until the idle grace elapses."""
    reset_governor_for_tests()
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_EMBED_IDLE_DEMOTE_S", "15")
    monkeypatch.setattr(life, "active_client_count", lambda: 0)
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.idle_stop_debounced",
        lambda **_: None,
    )
    left_at = 1000.0
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.load_policy",
        lambda: {"last_client_left_at": left_at},
    )

    gov = MemoryGovernor()
    gov.desired_tier = "serve_1repo"
    gov.apply_tier("serve_1repo")
    # Semantic was long ago — without leave anchoring this would demote immediately.
    gov.last_semantic_at = left_at - 60

    monkeypatch.setattr("pipeline.engine.release_embedders", lambda: 0)

    still_warm = gov.maybe_demote_idle(now=left_at + 10)
    assert still_warm is None
    assert gov.active_tier == "serve_1repo"

    demoted = gov.maybe_demote_idle(now=left_at + 16)
    assert demoted is not None
    assert demoted["action"] == "demote_serve"
    assert gov.active_tier == "locate_only"


def test_touch_mcp_client_reregisters_after_stale_eviction(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "25")
    monkeypatch.setattr(life, "_client_pid_trustworthy", lambda _meta: True)

    from pipeline import mcp_locate

    client_id = "mcp:test-session"
    mcp_locate._MCP_CLIENT_ID = client_id
    life.register_client(client_id, pid=9999, now=100.0)
    assert not life.reconcile_clients(now=130.0)

    mcp_locate._touch_mcp_client()
    assert life.reconcile_clients(now=131.0)
    assert life.load_policy()["last_client_left_at"] is None
