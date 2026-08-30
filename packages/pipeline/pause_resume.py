"""Global pause/resume for Scubiee.

scubiee pause  — stop all processes, disable MCP configs, rename rules, save state.
scubiee resume — restore MCP configs, rename rules back, start engine, reconcile.

While paused:
- No background CPU/memory/disk usage.
- MCP server entries are disabled (agents won't attempt to connect).
- Rule files are renamed to *.paused (invisible to IDE agent loaders).
- status() MCP call returns {"ok": false, "paused": true} so agents skip Scubiee.
- Watchdog/lifecycle_runtime refuse to restart anything.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pipeline.branding import MCP_SERVER_NAMES
from pipeline.tool_registry import (
    TOOL_MAP,
    ToolDef,
    resolve_mcp_legacy_global_paths,
    resolve_mcp_project_write_targets,
    resolve_rule_project_paths,
    resolve_rule_user_paths,
)


# ── State file ────────────────────────────────────────────────────────────────

def _state_path() -> Path:
    from pipeline.project_id import context_engine_home

    return context_engine_home() / "pause_state.json"


def is_paused() -> bool:
    """Return True if Scubiee is globally paused."""
    path = _state_path()
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return bool(data.get("paused"))
    except (json.JSONDecodeError, OSError):
        return False


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(data: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ── MCP disable/enable ────────────────────────────────────────────────────────

def _disable_mcp_json(path: Path, key: str) -> bool:
    """Set disabled=true on every known Scubiee MCP server key."""
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    servers = data.get(key)
    if not isinstance(servers, dict):
        return False
    changed = False
    for name in MCP_SERVER_NAMES:
        if name not in servers:
            continue
        entry = servers[name]
        if isinstance(entry, dict):
            entry["disabled"] = True
            servers[name] = entry
            changed = True
    if not changed:
        return False
    data[key] = servers
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def _enable_mcp_json(path: Path, key: str) -> bool:
    """Clear disabled on Scubiee MCP keys."""
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    servers = data.get(key)
    if not isinstance(servers, dict):
        return False
    changed = False
    for name in MCP_SERVER_NAMES:
        if name not in servers:
            continue
        entry = servers[name]
        if isinstance(entry, dict):
            entry.pop("disabled", None)
            servers[name] = entry
            changed = True
    if not changed:
        return False
    data[key] = servers
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def _disable_mcp_opencode(path: Path) -> bool:
    """OpenCode uses enabled: false."""
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    mcp = data.get("mcp")
    if not isinstance(mcp, dict):
        return False
    changed = False
    for name in MCP_SERVER_NAMES:
        if name not in mcp:
            continue
        entry = mcp[name]
        if isinstance(entry, dict):
            entry["enabled"] = False
            mcp[name] = entry
            changed = True
    if not changed:
        return False
    data["mcp"] = mcp
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def _enable_mcp_opencode(path: Path) -> bool:
    """OpenCode uses enabled: true."""
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    mcp = data.get("mcp")
    if not isinstance(mcp, dict):
        return False
    changed = False
    for name in MCP_SERVER_NAMES:
        if name not in mcp:
            continue
        entry = mcp[name]
        if isinstance(entry, dict):
            entry["enabled"] = True
            mcp[name] = entry
            changed = True
    if not changed:
        return False
    data["mcp"] = mcp
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def _iter_connected_mcp_paths(tool: ToolDef):
    """Yield (path, schema, key) for project MCP + legacy global cleanup paths."""
    from pipeline.managed_repos import managed_repo_paths

    for repo in managed_repo_paths(enrolled_only=False):
        for target in resolve_mcp_project_write_targets(tool, repo):
            yield target
    for target in resolve_mcp_legacy_global_paths(tool):
        yield target


def _disable_mcp_for_tool(tool: ToolDef) -> list[str]:
    """Disable MCP config entries for a single tool. Returns list of disabled paths."""
    disabled: list[str] = []
    for path, schema, key in _iter_connected_mcp_paths(tool):
        if schema == "opencode":
            if _disable_mcp_opencode(path):
                disabled.append(str(path))
        elif schema in ("codex", "continue"):
            pass
        else:
            if _disable_mcp_json(path, key):
                disabled.append(str(path))
    return disabled


def _enable_mcp_for_tool(tool: ToolDef) -> list[str]:
    """Re-enable MCP config entries for a single tool. Returns list of enabled paths."""
    enabled: list[str] = []
    for path, schema, key in _iter_connected_mcp_paths(tool):
        if schema == "opencode":
            if _enable_mcp_opencode(path):
                enabled.append(str(path))
        elif schema in ("codex", "continue"):
            pass
        else:
            if _enable_mcp_json(path, key):
                enabled.append(str(path))
    return enabled


# ── Rule rename ───────────────────────────────────────────────────────────────

_PAUSED_SUFFIX = ".paused"


def _pause_rule_files(tool: ToolDef) -> list[str]:
    """Rename rule files to *.paused. Returns list of renamed paths."""
    renamed: list[str] = []
    from pipeline.managed_repos import managed_repo_paths

    candidates: list[Path] = list(resolve_rule_user_paths(tool))
    for repo in managed_repo_paths(enrolled_only=False):
        candidates.extend(resolve_rule_project_paths(tool, repo))
        agents = repo / "AGENTS.md"
        if agents.is_file():
            candidates.append(agents)

    seen: set[str] = set()
    for rule_path in candidates:
        key = str(rule_path.resolve()).replace("\\", "/").lower()
        if key in seen:
            continue
        seen.add(key)
        if rule_path.is_file() and not rule_path.name.endswith(_PAUSED_SUFFIX):
            paused_path = rule_path.with_name(rule_path.name + _PAUSED_SUFFIX)
            rule_path.rename(paused_path)
            renamed.append(str(rule_path))
    return renamed


def _resume_rule_files(tool: ToolDef) -> list[str]:
    """Rename *.paused back to original. Returns list of restored paths."""
    restored: list[str] = []
    from pipeline.managed_repos import managed_repo_paths

    candidates: list[Path] = list(resolve_rule_user_paths(tool))
    for repo in managed_repo_paths(enrolled_only=False):
        candidates.extend(resolve_rule_project_paths(tool, repo))
        candidates.append(repo / "AGENTS.md")

    seen: set[str] = set()
    for rule_path in candidates:
        key = str(rule_path.resolve()).replace("\\", "/").lower()
        if key in seen:
            continue
        seen.add(key)
        paused_path = rule_path.with_name(rule_path.name + _PAUSED_SUFFIX)
        if not paused_path.is_file():
            continue
        if rule_path.is_file():
            paused_path.unlink(missing_ok=True)
            restored.append(str(rule_path))
            continue
        paused_path.rename(rule_path)
        restored.append(str(rule_path))
    return restored


# ── Detect connected tools ────────────────────────────────────────────────────

def _detect_connected_tools() -> list[str]:
    """Return slugs of tools the user has connected (local-first store)."""
    from pipeline.connect_state import load_connected_tools

    return load_connected_tools()


# ── Core pause/resume ─────────────────────────────────────────────────────────

def pause() -> dict[str, Any]:
    """Globally pause Scubiee. Returns a report dict."""
    if is_paused():
        return {"ok": True, "already_paused": True}

    report: dict[str, Any] = {"ok": True, "paused_at": time.time()}

    # 1. Detect which tools are connected (before we disable them)
    connected = _detect_connected_tools()
    report["connected_tools"] = connected

    # 2. Stop all processes
    try:
        from pipeline.daemon import stop_daemon
        from pipeline.lifecycle_runtime import DESIRED_STANDBY, set_desired_mode
        from pipeline.watchdog import stop_watchdog

        set_desired_mode(DESIRED_STANDBY)
        report["watchdog"] = stop_watchdog()
        report["engine"] = stop_daemon()
    except Exception as exc:  # noqa: BLE001
        report["stop_error"] = str(exc)

    # 3. Disable MCP configs for connected tools
    disabled_mcp: list[str] = []
    for slug in connected:
        tool = TOOL_MAP.get(slug)
        if tool:
            disabled_mcp.extend(_disable_mcp_for_tool(tool))
    report["disabled_mcp"] = disabled_mcp

    # 4. Rename rule files
    renamed_rules: list[str] = []
    for slug in connected:
        tool = TOOL_MAP.get(slug)
        if tool:
            renamed_rules.extend(_pause_rule_files(tool))
    report["renamed_rules"] = renamed_rules

    # 5. Save state
    _save_state({
        "paused": True,
        "paused_at": report["paused_at"],
        "connected_tools": connected,
        "disabled_mcp": disabled_mcp,
        "renamed_rules": renamed_rules,
    })

    return report


def resume() -> dict[str, Any]:
    """Globally resume Scubiee. Returns a report dict."""
    if not is_paused():
        return {"ok": True, "already_active": True}

    state = _load_state()
    connected = state.get("connected_tools", [])
    report: dict[str, Any] = {"ok": True, "resumed_at": time.time()}

    # 1. Re-enable MCP configs
    enabled_mcp: list[str] = []
    for slug in connected:
        tool = TOOL_MAP.get(slug)
        if tool:
            enabled_mcp.extend(_enable_mcp_for_tool(tool))
    report["enabled_mcp"] = enabled_mcp

    # 2. Restore rule files
    restored_rules: list[str] = []
    for slug in connected:
        tool = TOOL_MAP.get(slug)
        if tool:
            restored_rules.extend(_resume_rule_files(tool))
    report["restored_rules"] = restored_rules

    # 3. Set lifecycle back to active and start engine + watchdog
    try:
        from pipeline.lifecycle_runtime import DESIRED_RUN, set_desired_mode

        set_desired_mode(DESIRED_RUN)
    except Exception as exc:  # noqa: BLE001
        report["lifecycle_error"] = str(exc)

    try:
        from pipeline.daemon import ensure_daemon
        from pipeline.project_id import load_registry

        # Find first managed repo to bind the daemon to
        repo = None
        registry = load_registry()
        for entry in (registry.get("projects") or {}).values():
            if isinstance(entry, dict) and entry.get("managed"):
                paths = entry.get("paths", [])
                if paths:
                    from pathlib import Path
                    candidate = Path(str(paths[0]))
                    if candidate.exists():
                        repo = candidate
                        break
        if repo is None:
            report["engine"] = {
                "ok": False,
                "skipped": True,
                "reason": "no_managed_repos",
                "hint": "run `scubiee init .` in a project before resuming engine",
            }
        else:
            report["engine"] = ensure_daemon(repo)
    except Exception as exc:  # noqa: BLE001
        report["engine_error"] = str(exc)

    try:
        from pipeline.watchdog import start_watchdog

        report["watchdog"] = start_watchdog()
    except Exception as exc:  # noqa: BLE001
        report["watchdog_error"] = str(exc)

    # 4. Reconcile dirty files (merkle diff since pause)
    reconciled = 0
    try:
        from pipeline.daemon import reconcile_managed_repositories

        recon = reconcile_managed_repositories(reason="resume_after_pause")
        reconciled = recon.get("reconciled", 0)
        report["reconciled"] = recon
    except Exception as exc:  # noqa: BLE001
        report["reconcile_error"] = str(exc)

    report["files_reconciled"] = reconciled
    report["connected_tools"] = connected

    # 5. Clear pause state
    _save_state({"paused": False, "resumed_at": report["resumed_at"]})

    return report
