"""Tests for lifecycle next-action guidance."""

from __future__ import annotations

from pathlib import Path


def test_next_action_globally_paused(monkeypatch, tmp_path: Path) -> None:
    from pipeline import lifecycle_guidance as lg

    monkeypatch.setattr(lg, "lifecycle_snapshot", lambda _root=None: {
        "globally_paused": True,
        "machine_ready": True,
        "repo_enrolled": True,
        "repo_managed": True,
        "repo_paused": False,
        "project_id": "ce_test",
        "daemon_healthy": False,
        "cursor_connected": True,
        "root": str(tmp_path),
    })
    guide = lg.next_actions(tmp_path)
    assert guide["state"] == "globally_paused"
    assert guide["steps"][0]["action"] == "none — Scubiee is stopped"
    assert any(s.get("action") == "scubiee resume" for s in guide["steps"])
    assert lg.primary_recovery_action(guide) == "scubiee resume"


def test_next_action_repo_paused(monkeypatch, tmp_path: Path) -> None:
    from pipeline import lifecycle_guidance as lg

    monkeypatch.setattr(lg, "lifecycle_snapshot", lambda _root=None: {
        "globally_paused": False,
        "machine_ready": True,
        "repo_enrolled": True,
        "repo_managed": True,
        "repo_paused": True,
        "project_id": "ce_test",
        "daemon_healthy": True,
        "cursor_connected": True,
        "root": str(tmp_path),
    })
    guide = lg.next_actions(tmp_path)
    assert guide["state"] == "repo_paused"
    assert guide["steps"][0]["action"] == "scubiee activate ."
    assert lg.primary_recovery_action(guide) == "scubiee activate ."


def test_next_action_not_enrolled(monkeypatch, tmp_path: Path) -> None:
    from pipeline import lifecycle_guidance as lg

    monkeypatch.setattr(lg, "lifecycle_snapshot", lambda _root=None: {
        "globally_paused": False,
        "machine_ready": True,
        "repo_enrolled": False,
        "repo_managed": False,
        "repo_paused": False,
        "project_id": None,
        "daemon_healthy": False,
        "cursor_connected": False,
        "root": str(tmp_path),
    })
    guide = lg.next_actions(tmp_path)
    assert guide["state"] == "repo_not_enrolled"
    assert guide["steps"][0]["action"] == "scubiee init ."


def test_next_action_ready(monkeypatch, tmp_path: Path) -> None:
    from pipeline import lifecycle_guidance as lg

    monkeypatch.setattr(lg, "lifecycle_snapshot", lambda _root=None: {
        "globally_paused": False,
        "machine_ready": True,
        "repo_enrolled": True,
        "repo_managed": True,
        "repo_paused": False,
        "project_id": "ce_test",
        "daemon_healthy": True,
        "cursor_connected": True,
        "root": str(tmp_path),
    })
    guide = lg.next_actions(tmp_path)
    assert guide["state"] == "ready"
    assert guide["steps"][0]["action"] == "none"


def test_gate_line_paused_when_globally_paused(monkeypatch) -> None:
    from pipeline import mcp_locate as ml

    monkeypatch.setattr("pipeline.pause_resume.is_paused", lambda: True)
    assert ml._gate_line() == "p"


def test_locate_tools_blocked_when_paused(monkeypatch, tmp_path: Path) -> None:
    from pipeline import mcp_locate as ml

    monkeypatch.setattr("pipeline.pause_resume.is_paused", lambda: True)
    payload = ml._paused_locate_err("map")
    import json

    data = json.loads(payload)
    assert data["paused"] is True
    assert data["ok"] is False
    assert data["should_use_mcp"] is False
    assert "native" in data["hint"].lower()


def test_backend_error_repo_paused_hint(tmp_path: Path) -> None:
    from pipeline.mcp_locate import _backend_error
    import json

    payload = json.loads(
        _backend_error(
            "map",
            tmp_path,
            {"status": "paused", "error": "paused", "ok": False},
            hint="",
        )
    )
    assert "activate" in payload["hint"].lower()
