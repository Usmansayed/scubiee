"""Unified next-step guidance for Scubiee lifecycle edge cases.

Agents and CLI use this to answer: resume vs init vs connect vs setup?
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _machine_ready() -> bool:
    try:
        from pipeline.accel import load_accel

        return load_accel() is not None
    except Exception:  # noqa: BLE001
        return False


def _repo_enrolled(root: Path) -> bool:
    try:
        from pipeline.mcp_locate import _is_enrolled

        return _is_enrolled(root)
    except Exception:  # noqa: BLE001
        return False


def _repo_managed(root: Path) -> tuple[str | None, dict[str, Any]]:
    try:
        from pipeline.project_id import read_id_file, load_registry

        pid = read_id_file(root)
        if not pid:
            return None, {}
        entry = (load_registry().get("projects") or {}).get(pid)
        return pid, dict(entry) if isinstance(entry, dict) else {}
    except Exception:  # noqa: BLE001
        return None, {}


def _daemon_healthy() -> bool:
    try:
        from pipeline.daemon import is_running

        return is_running()
    except Exception:  # noqa: BLE001
        return False


def _tool_connected(slug: str = "cursor") -> bool:
    try:
        from pipeline.connect_state import load_connected_tools

        return slug in load_connected_tools()
    except Exception:  # noqa: BLE001
        return False


def lifecycle_snapshot(root: Path | str | None = None) -> dict[str, Any]:
    """Current machine + repo lifecycle flags for status/gate/CLI."""
    from pipeline.pause_resume import is_paused

    repo = Path(root or Path.cwd()).resolve()
    globally_paused = is_paused()
    machine_ready = _machine_ready()
    enrolled = _repo_enrolled(repo)
    project_id, entry = _repo_managed(repo)
    repo_paused = bool(entry.get("lifecycle_state") == "paused")
    daemon_ok = _daemon_healthy()
    try:
        from pipeline.connect_state import load_connected_tools

        connected_hosts = list(load_connected_tools() or [])
    except Exception:  # noqa: BLE001
        connected_hosts = []
    mcp_connected = bool(connected_hosts)
    cursor_connected = "cursor" in connected_hosts

    return {
        "globally_paused": globally_paused,
        "machine_ready": machine_ready,
        "repo_enrolled": enrolled,
        "repo_managed": bool(entry.get("managed")) if entry else enrolled,
        "repo_paused": repo_paused,
        "project_id": project_id,
        "daemon_healthy": daemon_ok,
        "mcp_connected": mcp_connected,
        "connected_hosts": connected_hosts,
        "cursor_connected": cursor_connected,
        "root": str(repo),
    }


def next_actions(
    root: Path | str | None = None,
    *,
    for_agent: bool = True,
) -> dict[str, Any]:
    """Return ordered recovery steps — first item is the primary action."""
    snap = lifecycle_snapshot(root)
    steps: list[dict[str, str]] = []
    state = "ready"

    if snap["globally_paused"]:
        state = "globally_paused"
        steps.append({
            "action": "none — Scubiee is stopped",
            "why": (
                "MCP, rules, and repo .scubiee were removed. "
                "Use the host's native file/search tools only."
            ),
        })
        steps.append({
            "action": "scubiee resume",
            "why": "Restores MCP, rules, id.json, and engine (not init).",
        })
        if for_agent:
            steps.append({
                "action": "After resume, call gate(root=<workspace>) — reload host MCP only if tools are missing",
                "why": "The MCP process usually stays up; reload only if the host disabled the server.",
            })
        return {"state": state, "steps": steps, **snap}

    if not snap["machine_ready"]:
        state = "machine_not_setup"
        steps.append({
            "action": "scubiee setup",
            "why": "No machine profile (~/.scubiee/accel.json).",
        })
        return {"state": state, "steps": steps, **snap}

    mcp_connected = bool(snap.get("mcp_connected") or snap.get("cursor_connected"))

    if not snap["repo_enrolled"]:
        state = "repo_not_enrolled"
        steps.append({
            "action": "scubiee init .",
            "why": "Repo has no .scubiee/id.json — enrollment required once per checkout.",
        })
        steps.append({
            "action": "gate(root=<workspace>) then map/focus — same chat, no host restart",
            "why": "Locate tools stay registered; bind the new project_id per call after init.",
        })
        if not mcp_connected:
            steps.append({
                "action": "scubiee connect",
                "why": "Wire MCP + GATE rules for this host if not already connected.",
            })
        return {"state": state, "steps": steps, **snap}

    if snap["repo_paused"]:
        state = "repo_paused"
        steps.append({
            "action": "scubiee activate .",
            "why": "This checkout is paused in registry (per-repo, not global stop).",
        })
        return {"state": state, "steps": steps, **snap}

    if not mcp_connected:
        state = "not_connected"
        steps.append({
            "action": "scubiee connect",
            "why": "Machine + repo ready but no host MCP pin yet (any supported IDE/CLI).",
        })
        return {"state": state, "steps": steps, **snap}

    if not snap["daemon_healthy"]:
        state = "daemon_down"
        steps.append({
            "action": "scubiee engine start",
            "why": (
                "Engine only is stopped (scubiee engine stop) — MCP/rules still wired. "
                "Not the same as scubiee stop."
            ),
        })
        if for_agent:
            steps.append({
                "action": "Or call map/focus once (auto-starts daemon)",
                "why": "ensure_daemon runs on first MCP locate call.",
            })
        return {"state": state, "steps": steps, **snap}

    steps.append({
        "action": "none",
        "why": "Ready — use map/focus/grep/glob; pass project_id from gate.",
    })
    return {"state": state, "steps": steps, **snap}


def primary_recovery_action(
    guide: dict[str, Any] | None = None,
    *,
    root: Path | str | None = None,
) -> str | None:
    """User-facing recovery command — never the agent-ban 'none' step."""
    if guide is None:
        guide = next_actions(root)
    state = str(guide.get("state") or "")
    if state == "globally_paused":
        return "scubiee resume"
    if state == "repo_paused":
        return "scubiee activate ."
    for step in guide.get("steps") or []:
        action = str(step.get("action") or "")
        if not action or action.startswith("none"):
            continue
        return action
    return None


def primary_hint(root: Path | str | None = None) -> str:
    """One-line hint for MCP errors and status()."""
    guide = next_actions(root)
    recovery = primary_recovery_action(guide)
    if not recovery:
        return "Scubiee ready."
    steps = guide.get("steps") or []
    why = ""
    for step in steps:
        if str(step.get("action") or "") == recovery:
            why = str(step.get("why") or "")
            break
    return f"{recovery}. {why}".strip()
