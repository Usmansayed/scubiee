"""Tests for scubiee stop/resume (global pause)."""

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
    cursor_mcp = tmp_path / "cursor_mcp.json"
    cursor_mcp.write_text(json.dumps({
        "mcpServers": {
            "scubiee": {"command": "python", "args": ["-m", "pipeline.mcp_locate"]},
            "other-server": {"command": "node", "args": ["index.js"]},
        }
    }, indent=2), encoding="utf-8")

    cursor_rule = tmp_path / "context-agent.mdc"
    cursor_rule.write_text("---\ndescription: Scubiee\n---\nUse Scubiee MCP.\n", encoding="utf-8")

    return {"cursor_mcp": cursor_mcp, "cursor_rule": cursor_rule}


def test_is_paused_default_false(ce_home: Path) -> None:
    from pipeline.pause_resume import is_paused

    assert is_paused() is False


def test_pause_sets_state_and_resume_clears(ce_home: Path) -> None:
    from pipeline.pause_resume import is_paused, pause, resume

    with patch("pipeline.pause_resume._detect_connected_tools", return_value=[]), \
         patch("pipeline.pause_resume._teardown_all_tool_surfaces", return_value=[]), \
         patch("pipeline.pause_resume._strip_agents_md_all_repos", return_value=[]), \
         patch("pipeline.pause_resume._hide_repo_scubiee_dirs", return_value=[]), \
         patch("pipeline.daemon.stop_daemon", return_value={"ok": True}), \
         patch("pipeline.watchdog.stop_watchdog", return_value={"ok": True}), \
         patch("pipeline.lifecycle_runtime.set_desired_mode"):
        result = pause()

    assert result["ok"] is True
    assert is_paused() is True

    with patch("pipeline.pause_resume._restore_enrolled_id_files", return_value=[]), \
         patch("pipeline.rules_installer.install_tool", return_value={"ok": True}), \
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
         patch("pipeline.pause_resume._teardown_all_tool_surfaces", return_value=[]), \
         patch("pipeline.pause_resume._strip_agents_md_all_repos", return_value=[]), \
         patch("pipeline.pause_resume._hide_repo_scubiee_dirs", return_value=[]), \
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
    assert _disable_mcp_json(path, "mcpServers") is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["scubiee"]["disabled"] is True
    assert _enable_mcp_json(path, "mcpServers") is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "disabled" not in data["mcpServers"]["scubiee"]


def test_paused_blocks_action_commands(ce_home: Path) -> None:
    from pipeline.lifecycle_guard import paused_blocks_command
    from pipeline.pause_resume import _save_state

    _save_state({"paused": True})
    assert paused_blocks_command("init") is not None
    assert "resume" in (paused_blocks_command("init") or "").lower()
    assert paused_blocks_command("connect") is None  # allowed — CLI auto-resumes
    assert paused_blocks_command("disconnect") is None
    assert paused_blocks_command("resume") is None
    assert paused_blocks_command("stop") is None
    assert paused_blocks_command("doctor") is None
    assert paused_blocks_command("gate") is None
    assert paused_blocks_command("wipe") is None
    assert paused_blocks_command("list") is None
    assert paused_blocks_command("engine", ["engine", "status"]) is None
    assert paused_blocks_command("engine", ["engine", "start"]) is not None


def test_engine_should_not_run_when_paused(ce_home: Path) -> None:
    from pipeline.lifecycle_runtime import engine_should_be_running
    from pipeline.pause_resume import _save_state

    _save_state({"paused": False})
    _save_state({"paused": True})
    assert engine_should_be_running() is False


def test_ensure_daemon_skips_when_paused(ce_home: Path) -> None:
    from pipeline.pause_resume import _save_state

    _save_state({"paused": True})
    from pipeline.daemon import ensure_daemon

    result = ensure_daemon()
    assert result["skipped"] is True
    assert result["reason"] == "globally_paused"
    assert "resume" in str(result.get("hint") or "").lower()


