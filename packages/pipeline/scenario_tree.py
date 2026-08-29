"""User-journey scenario tree — backtracking enumeration with branch-and-bound pruning.

Decision axes (in order):
  1. connect     — NEVER | GLOBAL
  2. workspace   — UNMANAGED | MANAGED | WRONG_REPO
  3. init_timing — NONE | BEFORE_MCP | MID_SESSION (only UNMANAGED→enrolled)
  4. pause       — OFF | ON
  5. mcp_spawn   — FIRST | RESPAWN

Branch-and-bound: invalid / redundant branches are pruned before expanding children.
Backtracking: depth-first enumeration of all surviving paths to outcome leaves.

See docs/user-journey-scenarios.md and tests/test_scenario_backtracking.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator


class Connect(str, Enum):
    NEVER = "never"
    GLOBAL = "global"


class Workspace(str, Enum):
    UNMANAGED = "unmanaged"
    MANAGED = "managed"
    WRONG_REPO = "wrong_repo"


class InitTiming(str, Enum):
    NONE = "none"
    BEFORE_MCP = "before_mcp"
    MID_SESSION = "mid_session"


class Pause(str, Enum):
    OFF = "off"
    ON = "on"


class McpSpawn(str, Enum):
    FIRST = "first"
    RESPAWN = "respawn"


class Outcome(str, Enum):
    NO_MCP = "no_mcp"
    GATE_ONLY_NATIVE = "gate_only_native"
    FULL_MANAGED = "full_managed"
    WRONG_REPO_GATE = "wrong_repo_gate"
    PAUSED_RULE = "paused_rule"
    MID_INIT_RELOAD = "mid_init_reload"
    DISCONNECTED = "disconnected"
    RULES_ONLY_ON_INIT = "rules_only_on_init"


@dataclass(frozen=True)
class ScenarioPath:
    """One complete user journey from root to leaf."""

    connect: Connect
    workspace: Workspace
    init_timing: InitTiming
    pause: Pause
    mcp_spawn: McpSpawn
    outcome: Outcome
    path_id: str = ""
    notes: str = ""

    def choices(self) -> tuple[str, ...]:
        return (
            self.connect.value,
            self.workspace.value,
            self.init_timing.value,
            self.pause.value,
            self.mcp_spawn.value,
        )


@dataclass
class _Partial:
    connect: Connect | None = None
    workspace: Workspace | None = None
    init_timing: InitTiming = InitTiming.NONE
    pause: Pause = Pause.OFF
    mcp_spawn: McpSpawn | None = None


def _should_prune(p: _Partial) -> bool:
    """Branch-and-bound: return True to cut this branch (invalid or duplicate)."""
    # No MCP behavior without global connect (except never-connect leaf handled separately)
    if p.connect == Connect.NEVER:
        if p.workspace is not None or p.init_timing != InitTiming.NONE:
            return True
        if p.pause == Pause.ON or p.mcp_spawn is not None:
            return True
        return False  # leaf: never connected

    if p.connect != Connect.GLOBAL:
        return False

    if p.workspace is None:
        return p.init_timing != InitTiming.NONE or p.pause == Pause.ON or p.mcp_spawn is not None

    # Managed workspace: init is implicit (before_mcp only)
    if p.workspace == Workspace.MANAGED:
        if p.init_timing == InitTiming.MID_SESSION:
            return True
        if p.init_timing == InitTiming.NONE:
            return True  # managed implies init before open

    # Unmanaged: no init before, optional mid_session
    if p.workspace == Workspace.UNMANAGED:
        if p.init_timing == InitTiming.BEFORE_MCP:
            return True

    # Wrong repo: init on A implied; no mid_session on B
    if p.workspace == Workspace.WRONG_REPO:
        if p.init_timing != InitTiming.NONE:
            return True

    # Pause only meaningful when repo has enrollment (managed or mid_session)
    if p.pause == Pause.ON:
        if p.workspace == Workspace.UNMANAGED and p.init_timing != InitTiming.MID_SESSION:
            if p.mcp_spawn is None:
                pass  # allow pause+unmanaged? gate 0 still — prune pause as no-op
            return p.workspace == Workspace.UNMANAGED and p.init_timing == InitTiming.NONE

    # Respawn only after enrollment path exists
    if p.mcp_spawn == McpSpawn.RESPAWN:
        if p.workspace == Workspace.UNMANAGED and p.init_timing != InitTiming.MID_SESSION:
            return True
        if p.workspace == Workspace.WRONG_REPO:
            return True

    # First spawn + mid_session init is the stale-MCP case (disk updates, tools after respawn)
    if p.mcp_spawn == McpSpawn.FIRST and p.init_timing == InitTiming.MID_SESSION:
        return True  # mid init requires respawn to get full tools — separate leaf

    return False


def _outcome_for(p: _Partial) -> Outcome | None:
    if p.connect == Connect.NEVER:
        return Outcome.NO_MCP

    if p.workspace is None or p.mcp_spawn is None:
        return None

    if p.pause == Pause.ON and p.workspace == Workspace.MANAGED:
        return Outcome.PAUSED_RULE

    if p.workspace == Workspace.WRONG_REPO:
        return Outcome.WRONG_REPO_GATE

    if p.workspace == Workspace.UNMANAGED and p.init_timing == InitTiming.NONE:
        return Outcome.GATE_ONLY_NATIVE

    if p.workspace == Workspace.UNMANAGED and p.init_timing == InitTiming.MID_SESSION:
        if p.mcp_spawn == McpSpawn.RESPAWN:
            return Outcome.MID_INIT_RELOAD
        return None

    if p.workspace == Workspace.MANAGED:
        if p.mcp_spawn == McpSpawn.FIRST:
            return Outcome.FULL_MANAGED
        if p.mcp_spawn == McpSpawn.RESPAWN:
            return Outcome.FULL_MANAGED  # same outcome, different path

    return None


def _path_id(p: _Partial, outcome: Outcome) -> str:
    parts = [
        p.connect.value if p.connect else "?",
        p.workspace.value if p.workspace else "-",
        p.init_timing.value,
        p.pause.value,
        p.mcp_spawn.value if p.mcp_spawn else "-",
        outcome.value,
    ]
    return "/".join(parts)


def _notes_for(p: _Partial, outcome: Outcome) -> str:
    notes = {
        Outcome.NO_MCP: "S1: setup only, never connect",
        Outcome.GATE_ONLY_NATIVE: "S3: global connect, open clone without init",
        Outcome.FULL_MANAGED: "S4: connect + init + open managed repo",
        Outcome.WRONG_REPO_GATE: "S5/S14: init A, IDE opens B",
        Outcome.PAUSED_RULE: "S8/S16: scubiee pause on managed repo",
        Outcome.MID_INIT_RELOAD: "S20: init mid-session, MCP respawn",
        Outcome.DISCONNECTED: "S10: disconnect removes global MCP",
        Outcome.RULES_ONLY_ON_INIT: "S6/S13: bans in rule, trajectory in MCP",
    }
    base = notes.get(outcome, "")
    if p.mcp_spawn == McpSpawn.RESPAWN and outcome == Outcome.FULL_MANAGED:
        return base + " (respawn path)"
    return base


def _backtrack(p: _Partial, depth: int, results: list[ScenarioPath]) -> None:
    if _should_prune(p):
        return

    if depth == 0:
        for c in Connect:
            _backtrack(_Partial(connect=c), 1, results)
        return

    if depth == 1:
        if p.connect == Connect.NEVER:
            results.append(
                ScenarioPath(
                    connect=Connect.NEVER,
                    workspace=Workspace.UNMANAGED,
                    init_timing=InitTiming.NONE,
                    pause=Pause.OFF,
                    mcp_spawn=McpSpawn.FIRST,
                    outcome=Outcome.NO_MCP,
                    path_id="never",
                    notes=_notes_for(p, Outcome.NO_MCP),
                )
            )
            return
        for w in Workspace:
            np = _Partial(
                connect=p.connect,
                workspace=w,
                init_timing=InitTiming.BEFORE_MCP if w == Workspace.MANAGED else InitTiming.NONE,
            )
            _backtrack(np, 2, results)
        return

    if depth == 2:
        # Optional mid_session branch for unmanaged only
        if p.workspace == Workspace.UNMANAGED:
            for timing in (InitTiming.NONE, InitTiming.MID_SESSION):
                np = _Partial(
                    connect=p.connect,
                    workspace=p.workspace,
                    init_timing=timing,
                )
                _backtrack(np, 3, results)
        else:
            _backtrack(p, 3, results)
        return

    if depth == 3:
        for pause in Pause:
            np = _Partial(
                connect=p.connect,
                workspace=p.workspace,
                init_timing=p.init_timing,
                pause=pause,
            )
            _backtrack(np, 4, results)
        return

    if depth == 4:
        for spawn in McpSpawn:
            np = _Partial(
                connect=p.connect,
                workspace=p.workspace,
                init_timing=p.init_timing,
                pause=p.pause,
                mcp_spawn=spawn,
            )
            if _should_prune(np):
                continue
            outcome = _outcome_for(np)
            if outcome is None:
                continue
            results.append(
                ScenarioPath(
                    connect=np.connect,  # type: ignore[arg-type]
                    workspace=np.workspace,  # type: ignore[arg-type]
                    init_timing=np.init_timing,
                    pause=np.pause,
                    mcp_spawn=np.mcp_spawn,  # type: ignore[arg-type]
                    outcome=outcome,
                    path_id=_path_id(np, outcome),
                    notes=_notes_for(np, outcome),
                )
            )
        return


def enumerate_scenarios() -> list[ScenarioPath]:
    """Backtracking DFS over the decision tree; returns all non-pruned leaves."""
    results: list[ScenarioPath] = []
    _backtrack(_Partial(), 0, results)
    # Deduplicate identical outcomes with same choices
    seen: set[tuple[str, ...]] = set()
    unique: list[ScenarioPath] = []
    for s in results:
        key = s.choices() + (s.outcome.value,)
        if key in seen:
            continue
        seen.add(key)
        unique.append(s)
    return sorted(unique, key=lambda s: s.path_id)


def scenarios_by_outcome() -> dict[Outcome, list[ScenarioPath]]:
    out: dict[Outcome, list[ScenarioPath]] = {}
    for s in enumerate_scenarios():
        out.setdefault(s.outcome, []).append(s)
    return out


def iter_minimal_cover() -> Iterator[ScenarioPath]:
    """One representative path per outcome (branch-and-bound cover set)."""
    by = scenarios_by_outcome()
    for outcome in Outcome:
        paths = by.get(outcome)
        if paths:
            yield paths[0]
