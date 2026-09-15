from __future__ import annotations

from pipeline.process_job import cpu_rate_for_percent, engine_cpu_cap_pct, engine_popen_kwargs


def test_cpu_rate_for_percent_30() -> None:
    assert cpu_rate_for_percent(30) == 3000
    assert cpu_rate_for_percent(1) == 100
    assert cpu_rate_for_percent(100) == 10000


def test_engine_spawn_breaks_away_from_cursor_job(monkeypatch) -> None:
    import os
    import subprocess

    from pipeline.process_job import CREATE_BREAKAWAY_FROM_JOB, CREATE_NO_WINDOW, engine_popen_kwargs

    # Soft default: no console flash (JobObject BREAKAWAY_OK covers Cursor job).
    monkeypatch.delenv("CTX_ENGINE_HARD_DETACH", raising=False)
    kwargs = engine_popen_kwargs()
    flags = int(kwargs.get("creationflags") or 0)
    if os.name != "nt":
        assert "creationflags" not in kwargs or flags == 0
        assert kwargs.get("start_new_session") is True
        return
    assert flags & CREATE_NO_WINDOW
    assert not (flags & CREATE_BREAKAWAY_FROM_JOB)

    # Hard detach when explicitly requested.
    monkeypatch.setenv("CTX_ENGINE_HARD_DETACH", "1")
    hard = engine_popen_kwargs()
    hflags = int(hard.get("creationflags") or 0)
    assert hflags & CREATE_NO_WINDOW
    assert hflags & CREATE_BREAKAWAY_FROM_JOB
    assert hflags & int(getattr(subprocess, "DETACHED_PROCESS", 0x8))
    assert hflags & int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    assert hard.get("close_fds") is True


def test_engine_cpu_cap_pct_default(monkeypatch) -> None:
    monkeypatch.delenv("CTX_ENGINE_CPU_CAP_PCT", raising=False)
    assert engine_cpu_cap_pct() == 20.0
    monkeypatch.setenv("CTX_ENGINE_CPU_CAP_PCT", "25")
    assert engine_cpu_cap_pct() == 25.0
