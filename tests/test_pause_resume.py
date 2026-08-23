"""Tests for scubiee sleep/wake (global pause/resume)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def ce_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    return home


@pytest.fixture
def mock_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Create fake MCP configs and rule files for testing."""
    # Fake cursor MCP config
    cursor_mcp = tmp_path / "cursor_mcp.json"
    cursor_mcp.write_text(json.dumps({
        "mcpServers": {
            "context-engine": {"command": "python", "args": ["-m", "pipeline.mcp_locate"]},
            "other-server": {"command": "node", "args": ["index.js"]},
        }
    }, indent=2), encoding="utf-8")

    # Fake cursor rule file
    cursor_rule = tmp_path / "context-agent.mdc"
    cursor_rule.write_text("---\ndescription: Scubiee\n---\nUse Scubiee MCP.\n", encoding="utf-8")

    # Fake kiro MCP config
    kiro_mcp = tmp_path / "kiro_mcp.json"
    kiro_mcp.write_text(json.dumps({
        "mcpServers": {
            "context-engine": {"command": "python", "args": ["-m", "pipeline.mcp_locate"]},
        }
    }, indent=2), encoding="utf-8")

    # Fake kiro rule
    kiro_rule = tmp_path / "context-engine.md"
    kiro_rule.write_text("# Scubiee\nUse MCP tools.\n", encoding="utf-8")

    return {
        "cursor_mcp": cursor_mcp,
        "cursor_rule": cursor_rule,
        "kiro_mcp": kiro_mcp,
        "kiro_rule": kiro_rule,
    }


def test_is_paused_default_false(ce_home: Path) -> None:
    from pipeline.pause_resume import is_paused

    assert is_paused() is False


def test_pause_sets_state_and_resume_clears(ce_home: Path) -> None:
    from pipeline.pause_resume import is_paused, pause, resume

    with patch("pipeline.pause_resume._detect_connected_tools", return_value=[]), \
         patch("pipeline.daemon.stop_daemon", return_value={"ok": True}), \
         patch("pipeline.watchdog.stop_watchdog", return_value={"ok": True}), \
         patch("pipeline.lifecycle_runtime.set_desired_mode"):
        result = pause()

    assert result["ok"] is True
    assert is_paused() is True

    with patch("pipeline.pause_resume._enable_mcp_for_tool", return_value=[]), \
         patch("pipeline.pause_resume._resume_rule_files", return_value=[]), \
         patch("pipeline.lifecycle_runtime.set_desired_mode"), \
         patch("pipeline.daemon.ensure_daemon", return_value={"ok": True}), \
         patch("pipeline.watchdog.start_watchdog", return_value={"ok": True}), \
         patch("pipeline.daemon.reconcile_managed_repositories", return_value={"reconciled": 0}):
        result = resume()

    assert result["ok"] is True
    assert is_paused() is False


def test_pause_is_idempotent(ce_home: Path) -> None:
    from pipeline.pause_resume import is_paused, pause

    with patch("pipeline.pause_resume._detect_connected_tools", return_value=[]), \
         patch("pipeline.daemon.stop_daemon", return_value={"ok": True}), \
         patch("pipeline.watchdog.stop_watchdog", return_value={"ok": True}), \
         patch("pipeline.lifecycle_runtime.set_desired_mode"):
        pause()

    result = pause()
    assert result["ok"] is True
    assert result["already_paused"] is True
    assert is_paused() is True


def test_resume_is_idempotent(ce_home: Path) -> None:
    from pipeline.pause_resume import is_paused, resume

    result = resume()
    assert result["ok"] is True
    assert result["already_active"] is True
    assert is_paused() is False


def test_disable_mcp_json_sets_disabled_field(ce_home: Path, mock_tools: dict[str, Path]) -> None:
    from pipeline.pause_resume import _disable_mcp_json, _enable_mcp_json

    path = mock_tools["cursor_mcp"]

    # Disable
    assert _disable_mcp_json(path, "mcpServers") is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["context-engine"]["disabled"] is True
    # Other server untouched
    assert "disabled" not in data["mcpServers"]["other-server"]

    # Enable
    assert _enable_mcp_json(path, "mcpServers") is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "disabled" not in data["mcpServers"]["context-engine"]