def test_start_watchdog_skips_when_paused(ce_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.pause_resume import _save_state

    monkeypatch.setenv("CTX_WATCHDOG", "1")
    _save_state({"paused": True})

    from pipeline.watchdog import start_watchdog

    result = start_watchdog()
    assert result["skipped"] is True
    assert result["reason"] == "globally_paused"


def test_remove_mcp_preserves_other_servers(tmp_path: Path) -> None:
    from pipeline.rules_installer import _remove_mcp_json_keyed

    mcp = tmp_path / "mcp.json"
    mcp.write_text(json.dumps({
        "mcpServers": {
            "scubiee": {"command": "python", "args": ["-m", "pipeline.mcp_locate"]},
            "my-custom-mcp": {"command": "node", "args": ["server.js"]},
        }
    }, indent=2), encoding="utf-8")

    assert _remove_mcp_json_keyed(mcp, "mcpServers") is True
    data = json.loads(mcp.read_text(encoding="utf-8"))
    assert "scubiee" not in data["mcpServers"]
    assert "my-custom-mcp" in data["mcpServers"]


def test_pause_saves_connected_tools(ce_home: Path) -> None:
    from pipeline.pause_resume import _load_state, pause

    with patch("pipeline.pause_resume._detect_connected_tools", return_value=["cursor", "kiro"]), \
         patch("pipeline.pause_resume._teardown_all_tool_surfaces", return_value=[]), \
         patch("pipeline.pause_resume._strip_agents_md_all_repos", return_value=[]), \
         patch("pipeline.pause_resume._hide_repo_scubiee_dirs", return_value=[]), \
         patch("pipeline.daemon.stop_daemon", return_value={"ok": True}), \
         patch("pipeline.watchdog.stop_watchdog", return_value={"ok": True}), \
         patch("pipeline.lifecycle_runtime.set_desired_mode"):
        result = pause()

    assert result["connected_tools"] == ["cursor", "kiro"]
    state = _load_state()
    assert state["connected_tools"] == ["cursor", "kiro"]
    assert state["paused"] is True


def test_resume_stays_paused_when_mcp_restore_fails(ce_home: Path) -> None:
    from pipeline.pause_resume import _save_state, is_paused, pause, resume

    with patch("pipeline.pause_resume._detect_connected_tools", return_value=["cursor"]), \
         patch("pipeline.pause_resume._teardown_all_tool_surfaces", return_value=[]), \
         patch("pipeline.pause_resume._strip_agents_md_all_repos", return_value=[]), \
         patch("pipeline.pause_resume._hide_repo_scubiee_dirs", return_value=[]), \
         patch("pipeline.daemon.stop_daemon", return_value={"ok": True}), \
         patch("pipeline.watchdog.stop_watchdog", return_value={"ok": True}), \
         patch("pipeline.lifecycle_runtime.set_desired_mode"):
        pause()

    with patch(
        "pipeline.rules_installer.install_tool",
        return_value={"ok": False, "errors": ["corrupt mcp.json"]},
    ), \
         patch("pipeline.pause_resume._restore_enrolled_id_files", return_value=[]):
        result = resume()

    assert result["ok"] is False
    assert is_paused() is True
    assert "still stopped" in str(result.get("hint") or "").lower()


def test_pause_resume_roundtrip_preserves_other_mcp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from conftest import enroll_test_repo, write_machine_setup

    from pipeline.connect_state import add_connected_tool
    from pipeline.pause_resume import is_paused, pause, resume
    from pipeline.rules_installer import install_tool
    from pipeline.tool_registry import TOOL_MAP

    ce_home = tmp_path / "ce-home"
    write_machine_setup(ce_home)
    monkeypatch.setenv("CTX_HOME", str(ce_home))

    repo = tmp_path / "ws"
    repo.mkdir()
    (repo / ".git").mkdir()
    enroll_test_repo(repo, home=ce_home)

    mcp = repo / ".cursor" / "mcp.json"
    mcp.parent.mkdir(parents=True)
    mcp.write_text(
        json.dumps(
            {"mcpServers": {"other-server": {"command": "node", "args": ["x.js"]}}},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    add_connected_tool("cursor")
    install_report = install_tool(TOOL_MAP["cursor"])
    assert install_report["ok"] is True
    after_install = json.loads(mcp.read_text(encoding="utf-8"))
    assert "scubiee" in after_install["mcpServers"]
    assert "other-server" in after_install["mcpServers"]

    with patch("pipeline.daemon.stop_daemon", return_value={"ok": True}), \
         patch("pipeline.watchdog.stop_watchdog", return_value={"ok": True}), \
         patch("pipeline.lifecycle_runtime.set_desired_mode"):
        pause_result = pause()

    assert pause_result["ok"] is True
    assert is_paused() is True
    after_pause = json.loads(mcp.read_text(encoding="utf-8"))
    assert "scubiee" not in after_pause["mcpServers"]
    assert "other-server" in after_pause["mcpServers"]
    assert not (repo / ".scubiee").exists()

    with patch("pipeline.daemon.ensure_daemon", return_value={"ok": True}), \
         patch("pipeline.watchdog.start_watchdog", return_value={"ok": True}), \
         patch(
             "pipeline.daemon.reconcile_managed_repositories",
             return_value={"reconciled": 0},
         ), \
         patch("pipeline.lifecycle_runtime.set_desired_mode"):
        resume_result = resume()

    assert resume_result["ok"] is True
    assert is_paused() is False
    after_resume = json.loads(mcp.read_text(encoding="utf-8"))
    assert "scubiee" in after_resume["mcpServers"]
    assert "other-server" in after_resume["mcpServers"]
    assert (repo / ".scubiee" / "id.json").is_file()


def test_connect_auto_resumes_when_globally_paused(ce_home: Path) -> None:
    from pipeline.__main__ import main
    from pipeline.pause_resume import _save_state, is_paused

    _save_state({"paused": True, "connected_tools": []})

    with patch("pipeline.pause_resume.resume", return_value={"ok": True}) as mock_resume, \
         patch(
             "pipeline.rules_installer.install_tools",
             return_value=[{"ok": True, "tool": "Cursor", "slug": "cursor"}],
         ):
        assert main(["connect", "--cursor", "--dry-run"]) == 0

    mock_resume.assert_called_once()
    assert is_paused() is True  # resume was mocked — pause state unchanged by mock


def test_is_paused_fail_closed_on_corrupt_state(ce_home: Path) -> None:
    from pipeline.pause_resume import _state_path, is_paused

    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ corrupt json", encoding="utf-8")
    assert is_paused() is True
