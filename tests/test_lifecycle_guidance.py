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
    joined = " ".join(s.get("action", "") + " " + s.get("why", "") for s in guide["steps"])
    assert "reload mcp" not in joined.lower()
    assert any("root=" in (s.get("action") or "") or "root=" in (s.get("why") or "") for s in guide["steps"])


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
    # Gate-pause resolution moved from the retired mcp_locate tool to the neutral
    # gate_cli layer in the Map V3 migration. Paused -> "p" is still the contract.
    from pipeline.gate_cli import gate_line_for_root

    monkeypatch.setattr("pipeline.pause_resume.is_paused", lambda: True)
    monkeypatch.setattr("pipeline.pause_resume.is_resuming", lambda: False)
    assert gate_line_for_root() == "p"


# NOTE: test_locate_tools_blocked_when_paused and test_backend_error_repo_paused_hint
# asserted the mcp_locate tool's paused/backend-error RESPONSE SHAPES (_paused_locate_err,
# _backend_error). Those response envelopes were part of the old 8-tool surface and were
# retired in the Map V3 migration (Map V3 emits its own payloads). The live paused signal
# is covered by test_gate_line_paused_when_globally_paused above. See
# archive/old-mcp-map/ for the retired tool and its original tests.
