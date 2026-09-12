"""Contracts that stop the MCP reconnect / watchdog spawn storm."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_start_daemon_source_does_not_heal_mcp_pins() -> None:
    """Engine start must not mutate IDE mcp.json (Cursor file-watcher restart)."""
    root = Path(__file__).resolve().parents[1]
    text = (root / "packages" / "pipeline" / "daemon.py").read_text(encoding="utf-8")
    assert "heal_mcp_pins_if_stubbed" not in text
    assert "restore_live_mcp_pins" not in text


def test_hot_paths_do_not_import_debug_blink() -> None:
    root = Path(__file__).resolve().parents[1] / "packages" / "pipeline"
    offenders: list[str] = []
    for name in (
        "daemon.py",
        "watchdog.py",
        "mcp_bridge.py",
        "mcp_restore.py",
        "process_job.py",
        "process_control.py",
        "silent_spawn.py",
        "freshness.py",
        "project_id.py",
        "lifecycle_runtime.py",
    ):
        text = (root / name).read_text(encoding="utf-8")
        if "_debug_blink" in text:
            offenders.append(name)
    assert offenders == [], f"debug blink hooks still in: {offenders}"


def test_engine_should_be_running_honors_start_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    from pipeline.daemon import note_engine_start_request
    from pipeline.lifecycle_runtime import DESIRED_STANDBY, engine_should_be_running, set_desired_mode

    set_desired_mode(DESIRED_STANDBY)
    assert engine_should_be_running() is False
    note_engine_start_request(repo=str(tmp_path))
    assert engine_should_be_running() is True


def test_windows_server_entry_sets_windows_hide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from pipeline.mcp_install import server_entry
    from pipeline.rules_installer import format_server_entry
    from pipeline.tool_registry import get_tool

    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(
        "pipeline.process_job.background_python",
        lambda: r"C:\fake\pythonw.exe",
    )
    entry = server_entry()
    assert entry.get("windowsHide") is True
    blob = f"{entry.get('command')} {' '.join(str(a) for a in (entry.get('args') or []))}"
    assert "pipeline.mcp_bridge" in blob

    cursor = get_tool("cursor")
    assert cursor is not None
    formatted = format_server_entry(cursor)
    assert formatted.get("windowsHide") is True


def test_restore_noop_skips_cursor_vscdb_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline.mcp_restore import restore_live_mcp_pins

    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    called = {"vscdb": False}

    def _boom() -> dict:
        called["vscdb"] = True
        return {"ok": True, "cleared": []}

    monkeypatch.setattr(
        "pipeline.mcp_restore.scan_mcp_pins_needing_restore",
        lambda: {"ok": True, "needs_restore": False, "paths": [], "count": 0},
    )
    monkeypatch.setattr("pipeline.mcp_restore.clear_cursor_disabled_scubiee", _boom)
    out = restore_live_mcp_pins()
    assert out.get("skipped") is True
    assert called["vscdb"] is False


def test_durable_engine_process_recognizes_boot_scripts() -> None:
    from pipeline.process_control import _is_durable_engine_process

    assert _is_durable_engine_process(
        {"cmdline": r"C:\Users\a\.scubiee\_boot_watchdog.pyw"}
    )
    assert _is_durable_engine_process(
        {"cmdline": r"C:\Users\a\.scubiee\_boot_supervisor.pyw"}
    )
    assert not _is_durable_engine_process(
        {"cmdline": r"pythonw.exe -u -m pipeline.mcp_bridge"}
    )


def test_hot_reload_does_not_rewrite_pythonw_bridge_pin(tmp_path: Path) -> None:
    """Upgrade stamp refresh must not touch pythonw -m pipeline.mcp_bridge pins.

    Rewriting mcp.json is what made Cursor kill/restart the stdio server.
    """
    import json

    from pipeline.mcp_hot_reload import _patch_build_env_in_json

    path = tmp_path / "mcp.json"
    original = {
        "mcpServers": {
            "scubiee": {
                "command": r"C:/Users/usman/AppData/Roaming/uv/tools/scubiee/Scripts/pythonw.exe",
                "args": ["-u", "-m", "pipeline.mcp_bridge"],
                "env": {"CTX_SCUBIEE_BUILD": "0.3.67-old"},
            }
        }
    }
    path.write_text(json.dumps(original, indent=2), encoding="utf-8")
    assert _patch_build_env_in_json(path, "0.3.68-new") is False
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["mcpServers"]["scubiee"]["env"]["CTX_SCUBIEE_BUILD"] == "0.3.67-old"
