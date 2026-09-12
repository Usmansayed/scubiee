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


def test_alive_mcp_client_not_stale_without_touch(tmp_path, monkeypatch) -> None:
    """Quiet IDE must stay registered — unload is disconnect-driven only."""
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "10")
    monkeypatch.setattr(life, "_client_pid_trustworthy", lambda _meta: True)

    life.register_client("mcp:1", pid=1, now=100.0)
    assert life.touch_client("mcp:1", now=120.0) is True
    assert len(life.reconcile_clients(now=10_000.0)) == 1
    assert life.load_policy()["last_client_left_at"] is None


def test_idle_stop_timeline_after_mcp_disconnect(tmp_path, monkeypatch) -> None:
    """Unregister → wait disconnect debounce (10s) → stop."""
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_DISCONNECT_DEBOUNCE_S", "10")
    monkeypatch.setattr(life, "_client_pid_trustworthy", lambda _meta: True)
    life.set_desired_mode(life.DESIRED_RUN)

    life.register_client("mcp:1", pid=1, now=0.0)
    life.unregister_client("mcp:1", now=0.0)
    assert life.load_policy()["last_client_left_at"] == 0.0

    assert life.should_idle_stop(now=9.0) is False
    assert life.should_idle_stop(now=10.0) is True


def test_dead_pid_evicts_then_disconnect_debounce(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_DISCONNECT_DEBOUNCE_S", "10")
    # First register with trustworthy, then die.
    state = {"alive": True}

    def _trust(meta):
        return bool(state["alive"])

    monkeypatch.setattr(life, "_client_pid_trustworthy", _trust)
    life.set_desired_mode(life.DESIRED_RUN)

    life.register_client("mcp:1", pid=1, now=100.0)
    assert life.reconcile_clients(now=100.0)
    state["alive"] = False
    assert not life.reconcile_clients(now=101.0)
    assert life.load_policy()["last_client_left_at"] == 101.0
    assert life.should_idle_stop(now=110.0) is False
    assert life.should_idle_stop(now=111.0) is True


def test_apply_idle_policy_enters_standby_after_disconnect(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_DISCONNECT_DEBOUNCE_S", "10")
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
    result = life.apply_idle_policy(now=1010.0)
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
    monkeypatch.setenv("CTX_DISCONNECT_DEBOUNCE_S", "10")
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

    result = life.apply_idle_policy(now=1010.0)
    assert result.get("action") == "standby", result
    assert stopped["called"] is True


def test_apply_idle_policy_noop_when_standby_and_no_engine(tmp_path, monkeypatch) -> None:
    """Standby with nothing running stays a cheap no-op."""
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "25")
    monkeypatch.setattr("pipeline.daemon.is_running", lambda: False)

    assert life.apply_idle_policy(now=1025.0).get("action") == "already_standby"


def test_note_activity_preserves_disconnect_stamp(
    tmp_path, monkeypatch
) -> None:
    """Interactive touches must not cancel disconnect unload after MCP leave."""
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_DISCONNECT_DEBOUNCE_S", "10")

    life.register_client("mcp:1", pid=1, now=100.0)
    life.unregister_client("mcp:1", now=100.0)
    assert life.should_idle_stop(now=110.0) is True
    life.note_activity(now=120.0)
    assert life.load_policy()["last_client_left_at"] == 100.0
    assert life.should_idle_stop(now=999.0) is True


def test_governor_ignores_hub_activity_when_no_mcp_clients(
    tmp_path, monkeypatch
) -> None:
    """Without a disconnect stamp, hub activity must not demote (hold until leave)."""
    reset_governor_for_tests()
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_DISCONNECT_DEBOUNCE_S", "10")
    monkeypatch.setattr(life, "active_client_count", lambda: 0)
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
    runtime.last_activity_at = fixed_now
    hub.get.return_value = runtime

    monkeypatch.setattr("pipeline.engine.release_embedders", lambda: (_ for _ in ()).throw(AssertionError("unload")))
    assert gov.maybe_demote_idle(hub, now=fixed_now) is None
    assert gov.active_tier == "serve_1repo"


def test_governor_holds_warm_through_disconnect_grace(
    tmp_path, monkeypatch
) -> None:
    """After MCP leaves, keep embedder warm until the 10s disconnect debounce."""
    reset_governor_for_tests()
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_DISCONNECT_DEBOUNCE_S", "10")
    monkeypatch.setattr(life, "active_client_count", lambda: 0)
    left_at = 1000.0
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.load_policy",
        lambda: {"last_client_left_at": left_at},
    )

    gov = MemoryGovernor()
    gov.desired_tier = "serve_1repo"
    gov.apply_tier("serve_1repo")
    gov.last_semantic_at = left_at - 60

    monkeypatch.setattr("pipeline.engine.release_embedders", lambda: 0)
    monkeypatch.setattr("pipeline.engine.clear_engines", lambda: None)

    still_warm = gov.maybe_demote_idle(now=left_at + 9)
    assert still_warm is None
    assert gov.active_tier == "serve_1repo"

    demoted = gov.maybe_demote_idle(now=left_at + 10)
    assert demoted is not None
    assert demoted["action"] == "demote_serve"
    assert gov.active_tier == "locate_only"


