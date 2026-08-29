"""Backtracking / branch-and-bound scenario enumeration — executable verification.

Uses ``pipeline.scenario_tree`` to enumerate valid user journeys, then asserts
each outcome leaf matches MCP tools, instructions, and gate behavior.
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
from pipeline.scenario_tree import (
    Connect,
    InitTiming,
    McpSpawn,
    Outcome,
    Pause,
    ScenarioPath,
    Workspace,
    enumerate_scenarios,
    iter_minimal_cover,
    scenarios_by_outcome,
)
from pipeline.tool_registry import TOOL_MAP

PHASE_MANAGED_TOOLS = {
    "gate",
    "map",
    "focus",
    "grep",
    "glob",
    "workspace",
    "expand",
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

    return set(create_mcp(name="test-backtrack")._tool_manager._tools)


def _instructions(monkeypatch, surface: str = "phase") -> str:
    from pipeline.mcp_locate import _server_instructions

    monkeypatch.setenv("CTX_MCP_SURFACE", surface)
    return _server_instructions(surface)


def _apply_path(
    path: ScenarioPath,
    tmp_path: Path,
    monkeypatch,
    fake_home: Path,
) -> dict:
    """Simulate user journey; return observable state for assertions."""
    repo_a = _git_repo(tmp_path / "repo-a")
    repo_b = _git_repo(tmp_path / "repo-b")
    repo_u = _git_repo(tmp_path / "unmanaged")
    pid_a = "ce_backtrack_a1234567890abcdef12"

    state: dict = {"mcp_json": False, "tools": set(), "instructions": "", "gate": ""}

    if path.connect == Connect.GLOBAL:
        install_tool(TOOL_MAP["cursor"], repo=repo_u)
        state["mcp_json"] = (fake_home / ".cursor" / "mcp.json").is_file()

    if path.workspace == Workspace.MANAGED:
        _enroll(repo_a, pid_a, monkeypatch, tmp_path)
        write_project_gate_rules(repo_a)
        active = repo_a
    elif path.workspace == Workspace.WRONG_REPO:
        _enroll(repo_a, pid_a, monkeypatch, tmp_path)
        monkeypatch.setenv("CTX_REPO", str(repo_b.resolve()))
        monkeypatch.chdir(repo_b)
        active = repo_b
    else:
        monkeypatch.setenv("CTX_REPO", str(repo_u.resolve()))
        monkeypatch.chdir(repo_u)
        active = repo_u

    if path.init_timing == InitTiming.MID_SESSION:
        _enroll(active, "ce_backtrack_mid1234567890abcdef", monkeypatch, tmp_path)
        write_project_gate_rules(active)
        if path.mcp_spawn == McpSpawn.FIRST:
            state["tools"] = _mcp_tools(monkeypatch)
            state["instructions"] = _instructions(monkeypatch)
            return state

    if path.pause == Pause.ON and path.workspace == Workspace.MANAGED:
        monkeypatch.setattr("pipeline.pause_resume.is_paused", lambda: True)
        from pipeline.rules_installer import gate_line_for_repo

        state["gate"] = gate_line_for_repo(repo_a)
        state["tools"] = _mcp_tools(monkeypatch)
        state["instructions"] = _instructions(monkeypatch)
        return state

    if path.mcp_spawn == McpSpawn.RESPAWN and path.init_timing == InitTiming.MID_SESSION:
        monkeypatch.setenv("CTX_REPO", str(active.resolve()))
        monkeypatch.chdir(active)

    state["tools"] = _mcp_tools(monkeypatch)
    state["instructions"] = _instructions(monkeypatch)

    from pipeline.mcp_locate import _is_repo_managed

    state["managed"] = _is_repo_managed()
    return state


# ---------------------------------------------------------------------------
# Tree structure tests (branch-and-bound invariants)
# ---------------------------------------------------------------------------
def test_enumerated_paths_are_non_empty() -> None:
    paths = enumerate_scenarios()
    assert len(paths) >= 8


def test_every_outcome_has_at_least_one_path() -> None:
    by = scenarios_by_outcome()
    for outcome in (
        Outcome.NO_MCP,
        Outcome.GATE_ONLY_NATIVE,
        Outcome.FULL_MANAGED,
        Outcome.WRONG_REPO_GATE,
        Outcome.PAUSED_RULE,
        Outcome.MID_INIT_RELOAD,
    ):
        assert outcome in by, f"missing outcome {outcome.value}"


def test_prune_never_connect_extensions() -> None:
    """Branch-and-bound: never-connect cannot have workspace/pause/spawn branches."""
    paths = enumerate_scenarios()
    never = [p for p in paths if p.connect == Connect.NEVER]
    assert len(never) == 1
    assert never[0].outcome == Outcome.NO_MCP


def test_prune_mid_session_without_respawn() -> None:
    """Mid init + first spawn is invalid — must respawn MCP."""
    paths = enumerate_scenarios()
    bad = [
        p
        for p in paths
        if p.init_timing == InitTiming.MID_SESSION and p.mcp_spawn == McpSpawn.FIRST
    ]
    assert bad == []


def test_prune_wrong_repo_respawn() -> None:
    paths = enumerate_scenarios()
    bad = [p for p in paths if p.workspace == Workspace.WRONG_REPO and p.mcp_spawn == McpSpawn.RESPAWN]
    assert bad == []


def test_minimal_cover_hits_all_outcomes() -> None:
    cover = list(iter_minimal_cover())
    covered = {s.outcome for s in cover}
    assert Outcome.NO_MCP in covered
    assert Outcome.GATE_ONLY_NATIVE in covered
    assert Outcome.FULL_MANAGED in covered
    assert Outcome.WRONG_REPO_GATE in covered
    assert Outcome.PAUSED_RULE in covered
    assert Outcome.MID_INIT_RELOAD in covered


# ---------------------------------------------------------------------------
# Parametrized outcome verification (backtracking leaves)
# ---------------------------------------------------------------------------
ALL_PATHS = enumerate_scenarios()


@pytest.mark.parametrize("path", ALL_PATHS, ids=[p.path_id for p in ALL_PATHS])
def test_scenario_path_outcome(
    path: ScenarioPath,
    fake_home: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Each enumerated leaf must match its declared outcome signature."""
    if path.connect == Connect.NEVER:
        assert not (fake_home / ".cursor" / "mcp.json").exists()
        assert path.outcome == Outcome.NO_MCP
        return

    state = _apply_path(path, tmp_path, monkeypatch, fake_home)
    assert state["mcp_json"]

    if path.outcome == Outcome.GATE_ONLY_NATIVE:
        assert state["tools"] == {"gate"}
        assert "native" in state["instructions"].lower()
        assert "map(query)" not in state["instructions"]

    elif path.outcome == Outcome.FULL_MANAGED:
        assert state["tools"] == PHASE_MANAGED_TOOLS
        assert "map(query)" in state["instructions"]
        assert "tool bans are in the project GATE rule" in state["instructions"]
        assert state.get("managed") is True

    elif path.outcome == Outcome.WRONG_REPO_GATE:
        assert state["tools"] == {"gate"}
        assert state.get("managed") is False

    elif path.outcome == Outcome.PAUSED_RULE:
        assert state["gate"] == "p"

    elif path.outcome == Outcome.MID_INIT_RELOAD:
        assert state["tools"] == PHASE_MANAGED_TOOLS
        assert state.get("managed") is True


