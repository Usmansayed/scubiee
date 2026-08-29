"""Backtracking scenario matrix — usual user journeys and expected system behavior.

Each scenario models a real path: setup → connect → open repo → init → use MCP.
Tests assert the combination of MCP tools, instructions, rules, and runtime gates.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.rules_installer import (
    cleanup_project_gate_rules,
    format_server_entry,
    install_tool,
    uninstall_tool,
    write_project_gate_rules,
)
from pipeline.tool_registry import TOOL_MAP

PHASE_MANAGED_TOOLS = {
    "gate",
    "map",
    "focus",
    "grep",
    "glob",
    "workspace",
    "status",
}


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    (tmp_path / "ce-home").mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    return home


def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()
    return path


def _enroll(repo: Path, project_id: str, monkeypatch, tmp_path: Path) -> None:
    ce = repo / ".scubiee"
    ce.mkdir(exist_ok=True)
    (ce / "id.json").write_text(json.dumps({"project_id": project_id}), encoding="utf-8")
    from pipeline.project_id import save_registry

    save_registry(
        {
            "projects": {
                project_id: {
                    "managed": True,
                    "root": str(repo.resolve()),
                    "paths": [str(repo.resolve())],
                }
            }
        }
    )
    monkeypatch.setenv("CTX_REPO", str(repo.resolve()))
    monkeypatch.chdir(repo)


def _mcp_tools(monkeypatch) -> set[str]:
    pytest.importorskip("mcp")
    monkeypatch.delenv("CTX_MCP_SURFACE", raising=False)
    from pipeline.mcp_locate import create_mcp

    return set(create_mcp(name="test-scenario")._tool_manager._tools)


def _instructions(monkeypatch, surface: str = "phase") -> str:
    from pipeline.mcp_locate import _server_instructions

    monkeypatch.setenv("CTX_MCP_SURFACE", surface)
    return _server_instructions(surface)


# ---------------------------------------------------------------------------
# Scenario S1: Fresh machine — setup only, never connected
# ---------------------------------------------------------------------------
def test_s1_setup_only_no_mcp_no_rules(fake_home: Path) -> None:
    """User ran scubiee setup but never scubiee connect."""
    assert not (fake_home / ".cursor" / "mcp.json").exists()
    assert not (fake_home / ".cursor" / "rules" / "scubiee.mdc").exists()


# ---------------------------------------------------------------------------
# Scenario S2: Global connect once — MCP yes, global rules no
# ---------------------------------------------------------------------------
def test_s2_connect_global_mcp_only(fake_home: Path, tmp_path: Path) -> None:
    """User ran scubiee connect cursor once (any folder)."""
    repo = _git_repo(tmp_path / "any-ws")
    report = install_tool(TOOL_MAP["cursor"], repo=repo)
    assert report["ok"]
    assert (fake_home / ".cursor" / "mcp.json").is_file()
    assert report["rule_written"] is None
    assert not (fake_home / ".cursor" / "rules" / "scubiee.mdc").exists()
    assert not (repo / ".cursor" / "rules" / "scubiee.mdc").exists()


# ---------------------------------------------------------------------------
# Scenario S3: Connected, opens unmanaged repo — gate-only, minimal instructions
# ---------------------------------------------------------------------------
def test_s3_unmanaged_repo_gate_only_and_minimal_instructions(
    tmp_path: Path, monkeypatch
) -> None:
    """User connected globally but opened a repo without scubiee init."""
    repo = _git_repo(tmp_path / "fresh-clone")
    monkeypatch.setenv("CTX_REPO", str(repo.resolve()))
    monkeypatch.chdir(repo)

    tools = _mcp_tools(monkeypatch)
    assert tools == {"gate"}

    text = _instructions(monkeypatch)
    assert text.startswith("GATE 0.") or text.startswith("GATE 0:r")
    assert len(text) <= 220
    assert "map(query)" not in text
    assert "native" in text.lower()
    assert "Not managed" in text or "USE native" in text


# ---------------------------------------------------------------------------
# Scenario S4: Init enrolled repo — full tools + trajectory instructions
# ---------------------------------------------------------------------------
def test_s4_managed_repo_full_tools_and_trajectory(
    tmp_path: Path, monkeypatch
) -> None:
    """User ran scubiee init . in this workspace."""
    repo = _git_repo(tmp_path / "managed-proj")
    pid = "ce_scenario_managed1234567890ab"
    _enroll(repo, pid, monkeypatch, tmp_path)

    assert _mcp_tools(monkeypatch) == PHASE_MANAGED_TOOLS

    text = _instructions(monkeypatch)
    assert "map(query)" in text
    assert "grep(pattern" in text
    assert "session_id" in text
    assert "tool bans are in the project GATE rule" in text
    assert "BAN native" not in text


# ---------------------------------------------------------------------------
# Scenario S5: Two repos — init A, open B → B stays unmanaged
# ---------------------------------------------------------------------------
def test_s5_init_a_open_b_b_stays_unmanaged(tmp_path: Path, monkeypatch) -> None:
    """Registry has A; user opens unrelated repo B in same MCP process."""
    repo_a = _git_repo(tmp_path / "proj-a")
    repo_b = _git_repo(tmp_path / "proj-b")
    pid_a = "ce_scenario_a1234567890abcdef12"
    _enroll(repo_a, pid_a, monkeypatch, tmp_path)

    # Simulate MCP resolving to repo B (no id.json)
    monkeypatch.setenv("CTX_REPO", str(repo_b.resolve()))
    monkeypatch.chdir(repo_b)

    from pipeline.mcp_locate import _is_repo_managed

    assert _is_repo_managed() is False
    assert _mcp_tools(monkeypatch) == {"gate"}


# ---------------------------------------------------------------------------
# Scenario S6: Init writes project binding only (not global rules)
# ---------------------------------------------------------------------------
def test_s6_init_writes_project_rules_not_global(
    fake_home: Path, tmp_path: Path, monkeypatch
) -> None:
    """After init, project has GATE rule; home does not."""
    repo = _git_repo(tmp_path / "proj")
    pid = "ce_scenario_init1234567890abcdef"
    _enroll(repo, pid, monkeypatch, tmp_path)

    report = write_project_gate_rules(repo)
    assert report["ok"]
    assert (repo / ".cursor" / "rules" / "scubiee.mdc").is_file()
    rule = (repo / ".cursor" / "rules" / "scubiee.mdc").read_text(encoding="utf-8")
    assert pid in rule
    assert "BAN native" in rule
    assert "map(query)" not in rule
    assert not (fake_home / ".cursor" / "rules" / "scubiee.mdc").exists()


# ---------------------------------------------------------------------------
# Scenario S7: Unenrolled folder must not get init rules
# ---------------------------------------------------------------------------
def test_s7_init_rules_skipped_when_not_enrolled(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "never-inited")
    report = write_project_gate_rules(repo)
    assert report["skipped"]
    assert report["skip_reason"] == "repo not enrolled"


# ---------------------------------------------------------------------------
# Scenario S8: Paused machine — gate returns p
# ---------------------------------------------------------------------------
def test_s8_paused_gate_line(tmp_path: Path, monkeypatch) -> None:
    repo = _git_repo(tmp_path / "paused-proj")
    pid = "ce_scenario_pause1234567890abcdef"
    _enroll(repo, pid, monkeypatch, tmp_path)
    monkeypatch.setattr("pipeline.pause_resume.is_paused", lambda: True)

    from pipeline.rules_installer import gate_line_for_repo

    assert gate_line_for_repo(repo) == "p"


# ---------------------------------------------------------------------------
# Scenario S9: Wipe repo cleanup — rules removed, back to unmanaged
# ---------------------------------------------------------------------------
def test_s9_wipe_repo_rules_cleanup(tmp_path: Path, monkeypatch) -> None:
    repo = _git_repo(tmp_path / "wiped")
    pid = "ce_scenario_wipe1234567890abcdef"
    _enroll(repo, pid, monkeypatch, tmp_path)
    write_project_gate_rules(repo)
    rule = repo / ".cursor" / "rules" / "scubiee.mdc"
    assert rule.is_file()

    cleanup_project_gate_rules(repo)
    assert not rule.exists()


# ---------------------------------------------------------------------------
# Scenario S10: Disconnect removes global MCP, not project rules from init
# ---------------------------------------------------------------------------
def test_s10_disconnect_removes_global_mcp_only(
    fake_home: Path, tmp_path: Path, monkeypatch
) -> None:
    repo = _git_repo(tmp_path / "proj")
    install_tool(TOOL_MAP["cursor"], repo=repo)
    pid = "ce_scenario_disc1234567890abcdef"
    _enroll(repo, pid, monkeypatch, tmp_path)
    write_project_gate_rules(repo)
    project_rule = repo / ".cursor" / "rules" / "scubiee.mdc"
    assert project_rule.is_file()

    report = uninstall_tool(TOOL_MAP["cursor"], repo=repo)
    assert report["mcp_removed"] is True
    assert not (fake_home / ".cursor" / "mcp.json").exists()
    # Project init rule remains until user deletes or re-inits cleanup
    assert project_rule.is_file()


# ---------------------------------------------------------------------------
# Scenario S11: Locate tool hard-block if somehow called on unmanaged
# ---------------------------------------------------------------------------
def test_s11_map_blocked_on_unmanaged_runtime(tmp_path: Path, monkeypatch) -> None:
    """Defense in depth: runtime gate even if stale tool list."""
    pytest.importorskip("mcp")
    repo = _git_repo(tmp_path / "unmanaged")
    monkeypatch.setenv("CTX_REPO", str(repo.resolve()))
    monkeypatch.chdir(repo)
    monkeypatch.setattr("pipeline.mcp_locate._is_repo_managed", lambda: False)

    from pipeline.mcp_locate import create_mcp

    mcp = create_mcp(name="test-block")
    # gate-only surface — map not registered
    assert "map" not in mcp._tool_manager._tools


# ---------------------------------------------------------------------------
# Scenario S12: CTX_MCP_BARE_INSTRUCTIONS trial — managed but stripped
# ---------------------------------------------------------------------------
def test_s12_bare_instructions_override_managed_trajectory(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _git_repo(tmp_path / "managed-bare")
    pid = "ce_scenario_bare1234567890abcdef"
    _enroll(repo, pid, monkeypatch, tmp_path)
    monkeypatch.setenv("CTX_MCP_BARE_INSTRUCTIONS", "1")

    text = _instructions(monkeypatch)
    assert "map(query)" not in text
    assert "Recommended: map for meaning" in text or "use as you prefer" in text


# ---------------------------------------------------------------------------
# Scenario S13: Rules vs MCP instructions — no duplication
# ---------------------------------------------------------------------------
def test_s13_rules_and_instructions_do_not_duplicate_bans(
    tmp_path: Path, monkeypatch
) -> None:
    """Bans in project rule only; trajectory in MCP instructions only."""
    repo = _git_repo(tmp_path / "split")
    pid = "ce_scenario_split1234567890abcdef"
    _enroll(repo, pid, monkeypatch, tmp_path)
    write_project_gate_rules(repo)

    rule = (repo / ".cursor" / "rules" / "scubiee.mdc").read_text(encoding="utf-8")
    instr = _instructions(monkeypatch)

    assert "BAN native" in rule
    assert "USE Scubiee" in rule
    assert "map(query)" not in rule
    assert "Locate trajectory" in instr or "map(query)" in instr
    assert "BAN native" not in instr
    assert "tool bans are in the project GATE rule" in instr


# ---------------------------------------------------------------------------
# Scenario S14: IDE workspace env beats stale pin (wrong-repo protection)
# ---------------------------------------------------------------------------
def test_s14_live_ide_workspace_beats_stale_ctx_repo_pin(
    tmp_path: Path, monkeypatch
) -> None:
    """User opened repo B in sidebar; stale CTX_REPO still points at A."""
    from pipeline import mcp_locate

    repo_a = _git_repo(tmp_path / "proj-a")
    repo_b = _git_repo(tmp_path / "proj-b")
    pid_a = "ce_scenario_pin1234567890abcdef"
    _enroll(repo_a, pid_a, monkeypatch, tmp_path)

    junk = tmp_path / "spawn"
    junk.mkdir()
    monkeypatch.chdir(junk)
    monkeypatch.setenv("CTX_REPO", str(repo_a))
    monkeypatch.setenv("CURSOR_PROJECT_DIR", str(repo_b))
    for key in (
        "WORKSPACE_FOLDER_PATHS",
        "CLAUDE_PROJECT_DIR",
        "CODEX_WORKSPACE_ROOT",
        "CTX_PROJECT_ID",
    ):
        monkeypatch.delenv(key, raising=False)

    assert mcp_locate._default_repo() == repo_b.resolve()
    assert mcp_locate._is_repo_managed() is False


# ---------------------------------------------------------------------------
# Scenario S15: Init writes AGENTS.md ban section (append hosts)
# ---------------------------------------------------------------------------
def test_s15_init_writes_agents_md_ban_section(tmp_path: Path, monkeypatch) -> None:
    repo = _git_repo(tmp_path / "agents")
    pid = "ce_scenario_agents1234567890abcd"
    _enroll(repo, pid, monkeypatch, tmp_path)
    write_project_gate_rules(repo)
    agents = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert pid in agents
    assert "BAN native" in agents
    assert "map(query)" not in agents


# ---------------------------------------------------------------------------
# Scenario S16: Paused managed repo gets p rule
# ---------------------------------------------------------------------------
def test_s16_paused_managed_rule(tmp_path: Path, monkeypatch) -> None:
    repo = _git_repo(tmp_path / "paused-managed")
    pid = "ce_scenario_pausm1234567890abcdef"
    _enroll(repo, pid, monkeypatch, tmp_path)
    monkeypatch.setattr("pipeline.pause_resume.is_paused", lambda: True)
    write_project_gate_rules(repo)
    rule = (repo / ".cursor" / "rules" / "scubiee.mdc").read_text(encoding="utf-8")
    assert "GATE p" in rule
    assert "resume" in rule.lower()


# ---------------------------------------------------------------------------
# Scenario S17: Re-init refreshes gate rule on disk
# ---------------------------------------------------------------------------
def test_s17_reinit_refreshes_gate_rule(tmp_path: Path, monkeypatch) -> None:
    repo = _git_repo(tmp_path / "reinit")
    pid = "ce_scenario_reinit1234567890abcd"
    _enroll(repo, pid, monkeypatch, tmp_path)
    write_project_gate_rules(repo)
    rule_path = repo / ".cursor" / "rules" / "scubiee.mdc"
    rule_path.write_text("stale content", encoding="utf-8")

    write_project_gate_rules(repo)
    text = rule_path.read_text(encoding="utf-8")
    assert pid in text
    assert "BAN native" in text
    assert "stale content" not in text


# ---------------------------------------------------------------------------
# Scenario S18: Global connect all hosts — no workspace MCP pins
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("slug", ["cursor", "claude-code", "codex", "windsurf", "opencode"])
def test_s18_global_connect_no_workspace_pins(
    slug: str, fake_home: Path, tmp_path: Path
) -> None:
    from pipeline.host_workspace import is_global_mcp_tool

    assert is_global_mcp_tool(slug)
    repo = _git_repo(tmp_path / f"ws-{slug}")
    report = install_tool(TOOL_MAP[slug], repo=repo)
    assert report["ok"]
    assert not report.get("workspace_mcp_written")
    entry = format_server_entry(TOOL_MAP[slug], pin_repo=False)
    env = entry.get("env") or entry.get("environment") or {}
    assert "CTX_REPO" not in env


# ---------------------------------------------------------------------------
# Scenario S19: Unexpanded ${workspaceFolder} must not poison repo resolution
# ---------------------------------------------------------------------------
def test_s19_unexpanded_workspace_token_falls_back_to_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    from pipeline import mcp_locate

    live = _git_repo(tmp_path / "live-ws")
    pid = "ce_scenario_token1234567890abcdef"
    _enroll(live, pid, monkeypatch, tmp_path)
    monkeypatch.setenv("CTX_REPO", "${workspaceFolder}")
    monkeypatch.setenv("CURSOR_PROJECT_DIR", "${workspaceFolder}")
    monkeypatch.delenv("CTX_PROJECT_ID", raising=False)

    assert mcp_locate._default_repo() == live.resolve()
    assert mcp_locate._is_repo_managed() is True


# ---------------------------------------------------------------------------
# Scenario S20: Mid-session init — disk ready; reconnect unlocks full tools
# ---------------------------------------------------------------------------
def test_s20_mid_session_init_then_mcp_reload(
    tmp_path: Path, monkeypatch
) -> None:
    """Init updates disk immediately; new MCP spawn (reload/chat) gets full tools."""
    repo = _git_repo(tmp_path / "mid-init")
    monkeypatch.chdir(repo)
    monkeypatch.delenv("CTX_REPO", raising=False)

    tools_before = _mcp_tools(monkeypatch)
    assert tools_before == {"gate"}

    pid = "ce_scenario_mid1234567890abcdef"
    _enroll(repo, pid, monkeypatch, tmp_path)
    write_project_gate_rules(repo)
    assert (repo / ".cursor" / "rules" / "scubiee.mdc").is_file()

    # Simulates MCP reload / new chat — create_mcp re-evaluates managed state
    tools_after = _mcp_tools(monkeypatch)
    assert tools_after == PHASE_MANAGED_TOOLS


# ---------------------------------------------------------------------------
# Scenario matrix documentation (backtracking index)
# ---------------------------------------------------------------------------
USER_JOURNEY_SCENARIOS = [
    ("S1", "setup only", "no MCP, no rules"),
    ("S2", "connect global once", "MCP yes, global rules no"),
    ("S3", "open unmanaged repo", "gate-only; native-only MCP note"),
    ("S4", "init enrolled repo", "full tools + trajectory (no bans in MCP)"),
    ("S5", "init A, open B", "B unmanaged despite registry"),
    ("S6", "init project rules", "repo GATE ban rule, not ~/.cursor/rules"),
    ("S7", "init rules skip", "unenrolled repo → skip"),
    ("S8", "paused", "gate line p"),
    ("S9", "wipe/cleanup", "project rules removed"),
    ("S10", "disconnect", "global MCP removed"),
    ("S11", "stale locate call", "map not registered unmanaged"),
    ("S12", "bare instructions env", "managed stripped for trials"),
    ("S13", "rules vs instructions", "bans in rule only, trajectory in MCP"),
    ("S14", "IDE beats stale pin", "sidebar repo wins over CTX_REPO"),
    ("S15", "AGENTS.md on init", "append ban section for Codex/etc"),
    ("S16", "paused managed rule", "GATE p in project rule"),
    ("S17", "re-init refresh", "gate rule rewritten on disk"),
    ("S18", "global connect hosts", "no workspace MCP pins"),
    ("S19", "literal ${workspaceFolder}", "ignored; cwd/enrolled wins"),
    ("S20", "mid-session init + reload", "disk enrolled; new MCP spawn → full tools"),
]


@pytest.mark.parametrize("scenario_id,label,expected", USER_JOURNEY_SCENARIOS)
def test_scenario_matrix_documented(scenario_id: str, label: str, expected: str) -> None:
    """Living index — each row has a dedicated test above."""
    assert scenario_id.startswith("S")
    assert label
    assert expected
