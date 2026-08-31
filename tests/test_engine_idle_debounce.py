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
