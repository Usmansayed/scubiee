"""Warm autoload phase machine + demand contracts."""

from __future__ import annotations

import time
from pathlib import Path

import pytest


def test_phase_roundtrip_prewarm_dense(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    from pipeline import warm_autoload as wa

    monkeypatch.setattr(wa, "_home", lambda: tmp_path)
    begin = wa.begin_prewarm()
    assert begin["phase"] == wa.PHASE_PREWARM
    assert wa.in_prewarm() is True
    assert wa.should_ignore_health_fail() is True
    assert wa.idle_busy_reason() == "warm_phase:prewarm"

    end = wa.end_prewarm(ok=True)
    assert end["phase"] == wa.PHASE_DENSE
    assert wa.in_prewarm() is False
    assert wa.should_ignore_health_fail() is False


def test_begin_prewarm_does_not_refresh_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    from pipeline import warm_autoload as wa

    monkeypatch.setattr(wa, "_home", lambda: tmp_path)
    first = wa.begin_prewarm()
    ts = float(first["updated_at"])
    time.sleep(0.05)
    second = wa.begin_prewarm()
    assert second["updated_at"] == ts
    assert wa.DEFAULT_PREWARM_MAX_AGE_S == 45.0
    wa.end_prewarm(ok=True)
    wa._PHASE = wa.PHASE_DOWN
    wa._UPDATED_AT = 0.0
    wa._ERROR = None


def test_stale_prewarm_becomes_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    from pipeline import warm_autoload as wa

    monkeypatch.setattr(wa, "_home", lambda: tmp_path)
    wa._PHASE = wa.PHASE_DOWN
    wa._UPDATED_AT = 0.0
    wa._ERROR = None
    wa.begin_prewarm()
    # Backdate disk stamp
    path = wa.phase_path()
    import json

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["updated_at"] = time.time() - 9999
    path.write_text(json.dumps(raw), encoding="utf-8")
    # Clear memory so disk wins
    wa._PHASE = wa.PHASE_DOWN
    wa._UPDATED_AT = 0.0
    snap = wa.read_phase(max_age_s=180.0)
    assert snap.get("phase") == wa.PHASE_ERROR
    assert snap.get("stale") is True


def test_hung_prewarm_should_abort(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    from pipeline import warm_autoload as wa

    monkeypatch.setattr(wa, "_home", lambda: tmp_path)
    wa._PHASE = wa.PHASE_DOWN
    wa._UPDATED_AT = 0.0
    wa._ERROR = None
    wa.begin_prewarm()
    path = wa.phase_path()
    import json

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["updated_at"] = time.time() - 60
    path.write_text(json.dumps(raw), encoding="utf-8")
    wa._PHASE = wa.PHASE_DOWN
    wa._UPDATED_AT = 0.0
    assert wa.hung_prewarm_should_abort(max_age_s=45.0) is True
    wa.mark_down()
    raw = json.loads(wa.phase_path().read_text(encoding="utf-8"))
    raw["updated_at"] = time.time() - 3600
    raw["phase"] = "down"
    wa.phase_path().write_text(json.dumps(raw), encoding="utf-8")
    wa._PHASE = wa.PHASE_DOWN
    wa._UPDATED_AT = 0.0
    assert wa.hung_prewarm_should_abort(max_age_s=45.0) is False
    stamp = tmp_path / "embed_prewarm.busy"
    stamp.write_text(f"{time.time() - 3600} 999999", encoding="utf-8")
    assert wa.hung_prewarm_should_abort(max_age_s=45.0) is False


def test_mcp_demand_with_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline import warm_autoload as wa

    monkeypatch.setattr(wa, "mcp_frontend_present", lambda: True)
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.active_client_count",
        lambda: 0,
    )
    clients, demand = wa.mcp_or_client_demand()
    assert clients == 0
    assert demand is True