def test_pause_rule_rename_and_restore(ce_home: Path, mock_tools: dict[str, Path]) -> None:
    from pipeline.pause_resume import _PAUSED_SUFFIX

    cursor_rule = mock_tools["cursor_rule"]
    original_content = cursor_rule.read_text(encoding="utf-8")
    paused_path = cursor_rule.with_name(cursor_rule.name + _PAUSED_SUFFIX)

    # Rename to paused
    cursor_rule.rename(paused_path)
    assert not cursor_rule.exists()
    assert paused_path.is_file()
    assert paused_path.read_text(encoding="utf-8") == original_content

    # Restore
    paused_path.rename(cursor_rule)
    assert cursor_rule.is_file()
    assert not paused_path.exists()
    assert cursor_rule.read_text(encoding="utf-8") == original_content


def test_engine_should_not_run_when_paused(ce_home: Path) -> None:
    from pipeline.lifecycle_runtime import engine_should_be_running
    from pipeline.pause_resume import _save_state

    # Not paused — depends on policy (default is standby)
    _save_state({"paused": False})

    # Paused — always False
    _save_state({"paused": True})
    assert engine_should_be_running() is False


def test_ensure_daemon_skips_when_paused(ce_home: Path) -> None:
    from pipeline.pause_resume import _save_state

    _save_state({"paused": True})

    from pipeline.daemon import ensure_daemon

    result = ensure_daemon()
    assert result["skipped"] is True
    assert result["reason"] == "globally_paused"


def test_start_watchdog_skips_when_paused(ce_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.pause_resume import _save_state

    monkeypatch.setenv("CTX_WATCHDOG", "1")
    _save_state({"paused": True})

    from pipeline.watchdog import start_watchdog

    result = start_watchdog()
    assert result["skipped"] is True
    assert result["reason"] == "globally_paused"


def test_pause_saves_connected_tools(ce_home: Path) -> None:
    from pipeline.pause_resume import _load_state, pause

    with patch("pipeline.pause_resume._detect_connected_tools", return_value=["cursor", "kiro"]), \
         patch("pipeline.pause_resume._disable_mcp_for_tool", return_value=[]), \
         patch("pipeline.pause_resume._pause_rule_files", return_value=[]), \
         patch("pipeline.daemon.stop_daemon", return_value={"ok": True}), \
         patch("pipeline.watchdog.stop_watchdog", return_value={"ok": True}), \
         patch("pipeline.lifecycle_runtime.set_desired_mode"):
        result = pause()

    assert result["connected_tools"] == ["cursor", "kiro"]
    state = _load_state()
    assert state["connected_tools"] == ["cursor", "kiro"]
    assert state["paused"] is True


def test_resume_restores_saved_tools(ce_home: Path) -> None:
    from pipeline.pause_resume import _save_state, resume

    _save_state({
        "paused": True,
        "connected_tools": ["cursor", "claude-code"],
        "disabled_mcp": [],
        "renamed_rules": [],
    })

    enabled_calls: list[str] = []
    restored_calls: list[str] = []

    def fake_enable(tool):
        enabled_calls.append(tool.slug)
        return []

    def fake_restore(tool):
        restored_calls.append(tool.slug)
        return []

    with patch("pipeline.pause_resume._enable_mcp_for_tool", side_effect=fake_enable), \
         patch("pipeline.pause_resume._resume_rule_files", side_effect=fake_restore), \
         patch("pipeline.lifecycle_runtime.set_desired_mode"), \
         patch("pipeline.daemon.ensure_daemon", return_value={"ok": True}), \
         patch("pipeline.watchdog.start_watchdog", return_value={"ok": True}), \
         patch("pipeline.daemon.reconcile_managed_repositories", return_value={"reconciled": 2}):
        result = resume()

    assert result["ok"] is True
    assert result["files_reconciled"] == 2
    assert enabled_calls == ["cursor", "claude-code"]
    assert restored_calls == ["cursor", "claude-code"]
