"""Token-efficient MCP gating: connect-time tools, minimal instructions, init rules."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.rules_installer import install_tool, write_project_gate_rules
from pipeline.tool_registry import TOOL_MAP

from conftest import write_machine_setup


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


def test_connect_writes_mcp_only_no_global_rules(fake_home: Path, tmp_path: Path, monkeypatch) -> None:
    from conftest import enroll_test_repo

    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    workspace = _git_repo(tmp_path / "ws")
    enroll_test_repo(
        workspace, home=home, project_id="ce_tokengate1234567890abcdef"
    )
    report = install_tool(TOOL_MAP["cursor"], repo=workspace)
    assert report["ok"]
    assert report["rule_written"] is None
    assert report.get("rule_skipped") == "project rules written on enrolled repos"
    assert (workspace / ".cursor" / "mcp.json").is_file()
    assert not (fake_home / ".cursor" / "mcp.json").exists()


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
    assert "USE Scubiee" in text or "use Scubiee" in text.lower()
    assert "BAN native" in text
    assert "HOST OVERRIDE" in text
    assert "Locate trajectory" not in text
    assert "focus budget" not in text.lower()

    agents = repo / "AGENTS.md"
    assert agents.is_file()
    assert pid in agents.read_text(encoding="utf-8")


def test_init_skips_rules_when_unenrolled(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "proj")
    report = write_project_gate_rules(repo)
    assert report["skipped"]
    assert report["skip_reason"] == "repo not enrolled"
    assert not (repo / ".cursor" / "rules" / "scubiee.mdc").exists()


def test_bind_first_mcp_instructions_when_spawn_unmanaged(monkeypatch) -> None:
    from pipeline import mcp_locate as ml

    monkeypatch.delenv("CTX_MCP_BARE_INSTRUCTIONS", raising=False)
    monkeypatch.setattr(ml, "_is_repo_managed", lambda: False)
    monkeypatch.setattr(ml, "_gate_line", lambda just_checked=False: "0")
    text = ml._server_instructions("phase")
    assert text.startswith("GATE 0.")
    assert len(text) <= 320, f"instructions too long: {len(text)} chars"
    assert "Pass root=" in text
    assert "map|focus|grep" in text or "map" in text
    assert "map(query)" not in text
    assert "USE native" not in text
    assert ml.SERVER_INSTRUCTIONS_PHASE not in text


def test_managed_mcp_instructions_include_trajectory(monkeypatch) -> None:
    from pipeline import mcp_locate as ml

    monkeypatch.delenv("CTX_MCP_BARE_INSTRUCTIONS", raising=False)
    monkeypatch.setattr(ml, "_is_repo_managed", lambda: True)
    monkeypatch.setattr(ml, "_gate_line", lambda just_checked=False: "1:ce_test")
    text = ml._server_instructions("phase")
    assert "map(query)" in text
    assert "focus" in text
    assert "grep(pattern" in text
    assert "Project GATE rule" in text or "prefer Scubiee" in text.lower()
    assert "OVERRIDE" in text
    assert "Flexibility" in text or "user intent wins" in text
    assert "No tool path bans" in text or "no file-type restrictions" in text.lower()
    assert "expand(handle" in text
    assert "BAN native" not in text
    assert "STRICTLY" not in text


def test_unmanaged_phase_surface_exposes_full_toolkit(monkeypatch) -> None:
    pytest.importorskip("mcp")
    from pipeline.mcp_locate import create_mcp

    monkeypatch.delenv("CTX_MCP_SURFACE", raising=False)
    monkeypatch.setattr("pipeline.mcp_locate._is_repo_managed", lambda: False)
    tools = set(create_mcp(name="test-unmanaged")._tool_manager._tools)
    assert tools == {
        "gate",
        "map",
        "focus",
        "grep",
        "glob",
        "workspace",
        "expand",
        "status",
    }


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
        "expand",
        "status",
    }


def test_gate_with_root_marks_enrolled_managed(tmp_path: Path, monkeypatch) -> None:
    """Spawn-unmanaged process: gate(root=) binds enrolled repo."""
    pytest.importorskip("mcp")
    from pipeline.mcp_locate import create_mcp

    enrolled = _git_repo(tmp_path / "enrolled")
    pid = "ce_bindfirst1234567890abcdef12"
    ce = enrolled / ".scubiee"
    ce.mkdir()
    (ce / "id.json").write_text(json.dumps({"project_id": pid}), encoding="utf-8")
    from pipeline.project_id import save_registry

    save_registry(
        {
            "projects": {
                pid: {
                    "managed": True,
                    "root": str(enrolled.resolve()),
                    "paths": [str(enrolled.resolve())],
                }
            }
        }
    )
    junk = tmp_path / "spawn"
    junk.mkdir()
    monkeypatch.chdir(junk)
    monkeypatch.delenv("CTX_REPO", raising=False)

    mcp = create_mcp(name="test-gate-root")
    line = mcp._tool_manager._tools["gate"].fn(root=str(enrolled))
    assert line.startswith(f"1:{pid}")
    from pipeline import mcp_locate

    mcp_locate._LAST_MANAGED_REPO = None
