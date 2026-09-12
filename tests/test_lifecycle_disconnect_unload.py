"""Disconnect-driven unload: warm while MCP open, 120s debounce after close."""

from __future__ import annotations

from pipeline import lifecycle_runtime as life
from pipeline.memory_governor import MemoryGovernor, reset_governor_for_tests


def test_disconnect_debounce_defaults_to_120(monkeypatch) -> None:
    monkeypatch.delenv("CTX_DISCONNECT_DEBOUNCE_S", raising=False)
    monkeypatch.delenv("CTX_ENGINE_IDLE_S", raising=False)
    monkeypatch.delenv("CTX_EMBED_IDLE_DEMOTE_S", raising=False)
    assert life.disconnect_debounce_seconds() == 120.0
    assert life.idle_seconds() == 120.0


def test_unregister_does_not_demote_immediately(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_DISCONNECT_DEBOUNCE_S", "10")
    reset_governor_for_tests()
    demoted = []

    monkeypatch.setattr(
        "pipeline.memory_governor.MemoryGovernor.force_demote_disconnect",
        lambda self: demoted.append("force") or {"action": "demote_disconnect"},
    )
    monkeypatch.setattr(life, "_client_pid_trustworthy", lambda _m: True)

    life.register_client("mcp:1", pid=1, now=100.0)
    life.unregister_client("mcp:1", now=100.0)
    assert demoted == []
    assert life.load_policy()["last_client_left_at"] == 100.0
    assert life.should_idle_stop(now=109.0) is False
    assert life.should_idle_stop(now=110.0) is True


def test_hold_while_client_connected_ignores_clock(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_DISCONNECT_DEBOUNCE_S", "10")
    monkeypatch.setattr(life, "_client_pid_trustworthy", lambda _m: True)
    life.set_desired_mode(life.DESIRED_RUN)
    life.register_client("mcp:1", pid=1, now=0.0)
    # Hours later with client still registered — stay up.
    assert life.should_idle_stop(now=10_000.0) is False
    assert len(life.reconcile_clients(now=10_000.0)) == 1


def test_dead_pid_evicts_then_debounce_stops(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_DISCONNECT_DEBOUNCE_S", "10")
    monkeypatch.setattr(life, "_client_pid_trustworthy", lambda _m: False)
    life.set_desired_mode(life.DESIRED_RUN)
    life.register_client("mcp:1", pid=1, now=100.0)
    # Force trustworthy false on reconcile
    assert life.reconcile_clients(now=100.0) == []
    assert life.load_policy()["last_client_left_at"] == 100.0
    assert life.should_idle_stop(now=109.0) is False
    assert life.should_idle_stop(now=110.0) is True


def test_governor_demotes_only_after_disconnect_debounce(tmp_path, monkeypatch) -> None:
    reset_governor_for_tests()
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_DISCONNECT_DEBOUNCE_S", "10")
    monkeypatch.setattr(life, "active_client_count", lambda: 0)
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.load_policy",
        lambda: {"last_client_left_at": 1000.0},
    )
    monkeypatch.setattr("pipeline.engine.release_embedders", lambda: 1)
    monkeypatch.setattr("pipeline.engine.clear_engines", lambda: None)

    gov = MemoryGovernor()
    gov.desired_tier = "serve_1repo"
    gov.apply_tier("serve_1repo")
    gov.embedder_loaded = True
    assert gov.maybe_demote_idle(now=1009.0) is None
    out = gov.maybe_demote_idle(now=1010.0)
    assert out is not None
    assert out["action"] == "demote_serve"