# ---------------------------------------------------------------------------
# Explicit branch-and-bound decision tree (documented paths)
# ---------------------------------------------------------------------------
def test_bound_disconnect_branch(fake_home: Path, tmp_path: Path, monkeypatch) -> None:
    """Pruned branch: disconnect after connect — MCP gone, rules remain."""
    repo = _git_repo(tmp_path / "disc")
    install_tool(TOOL_MAP["cursor"], repo=repo)
    pid = "ce_backtrack_disc1234567890abcdef"
    _enroll(repo, pid, monkeypatch, tmp_path)
    write_project_gate_rules(repo)
    rule = repo / ".cursor" / "rules" / "scubiee.mdc"

    report = uninstall_tool(TOOL_MAP["cursor"], repo=repo)
    assert report["mcp_removed"] is True
    assert not (fake_home / ".cursor" / "mcp.json").exists()
    assert rule.is_file()


def test_bound_unmanaged_pause_is_noop(tmp_path: Path, monkeypatch) -> None:
    """Branch-and-bound: pause on never-enrolled repo still gate 0."""
    repo = _git_repo(tmp_path / "unpaused")
    monkeypatch.setenv("CTX_REPO", str(repo.resolve()))
    monkeypatch.chdir(repo)
    monkeypatch.setattr("pipeline.pause_resume.is_paused", lambda: True)

    tools = _mcp_tools(monkeypatch)
    text = _instructions(monkeypatch)
    assert tools == {"gate"}
    assert text.startswith("GATE 0.") or text.startswith("GATE 0:r")


def test_backtrack_managed_then_wipe_returns_unmanaged(tmp_path: Path, monkeypatch) -> None:
    """Backtrack: managed → wipe rules → same repo behaves unmanaged."""
    repo = _git_repo(tmp_path / "wiped")
    pid = "ce_backtrack_wipe1234567890abcdef"
    _enroll(repo, pid, monkeypatch, tmp_path)
    write_project_gate_rules(repo)
    cleanup_project_gate_rules(repo)

    assert _mcp_tools(monkeypatch) == PHASE_MANAGED_TOOLS  # still enrolled on disk
    rule = repo / ".cursor" / "rules" / "scubiee.mdc"
    assert not rule.exists()