def test_touch_mcp_client_reregisters_after_dead_pid_eviction(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_DISCONNECT_DEBOUNCE_S", "10")
    state = {"alive": True}
    monkeypatch.setattr(life, "_client_pid_trustworthy", lambda _m: bool(state["alive"]))

    from pipeline import mcp_locate

    client_id = "mcp:test-session"
    mcp_locate._MCP_CLIENT_ID = client_id
    life.register_client(client_id, pid=9999, now=100.0)
    state["alive"] = False
    assert not life.reconcile_clients(now=101.0)

    state["alive"] = True
    mcp_locate._touch_mcp_client()
    assert life.reconcile_clients(now=102.0)
    assert life.load_policy()["last_client_left_at"] is None


def _quiet_governor(monkeypatch) -> None:
    """Keep the sweeper's memory-governor beat out of the way of lifecycle asserts."""
    from pipeline import ce_service

    monkeypatch.setattr(
        ce_service, "get_context_engine", MagicMock(side_effect=RuntimeError("no engine"))
    )


def test_retire_self_schedules_hard_exit(monkeypatch) -> None:
    from pipeline import server

    monkeypatch.setattr(server, "_HTTPD", None)
    started: list[str] = []

    class _Thread:
        def __init__(self, target=None, name=None, daemon=None):
            started.append(str(name or ""))

        def start(self) -> None:
            started.append("started")

    monkeypatch.setattr(server.threading, "Thread", _Thread)
    assert server._retire_self() is True
    assert "ce-self-retire" in started
    assert "started" in started


def test_idle_sweeper_retires_self_when_stop_cannot_kill_own_pid(monkeypatch) -> None:
    """stop_daemon skips the engine's own pid; disconnect standby always retires."""
    import threading

    from pipeline import server

    _quiet_governor(monkeypatch)
    monkeypatch.setattr(
        life,
        "apply_idle_policy",
        lambda: {"action": "standby", "engine": {"ok": True, "running": True, "killed": []}},
    )

    retired = threading.Event()

    def _mark_retired() -> bool:
        retired.set()
        return True

    monkeypatch.setattr(server, "_retire_self", _mark_retired)

    stop = threading.Event()
    thread = server._start_idle_sweeper(interval_s=0.0, stop_event=stop)
    thread.join(timeout=5.0)
    stop.set()

    assert retired.is_set()
    assert not thread.is_alive(), "sweeper must exit once it has retired the server"


def test_idle_sweeper_retires_self_on_any_standby(monkeypatch) -> None:
    """Disconnect standby must exit this process even if stop_daemon reports
    running=False (it cannot kill our own pid). Soft demote is not enough."""
    import threading

    from pipeline import server

    _quiet_governor(monkeypatch)
    monkeypatch.setattr(
        life,
        "apply_idle_policy",
        lambda: {"action": "standby", "engine": {"ok": True, "running": False, "killed": [4242]}},
    )

    retired = threading.Event()

    def _mark_retired() -> bool:
        retired.set()
        return True

    monkeypatch.setattr(server, "_retire_self", _mark_retired)

    stop = threading.Event()
    thread = server._start_idle_sweeper(interval_s=0.0, stop_event=stop)
    thread.join(timeout=5.0)
    stop.set()

    assert retired.is_set()
    assert not thread.is_alive(), "sweeper must exit once it has retired the server"
