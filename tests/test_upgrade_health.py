"""Health check retry behavior after upgrade."""

from __future__ import annotations

from unittest.mock import patch

import pipeline.upgrade_platform as plat


def test_health_check_retries_until_ok(monkeypatch):
    calls = {"n": 0}

    def fake_probe(*, timeout: float = 5.0):
        calls["n"] += 1
        if calls["n"] < 3:
            return {"ok": False, "error": "connection refused", "installed_version": "0.3.10"}
        return {"ok": True, "installed_version": "0.3.10", "daemon_version": "0.3.10", "health": {"ok": True}}

    monkeypatch.setattr(plat, "_health_probe", fake_probe)
    monkeypatch.setattr("time.sleep", lambda _s: None)

    out = plat.health_check(retries=5, pause_s=0.1)
    assert out["ok"] is True
    assert out["attempts"] == 3


def test_health_check_exhausts_retries(monkeypatch):
    monkeypatch.setattr(
        plat,
        "_health_probe",
        lambda **kwargs: {"ok": False, "error": "down", "installed_version": "0.3.10"},
    )
    monkeypatch.setattr("time.sleep", lambda _s: None)

    out = plat.health_check(retries=2, pause_s=0.1)
    assert out["ok"] is False
    assert out["attempts"] == 2
