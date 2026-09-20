"""Contracts for Cursor-open warm traps (prewarm busy, MCP demand, attach)."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_idle_busy_reason_includes_prewarm_stamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    stamp = tmp_path / "embed_prewarm.busy"
    stamp.write_text(str(__import__("time").time()), encoding="utf-8")

    from pipeline import engine as eng
    from pipeline.lifecycle_runtime import _idle_busy_reason, apply_idle_policy
    from pipeline.lifecycle_runtime import DESIRED_RUN, set_desired_mode

    monkeypatch.setattr(eng, "_prewarm_busy_path", lambda: stamp)
    assert _idle_busy_reason() in {"embed_prewarm", "warm_phase:prewarm"}

    set_desired_mode(DESIRED_RUN)
    out = apply_idle_policy(now=100.0)
    assert out.get("action") == "busy"
    assert out.get("reason") in {"embed_prewarm", "warm_phase:prewarm"}


def test_mcp_or_client_demand_sees_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pipeline import watchdog as wd

    monkeypatch.setattr(wd, "mcp_frontend_present", lambda: True)
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.active_client_count",
        lambda: 0,
    )
    clients, demand = wd.mcp_or_client_demand()
    assert clients == 0
    assert demand is True


def test_watchdog_force_starts_when_bridge_present_clients_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline import watchdog as wd
    from pipeline.lifecycle_runtime import DESIRED_RUN, set_desired_mode
    from pipeline import warm_autoload as wa

    wa._PHASE = wa.PHASE_DOWN
    wa._UPDATED_AT = 0.0
    wa._ERROR = None

    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_WATCHDOG_INTERVAL_S", "0.05")
    set_desired_mode(DESIRED_RUN)
    calls: list[str] = []

    monkeypatch.setattr(wd, "_health_ok", lambda: False)
    monkeypatch.setattr(wd, "engine_process_alive", lambda: (False, "none"))
    monkeypatch.setattr(wd, "FAILS_BEFORE_RESTART", 2)
    monkeypatch.setattr(wd, "BACKOFF_S", (0.01, 0.01))
    monkeypatch.setattr(wd, "mcp_frontend_present", lambda: True)
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.engine_should_be_running",
        lambda: True,
    )
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.active_client_count",
        lambda: 0,
    )
    monkeypatch.setattr(
        "pipeline.daemon.force_restart_daemon",
        lambda repo=None: calls.append("restart") or {"ok": True},
    )
    monkeypatch.setattr(
        "pipeline.process_job.attach_supervisor_job",
        lambda: {"ok": True, "skipped": True},
    )
    wd.watchdog_loop(stop_after=0.8)
    assert calls, "MCP bridge present + clients=0 must force-start engine"


def test_kick_embed_prewarm_is_fire_and_forget() -> None:
    from pipeline.mcp_lifecycle import _kick_embed_prewarm
    import inspect

    src = inspect.getsource(_kick_embed_prewarm)
    assert '"wait": False' in src
    assert '"wait": True' not in src


def test_search_warming_while_prewarm(monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.ce_service import RuntimeManager

    monkeypatch.setattr("pipeline.warm_autoload.in_prewarm", lambda **_k: True)
    monkeypatch.setattr("pipeline.engine.embedder_is_loaded", lambda: False)
    ce = RuntimeManager.__new__(RuntimeManager)
    ce.repo = None
    ce.generation = 0
    ce.sync_loop = None
    ce.warm_state = "ready"
    ce.warm_error = None
    monkeypatch.setattr(ce, "_gate", lambda root=None: None)
    out = ce.search("warm autoload map query")
    assert out.get("warming") is True
    assert out.get("status") == "warming"
