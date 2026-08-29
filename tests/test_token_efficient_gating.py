"""Token-efficient MCP gating: connect-time tools, minimal instructions, init rules."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.rules_installer import install_tool, write_project_gate_rules
from pipeline.tool_registry import TOOL_MAP


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    return home


def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()
    return path


def test_connect_writes_mcp_only_no_global_rules(fake_home: Path, tmp_path: Path) -> None:
    workspace = _git_repo(tmp_path / "ws")
    report = install_tool(TOOL_MAP["cursor"], repo=workspace)
    assert report["ok"]
    assert report["rule_written"] is None
    assert report.get("rule_skipped") == "connect is MCP-only; rules written on init"
    assert (fake_home / ".cursor" / "mcp.json").is_file()
    assert not (fake_home / ".cursor" / "rules" / "scubiee.mdc").exists()


def test_init_writes_project_gate_rules(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "proj")
    ce = repo / ".scubiee"
    ce.mkdir()
    pid = "ce_test1234567890abcdef12345678"
    (ce / "id.json").write_text(json.dumps({"project_id": pid}), encoding="utf-8")

    report = write_project_gate_rules(repo)
    assert report["ok"]
    assert report["gate_line"].startswith("1:")
    assert not report["skipped"]

    cursor_rule = repo / ".cursor" / "rules" / "scubiee.mdc"
    assert cursor_rule.is_file()
    text = cursor_rule.read_text(encoding="utf-8")
    assert f"GATE 1:{pid}" in text
    assert "map" in text
    assert pid in text
    assert "BAN native Grep" in text
    assert "Locate trajectory" not in text

    agents = repo / "AGENTS.md"
    assert agents.is_file()
    assert pid in agents.read_text(encoding="utf-8")


def test_init_skips_rules_when_unenrolled(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "proj")
    report = write_project_gate_rules(repo)
    assert report["skipped"]
    assert report["skip_reason"] == "repo not enrolled"
    assert not (repo / ".cursor" / "rules" / "scubiee.mdc").exists()


def test_minimal_mcp_instructions_when_unmanaged(monkeypatch) -> None:
    from pipeline import mcp_locate as ml

    monkeypatch.delenv("CTX_MCP_BARE_INSTRUCTIONS", raising=False)
    monkeypatch.setattr(ml, "_is_repo_managed", lambda: False)
    monkeypatch.setattr(ml, "_gate_line", lambda just_checked=False: "0")
    text = ml._server_instructions("phase")
    assert text.startswith("GATE 0.")
    assert len(text) <= 200, f"instructions too long: {len(text)} chars"
    assert "map(query)" not in text


def test_managed_mcp_instructions_include_trajectory(monkeypatch) -> None:
    from pipeline import mcp_locate as ml

    monkeypatch.delenv("CTX_MCP_BARE_INSTRUCTIONS", raising=False)
    monkeypatch.setattr(ml, "_is_repo_managed", lambda: True)
    monkeypatch.setattr(ml, "_gate_line", lambda just_checked=False: "1:ce_test")
    text = ml._server_instructions("phase")
    assert "map(query)" in text
    assert "focus" in text
    assert "grep(pattern" in text
    assert "session_id" in text
    assert "tool bans are in the project GATE rule" in text
    assert "OVERRIDE" in text
    assert "NEVER grep first" in text
    assert "BAN native" not in text
    assert "STRICTLY" not in text


def test_unmanaged_phase_surface_exposes_gate_only(monkeypatch) -> None:
    pytest.importorskip("mcp")
    from pipeline.mcp_locate import create_mcp

    monkeypatch.delenv("CTX_MCP_SURFACE", raising=False)
    monkeypatch.setattr("pipeline.mcp_locate._is_repo_managed", lambda: False)
    tools = set(create_mcp(name="test-unmanaged")._tool_manager._tools)
    assert tools == {"gate"}


def test_managed_phase_surface_exposes_full_toolkit(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    from pipeline.mcp_locate import create_mcp

    monkeypatch.delenv("CTX_MCP_SURFACE", raising=False)
    monkeypatch.setattr("pipeline.mcp_locate._is_repo_managed", lambda: True)

    tools = set(create_mcp(name="test-managed")._tool_manager._tools)
    assert tools == {
        "gate",
        "map",
        "focus",
        "grep",
        "glob",
        "workspace",
        "status",
    }
