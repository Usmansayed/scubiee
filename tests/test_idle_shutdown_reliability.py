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
