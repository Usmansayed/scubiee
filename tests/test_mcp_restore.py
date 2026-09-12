"""MCP restore after unlock/upgrade stubs — Cursor + other AI coding hosts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import write_machine_setup


def test_is_stubbed_mcp_entry_detects_noop() -> None:
    from pipeline.mcp_restore import is_stubbed_mcp_entry, mcp_entry_needs_restore
    from pipeline.process_control import mcp_noop_command

    cmd, args = mcp_noop_command()
    stub = {"command": cmd, "args": args}
    assert is_stubbed_mcp_entry(stub) is True
    assert mcp_entry_needs_restore(stub) is True

    live = {"command": "scubiee-mcp-bridge", "args": []}
    assert is_stubbed_mcp_entry(live) is False
    assert mcp_entry_needs_restore(live) is False

    # 0.3.67+ Windows pin: pythonw -m pipeline.mcp_bridge (NOT scubiee-mcp*.exe).
    # Misclassifying this as a stub rewrites mcp.json on every engine start and
    # Cursor restarts MCP in a loop (watchdog spawn storm + terminal blink).
    win_bridge = {
        "command": r"C:/Users/usman/AppData/Roaming/uv/tools/scubiee/Scripts/pythonw.exe",
        "args": ["-u", "-m", "pipeline.mcp_bridge"],
        "env": {"CTX_MCP_BRIDGE_SPAWN_JSON": '["pythonw.exe","-u","-m","pipeline.mcp_locate"]'},
    }
    assert is_stubbed_mcp_entry(win_bridge) is False
    assert mcp_entry_needs_restore(win_bridge) is False

    locate = {
        "command": "/usr/bin/python3",
        "args": ["-u", "-m", "pipeline.mcp_locate"],
    }
    assert mcp_entry_needs_restore(locate) is False

    disabled = {"command": "scubiee-mcp-bridge", "disabled": True}
    assert mcp_entry_needs_restore(disabled) is True

    off = {"command": "scubiee-mcp-bridge", "enabled": False}
    assert mcp_entry_needs_restore(off) is True


def test_enrich_clears_sticky_disabled_for_cursor() -> None:
    from pipeline.mcp_permissions import enrich_server_entry_permissions

    entry = {
        "command": "scubiee-mcp-bridge",
        "args": [],
        "disabled": True,
        "enabled": False,
    }
    out = enrich_server_entry_permissions(entry, "cursor")
    assert "disabled" not in out
    assert out.get("enabled") is True
    assert out.get("autoApprove")


def test_enrich_forces_disabled_false_for_cline() -> None:
    from pipeline.mcp_permissions import enrich_server_entry_permissions

    entry = {"command": "scubiee-mcp-bridge", "args": [], "disabled": True}
    out = enrich_server_entry_permissions(entry, "cline")
    assert out.get("disabled") is False


def test_restore_live_mcp_pins_rewrites_stubbed_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline.connect_state import save_connected_tools
    from pipeline.mcp_restore import restore_live_mcp_pins
    from pipeline.process_control import mcp_noop_command
    from pipeline.project_id import save_registry

    home = tmp_path / "ce-home"
    home.mkdir()
    write_machine_setup(home)
    monkeypatch.setenv("CTX_HOME", str(home))
    save_connected_tools(["cursor"])

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    pid = "ce_restore_test_1234567890abcdef"
    (repo / ".scubiee").mkdir()
    (repo / ".scubiee" / "id.json").write_text(
        json.dumps({"project_id": pid}),
        encoding="utf-8",
    )
    save_registry(
        {
            "projects": {
                pid: {
                    "managed": True,
                    "root": str(repo.resolve()),
                    "paths": [str(repo.resolve())],
                }
            }
        }
    )

    mcp = repo / ".cursor" / "mcp.json"
    mcp.parent.mkdir(parents=True)
    cmd, args = mcp_noop_command()
    mcp.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "scubiee": {"command": cmd, "args": args, "disabled": True},
                    "other": {"command": "keep-me"},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    out = restore_live_mcp_pins(project=repo, force=True)
    assert out.get("ok") is True
    assert out.get("restored") is True or not out.get("skipped")

    data = json.loads(mcp.read_text(encoding="utf-8"))
    scubiee = data["mcpServers"]["scubiee"]
    assert data["mcpServers"]["other"]["command"] == "keep-me"
    assert scubiee.get("disabled") is not True
    blob = f"{scubiee.get('command')} {' '.join(str(a) for a in (scubiee.get('args') or []))}".lower()
    assert "scubiee" in blob or "pipeline.mcp" in blob
    assert not (str(scubiee.get("command", "")).lower() in {"cmd", "cmd.exe", "true"})


def test_restore_mcp_after_failed_upgrade_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pipeline import upgrade_supervisor as us

    monkeypatch.setattr(
        "pipeline.mcp_restore.restore_live_mcp_pins",
        lambda force=False: {"ok": True, "restored": True, "force": force},
    )
    out = us._restore_mcp_after_failed_upgrade()
    assert out.get("ok") is True
    assert out.get("restored") is True
    assert out.get("force") is True


def test_scan_detects_stubbed_cursor_mcp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline.mcp_restore import scan_mcp_pins_needing_restore
    from pipeline.process_control import mcp_noop_command

    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    (home / "connected_tools.json").write_text(
        json.dumps(["cursor"]), encoding="utf-8"
    )

    repo = tmp_path / "repo"
    repo.mkdir()
    mcp = repo / ".cursor" / "mcp.json"
    mcp.parent.mkdir(parents=True)
    cmd, args = mcp_noop_command()
    mcp.write_text(
        json.dumps({"mcpServers": {"scubiee": {"command": cmd, "args": args}}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    scan = scan_mcp_pins_needing_restore()
    assert scan["needs_restore"] is True
    assert any("mcp.json" in p for p in scan["paths"])


def test_clear_cursor_disabled_scubiee(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlite3

    from pipeline.mcp_restore import clear_cursor_disabled_scubiee

    app = tmp_path / "AppData"
    ws = app / "Cursor" / "User" / "workspaceStorage" / "abc"
    ws.mkdir(parents=True)
    db = ws / "state.vscdb"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
    con.execute(
        "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
        (
            "cursor/disabledMcpServers",
            json.dumps(
                [
                    "project-0-context-engine-scubiee",
                    "project-0-context-engine-figma",
                    "user-other",
                ]
            ),
        ),
    )
    con.commit()
    con.close()
    monkeypatch.setenv("APPDATA", str(app))

    report = clear_cursor_disabled_scubiee()
    assert report["ok"] is True
    assert report["cleared"]
    con = sqlite3.connect(str(db))
    raw = con.execute(
        "SELECT value FROM ItemTable WHERE key = ?",
        ("cursor/disabledMcpServers",),
    ).fetchone()[0]
    con.close()
    kept = json.loads(raw)
    assert "project-0-context-engine-scubiee" not in kept
    assert "project-0-context-engine-figma" in kept
    assert "user-other" in kept
