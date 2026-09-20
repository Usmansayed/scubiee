"""Unit tests for leave-only idle + mcp_host_sim observatory helpers."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_should_idle_stop_requires_leave_stamp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_DISCONNECT_DEBOUNCE_S", "10")
    from pipeline.lifecycle_runtime import (
        DESIRED_RUN,
        note_activity,
        register_client,
        set_desired_mode,
        should_idle_stop,
        unregister_client,
    )

    set_desired_mode(DESIRED_RUN)
    note_activity(now=100.0)
    assert should_idle_stop(now=10_000.0) is False

    register_client("mcp:sim@1", pid=1, now=200.0)
    unregister_client("mcp:sim@1", now=210.0)
    assert should_idle_stop(now=215.0) is False
    assert should_idle_stop(now=220.0) is True


def test_host_sim_first_map_budget_is_3s_after_settle() -> None:
    from pipeline.mcp_host_sim.scenario import FIRST_MAP_BUDGET_MS, LOCATE_BUDGET_MS, WARM_BUDGET_S

    assert FIRST_MAP_BUDGET_MS == 3000.0
    assert LOCATE_BUDGET_MS == 1000.0
    assert WARM_BUDGET_S == 40.0


def test_dense_d_channel_map_ok_helper() -> None:
    from pipeline.mcp_host_sim.scenario import dense_d_channel_map_ok

    assert dense_d_channel_map_ok(
        {
            "ok": True,
            "dense": True,
            "timings": {"dense": True, "retrieve_mode": "D_channel_best"},
            "cards": [{"file": "a.py"}],
        }
    )
    assert not dense_d_channel_map_ok(
        {"ok": True, "cards": [{"file": "a.py"}], "suggested_seed": {"file": "a.py"}}
    )


def test_observatory_tick_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    from pipeline.mcp_host_sim.observatory import observatory_tick

    tick = observatory_tick("http://127.0.0.1:18765")
    assert "engine" in tick
    assert "clients" in tick
    assert "running" in tick["engine"]
