"""Disconnect RAM contract: last MCP gone → engine process exits (not soft-unload)."""

from __future__ import annotations

from unittest.mock import MagicMock

from pipeline import lifecycle_runtime as life
from pipeline.embedder import disable_ort_cpu_mem_arena, fastembed_session_kwargs
from pipeline.process_control import sweep_orphan_scubiee_frontends


def test_apply_idle_policy_always_stop_engine_after_debounce(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_DISCONNECT_DEBOUNCE_S", "10")
    monkeypatch.setenv("CTX_ENGINE_TRANSITION_DEBOUNCE_S", "0")
    monkeypatch.setattr(life, "_client_pid_trustworthy", lambda _m: True)
    monkeypatch.setattr("pipeline.daemon.is_running", lambda: False)
    monkeypatch.setattr(life, "_idle_busy_reason", lambda: None)
    monkeypatch.setattr("pipeline.engine.ensure_embedder_ready", lambda *_a, **_k: {"ok": True})
    monkeypatch.setattr(
        "pipeline.memory_governor.get_governor",
        lambda: MagicMock(ensure_semantic_tier=lambda: None, indexing=False),
    )

    called: list[dict] = []

    def _standby(*, stop_engine: bool = True):
        called.append({"stop_engine": stop_engine})
        return {"ok": True, "policy": {}, "engine": {"ok": True, "running": False}}

    monkeypatch.setattr(life, "enter_standby", _standby)
    monkeypatch.setattr(
        "pipeline.process_control.sweep_orphan_scubiee_frontends",
        lambda **_: {"ok": True, "killed": []},
    )

    life.set_desired_mode(life.DESIRED_RUN)
    life.register_client("mcp:probe", pid=1, now=100.0)
    life.unregister_client("mcp:probe", now=100.0)
    out = life.apply_idle_policy(now=110.0, force=True)
    assert out["action"] == "standby"
    assert called == [{"stop_engine": True}]


def test_unregister_logs_leave_and_arms_debounce(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setattr(life, "_client_pid_trustworthy", lambda _m: True)
    monkeypatch.setattr("pipeline.engine.ensure_embedder_ready", lambda *_a, **_k: {"ok": True})
    monkeypatch.setattr(
        "pipeline.memory_governor.get_governor",
        lambda: MagicMock(ensure_semantic_tier=lambda: None, indexing=False),
    )
    life.register_client("mcp:x", pid=1, now=50.0)
    life.unregister_client("mcp:x", now=50.0)
    err = capsys.readouterr().err
    assert "client_left" in err
    assert "debounce_arm" in err
    assert life.load_policy()["last_client_left_at"] == 50.0


def test_orphan_frontend_sweep_kills_dead_parent_mcp_only(monkeypatch) -> None:
    procs = [
        {
            "pid": 11,
            "exe": r"C:\uv\tools\scubiee\Scripts\scubiee-mcp.exe",
            "cmdline": "scubiee-mcp",
        },
        {
            "pid": 22,
            "exe": r"C:\uv\tools\scubiee\Scripts\python.exe",
            "cmdline": "python -m pipeline engine run . --port 8765",
        },
        {
            "pid": 33,
            "exe": r"C:\uv\tools\scubiee\Scripts\scubiee-mcp.exe",
            "cmdline": "scubiee-mcp",
        },
    ]
    monkeypatch.setattr(
        "pipeline.process_control.enumerate_scubiee_processes",
        lambda **_: procs,
    )
    monkeypatch.setattr(
        "pipeline.process_control._frontend_parent_gone",
        lambda pid: pid == 11,
    )
    killed: list[int] = []

    def _term(pid, **_):
        killed.append(int(pid))
        return {"pid": pid, "terminated": True}

    monkeypatch.setattr("pipeline.process_control.safe_terminate_pid", _term)
    out = sweep_orphan_scubiee_frontends()
    assert killed == [11]
    assert 22 not in killed
    assert out["killed"] == [11]


def test_disable_ort_cpu_mem_arena_sets_env(monkeypatch) -> None:
    monkeypatch.delenv("ORT_ENABLE_CPU_MEM_ARENA", raising=False)
    info = disable_ort_cpu_mem_arena()
    assert info["ok"] is True
    assert __import__("os").environ.get("ORT_ENABLE_CPU_MEM_ARENA") == "0"
    extra = fastembed_session_kwargs()
    assert isinstance(extra, dict)
