"""Idle window + start/stop transition debounce."""

from __future__ import annotations


def test_default_idle_is_25(monkeypatch, tmp_path):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.delenv("CTX_ENGINE_IDLE_S", raising=False)
    monkeypatch.delenv("CTX_ENGINE_TRANSITION_DEBOUNCE_S", raising=False)
    from pipeline.lifecycle_runtime import (
        DEFAULT_IDLE_S,
        DEFAULT_TRANSITION_DEBOUNCE_S,
        idle_seconds,
        transition_debounce_seconds,
    )

    assert DEFAULT_IDLE_S == 25.0
    assert DEFAULT_TRANSITION_DEBOUNCE_S == 25.0
    assert idle_seconds() == 25.0
    assert transition_debounce_seconds() == 25.0


def test_idle_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "40")
    from pipeline import lifecycle_runtime as lr

    assert lr.idle_seconds() == 40.0


def test_idle_stop_debounced_after_start(monkeypatch, tmp_path):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "25")
    monkeypatch.setenv("CTX_ENGINE_TRANSITION_DEBOUNCE_S", "25")
    from pipeline.lifecycle_runtime import (
        idle_stop_debounced,
        note_engine_transition,
        should_idle_stop,
        register_client,
        unregister_client,
        set_desired_mode,
        DESIRED_RUN,
    )

    set_desired_mode(DESIRED_RUN)
    note_engine_transition("start", now=1000.0)
    blocked = idle_stop_debounced(now=1010.0)
    assert blocked is not None
    assert blocked["blocked"] is True
    assert blocked["wait_s"] == 15.0

    # After debounce window, idle-stop hysteresis clears.
    assert idle_stop_debounced(now=1025.0) is None

    # Client leave + 25s idle still required for should_idle_stop.
    register_client("t", pid=1, now=1025.0)
    # Fake dead pid so reconcile drops it — use unregister instead.
    unregister_client("t", now=1025.0)
    assert should_idle_stop(now=1040.0) is False  # only 15s since leave
    assert should_idle_stop(now=1050.0) is True  # 25s since leave


def test_apply_idle_policy_respects_debounce(monkeypatch, tmp_path):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "25")
    monkeypatch.setenv("CTX_ENGINE_TRANSITION_DEBOUNCE_S", "25")
    from pipeline.lifecycle_runtime import (
        apply_idle_policy,
        note_engine_transition,
        set_desired_mode,
        unregister_client,
        register_client,
        DESIRED_RUN,
    )

    monkeypatch.setattr(
        "pipeline.daemon.is_running",
        lambda: True,
    )
    set_desired_mode(DESIRED_RUN)
    register_client("c1", pid=1, now=1990.0)
    unregister_client("c1", now=1990.0)
    note_engine_transition("start", now=2000.0)

    # Idle elapsed (34s) but start debounce still active (24s < 25s).
    result = apply_idle_policy(now=2024.0)
    assert result.get("action") == "debounced"
    assert result.get("blocked") is True


def test_reconnect_within_grace_cancels_disconnect_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "25")
    from pipeline.lifecycle_runtime import (
        register_client,
        should_idle_stop,
        unregister_client,
    )

    register_client("mcp:1", pid=1, now=100.0)
    unregister_client("mcp:1", now=100.0)
    assert should_idle_stop(now=120.0) is False
    register_client("mcp:1", pid=1, now=110.0)
    assert should_idle_stop(now=130.0) is False


def test_upgrade_start_bypasses_idle_stop_debounce(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "25")
    monkeypatch.setenv("CTX_ENGINE_TRANSITION_DEBOUNCE_S", "25")
    from pipeline.lifecycle_runtime import (
        TRANSITION_REASON_UPGRADE,
        apply_idle_policy,
        complete_upgrade_transition,
        idle_stop_debounced,
        register_client,
        set_desired_mode,
        unregister_client,
        DESIRED_RUN,
    )

    set_desired_mode(DESIRED_RUN)
    complete_upgrade_transition(version="0.4.0", now=1005.0)
    from pipeline.lifecycle_runtime import load_transition

    assert load_transition()["last_start_reason"] == TRANSITION_REASON_UPGRADE
    assert idle_stop_debounced(now=1010.0) is None
    register_client("c1", pid=1, now=1010.0)
    unregister_client("c1", now=1010.0)
    monkeypatch.setattr("pipeline.daemon.is_running", lambda: True)
    stopped = {"called": False}

    def fake_standby(**kwargs):
        stopped["called"] = True
        return {"ok": True, "policy": {}, "engine": {"ok": True}}

    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.enter_standby",
        fake_standby,
    )
    result = apply_idle_policy(now=1036.0)
    assert result.get("action") == "standby"
    assert stopped["called"] is True


def test_apply_idle_policy_skips_during_upgrade(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    from pipeline.lifecycle_runtime import apply_idle_policy, begin_upgrade_transition

    begin_upgrade_transition(version="0.4.0", now=100.0)
    result = apply_idle_policy(now=200.0)
    assert result.get("action") == "upgrade_in_progress"


def test_stale_upgrade_flag_auto_clears(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_UPGRADE_STALE_S", "60")
    from pipeline.lifecycle_runtime import (
        apply_idle_policy,
        begin_upgrade_transition,
        load_transition,
        upgrade_in_progress,
    )

    begin_upgrade_transition(version="0.4.0", now=100.0)
    assert upgrade_in_progress(now=150.0) is True
    assert upgrade_in_progress(now=161.0) is False
    assert load_transition().get("upgrade_in_progress") is False
    result = apply_idle_policy(now=161.0)
    assert result.get("action") != "upgrade_in_progress"


def test_apply_idle_policy_rechecks_clients_before_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "25")
    from pipeline.lifecycle_runtime import (
        DESIRED_RUN,
        apply_idle_policy,
        set_desired_mode,
    )

    set_desired_mode(DESIRED_RUN)
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.should_idle_stop",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.idle_stop_debounced",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.reconcile_clients",
        lambda **kwargs: [{"client_id": "mcp:1"}],
    )
    result = apply_idle_policy(now=1030.0)
    assert result.get("action") == "clients_reconnected"


def test_quiesce_failure_aborts_upgrade_transition(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    from pipeline import lifecycle_runtime as life
    from pipeline.upgrade_platform import quiesce_for_upgrade

    monkeypatch.setattr(
        "pipeline.process_control.release_scubiee_process_locks",
        lambda **kwargs: {"ok": False, "error": "processes_still_running"},
    )
    report = quiesce_for_upgrade()
    assert report["ok"] is False
    assert life.upgrade_in_progress() is False


def test_restart_daemon_if_stale_aborts_on_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    from pipeline import lifecycle_runtime as life
    from pipeline.upgrade import restart_daemon_if_stale

    monkeypatch.setattr("pipeline.upgrade.daemon_version", lambda: "0.3.0")
    monkeypatch.setattr("pipeline.upgrade.installed_version", lambda: "0.3.10")
    monkeypatch.setattr("pipeline.daemon.stop_daemon_for_upgrade", lambda: {"ok": True})
    monkeypatch.setattr(
        "pipeline.daemon.force_restart_daemon",
        lambda *a, **k: {"ok": False, "error": "health_timeout"},
    )
    result = restart_daemon_if_stale()
    assert result["ok"] is False
    assert life.upgrade_in_progress() is False
