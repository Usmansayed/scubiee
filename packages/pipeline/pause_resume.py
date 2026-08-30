"""Global stop/resume for Scubiee (`scubiee stop` / `scubiee resume`).

``scubiee stop`` — kill processes, remove Scubiee MCP keys + GATE rules +
repo ``.scubiee`` folders. Registry + index stores in ``~/.scubiee`` are kept
so ``scubiee resume`` can reconnect without re-indexing.

**MCP:** edit ``mcp.json`` in place — add/remove only the ``scubiee`` key;
never delete the user's other MCP servers.

**Rules:** delete only Scubiee-owned files (``scubiee.mdc``, etc.) or the
marked section in ``AGENTS.md``; other rules in ``.cursor/rules/`` are kept.

**Repo data:** only ``<repo>/.scubiee/`` is removed (Scubiee-owned).

While stopped:
- No Scubiee MCP, rules, or repo ``.scubiee`` on disk.
- CLI action commands are blocked (except ``resume`` and read-only diagnostics).
- MCP tools return ``paused: true`` if a stale session is still loaded.
"""

from __future__ import annotations

import json
import shutil
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

PAUSED_BLOCK_MESSAGE = "Scubiee is stopped. Run `scubiee resume` to use commands."

# ── State file ────────────────────────────────────────────────────────────────

def _state_path() -> Path:
    from pipeline.project_id import context_engine_home

    return context_engine_home() / "pause_state.json"


def is_paused() -> bool:
    """Return True if Scubiee is globally stopped.

    Fail-closed: corrupt ``pause_state.json`` is treated as stopped.
    """
    path = _state_path()
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return bool(data.get("paused"))
    except (json.JSONDecodeError, OSError):
        return True


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


# paused_blocks_command lives in lifecycle_guard.py (re-exported below).

# ── MCP disable/enable (legacy helpers — tests only) ─────────────────────────

def _disable_mcp_json(path: Path, key: str) -> bool:
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


_PAUSED_SUFFIX = ".paused"  # legacy — resume cleans up if present


def _registry_project_id_for_repo(repo: Path) -> str | None:
    from pipeline.project_id import load_registry

    try:
        repo_key = str(repo.resolve()).replace("\\", "/").lower()
    except OSError:
        return None
    for pid, entry in (load_registry().get("projects") or {}).items():
        if not isinstance(entry, dict) or not isinstance(pid, str):
            continue
        if not pid.startswith("ce_"):
            continue
        for raw in list(entry.get("paths") or []) + ([entry.get("root")] if entry.get("root") else []):
            try:
                candidate = str(Path(str(raw)).resolve()).replace("\\", "/").lower()
            except OSError:
                continue
            if candidate == repo_key:
                return pid
    return None


def _hide_repo_scubiee_dirs() -> list[str]:
    """Remove repo-local ``.scubiee`` dirs; keep registry + home index stores."""
    from pipeline.managed_repos import managed_repo_paths
    from pipeline.project_id import id_dir_path

    removed: list[str] = []
    for repo in managed_repo_paths(enrolled_only=False):
        id_dir = id_dir_path(repo)
        if not id_dir.is_dir():
            continue
        try:
            shutil.rmtree(id_dir)
            removed.append(str(id_dir))
        except OSError as exc:
            removed.append(f"{id_dir} (error: {exc})")
    return removed


def _restore_enrolled_id_files() -> list[str]:
    from pipeline.managed_repos import managed_repo_paths
    from pipeline.project_id import read_id_file, write_id_file

    restored: list[str] = []
    for repo in managed_repo_paths(enrolled_only=False):
        if read_id_file(repo):
            continue
        pid = _registry_project_id_for_repo(repo)
        if not pid:
            continue
        try:
            write_id_file(repo, pid)
            restored.append(str(repo))
        except OSError:
            continue
    return restored


def _strip_agents_md_all_repos() -> list[str]:
    from pipeline.managed_repos import managed_repo_paths
    from pipeline.rules_installer import _remove_rule_section

    stripped: list[str] = []
    for repo in managed_repo_paths(enrolled_only=False):
        agents = repo / "AGENTS.md"
        if agents.is_file():
            try:
                if _remove_rule_section(agents):
                    stripped.append(str(agents))
            except OSError:
                pass
    return stripped


def _teardown_tool_surfaces(tool: ToolDef) -> dict[str, Any]:
    """Remove Scubiee MCP keys + GATE rules for one tool (does not touch connect_state)."""
    from pipeline.rules_installer import (
        _RULE_REMOVERS,
        _remove_legacy_global_mcp,
        fan_out_tool_to_enrolled_repos,
    )

    mcp_skipped: list[dict[str, str]] = []
    report: dict[str, Any] = {
        "slug": tool.slug,
        "legacy_global_removed": _remove_legacy_global_mcp(tool, warnings=mcp_skipped),
    }
    fan = fan_out_tool_to_enrolled_repos(
        tool, remove=True, dry_run=False, mcp_warnings=mcp_skipped
    )
    report["project_fan_out"] = fan
    if mcp_skipped:
        report["mcp_skipped"] = mcp_skipped

    user_removed: list[str] = []
    remover = _RULE_REMOVERS.get(tool.rule_format)
    if remover and tool.rule_format != "none":
        for path in resolve_rule_user_paths(tool):
            if path.is_file() and remover(path):
                user_removed.append(str(path))
    report["user_rules_removed"] = user_removed
    return report


def _collect_teardown_mcp_skipped(teardown: list[dict[str, Any]]) -> list[dict[str, str]]:
    skipped: list[dict[str, str]] = []
    for entry in teardown:
        skipped.extend(entry.get("mcp_skipped") or [])
        fan = entry.get("project_fan_out") or {}
        for sub in fan.get("reports") or []:
            skipped.extend(sub.get("mcp_skipped") or [])
    return skipped


def _teardown_all_tool_surfaces() -> list[dict[str, Any]]:
    """Stop cleanup for every supported IDE/agent — not only connected slugs."""
    return [_teardown_tool_surfaces(tool) for tool in TOOL_MAP.values()]


def _cleanup_legacy_paused_rules(tool: ToolDef) -> list[str]:
    """Remove leftover ``*.paused`` rule files from older stop implementations."""
    cleaned: list[str] = []
    candidates: list[Path] = list(resolve_rule_user_paths(tool))
    from pipeline.managed_repos import managed_repo_paths

    for repo in managed_repo_paths(enrolled_only=False):
        candidates.extend(resolve_rule_project_paths(tool, repo))

    seen: set[str] = set()
    for rule_path in candidates:
        paused_path = rule_path.with_name(rule_path.name + _PAUSED_SUFFIX)
        key = str(paused_path).replace("\\", "/").lower()
        if key in seen or not paused_path.is_file():
            continue
        seen.add(key)
        try:
            paused_path.unlink()
            cleaned.append(str(paused_path))
        except OSError:
            pass
        marker = rule_path.parent / "scubiee-stopped.mdc"
        if marker.is_file():
            try:
                marker.unlink()
                cleaned.append(str(marker))
            except OSError:
                pass
    return cleaned


def _detect_connected_tools() -> list[str]:
    from pipeline.connect_state import load_connected_tools

    return load_connected_tools()


# ── Core pause/resume ─────────────────────────────────────────────────────────

def pause() -> dict[str, Any]:
    """Globally stop Scubiee — tear down MCP, rules, repo .scubiee."""
    if is_paused():
        return {"ok": True, "already_paused": True}

    report: dict[str, Any] = {"ok": True, "paused_at": time.time()}

    connected = _detect_connected_tools()
    report["connected_tools"] = connected

    try:
        from pipeline.process_control import release_scubiee_process_locks

        report["process_release"] = release_scubiee_process_locks()
        if not report["process_release"].get("ok"):
            report["process_warning"] = report["process_release"].get("hint")
    except Exception as exc:  # noqa: BLE001
        report["stop_error"] = str(exc)

    teardown: list[dict[str, Any]] = _teardown_all_tool_surfaces()
    report["teardown"] = teardown
    mcp_skipped = _collect_teardown_mcp_skipped(teardown)
    if mcp_skipped:
        report["mcp_skipped"] = mcp_skipped
        report["mcp_skip_warning"] = (
            f"{len(mcp_skipped)} MCP file(s) could not be updated "
            "(invalid syntax — scubiee entry may remain; fix manually)"
        )
    report["agents_stripped"] = _strip_agents_md_all_repos()

    report["hidden_scubiee_dirs"] = _hide_repo_scubiee_dirs()

    _save_state({
        "paused": True,
        "paused_at": report["paused_at"],
        "connected_tools": connected,
        "teardown": teardown,
        "hidden_scubiee_dirs": report["hidden_scubiee_dirs"],
    })

    return report


def resume() -> dict[str, Any]:
    """Restore MCP, rules, repo id files, and engine after ``scubiee stop``."""
    if not is_paused():
        return {"ok": True, "already_active": True}

    state = _load_state()
    connected = list(state.get("connected_tools") or _detect_connected_tools())
    report: dict[str, Any] = {"ok": True, "resumed_at": time.time()}

    # Stay paused until MCP restore succeeds — never leave a half-resumed state.
    _save_state({
        "paused": True,
        "resuming": True,
        "paused_at": state.get("paused_at"),
        "connected_tools": connected,
    })

    report["restored_id_files"] = _restore_enrolled_id_files()

    restored: list[dict[str, Any]] = []
    restore_errors: list[str] = []
    for slug in connected:
        tool = TOOL_MAP.get(slug)
        if not tool:
            continue
        _cleanup_legacy_paused_rules(tool)
        from pipeline.rules_installer import install_tool

        result = install_tool(tool)
        restored.append(result)
        if not result.get("ok", True):
            restore_errors.extend(result.get("errors") or [f"{slug}: MCP restore failed"])

    report["connect_restore"] = restored

    if restore_errors:
        report["ok"] = False
        report["errors"] = restore_errors
        report["hint"] = (
            "MCP restore failed — Scubiee is still stopped. "
            "Fix the errors above and run `scubiee resume` again."
        )
        _save_state({
            "paused": True,
            "resuming": False,
            "paused_at": state.get("paused_at"),
            "connected_tools": connected,
            "last_resume_error": restore_errors,
        })
        return report

    try:
        from pipeline.lifecycle_runtime import DESIRED_RUN, set_desired_mode

        set_desired_mode(DESIRED_RUN)
    except Exception as exc:  # noqa: BLE001
        report["lifecycle_error"] = str(exc)

    try:
        from pipeline.daemon import ensure_daemon
        from pipeline.project_id import load_registry

        repo = None
        registry = load_registry()
        for entry in (registry.get("projects") or {}).values():
            if isinstance(entry, dict) and entry.get("managed"):
                paths = entry.get("paths") or []
                if paths:
                    from pathlib import Path as _Path

                    candidate = _Path(str(paths[0]))
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

    if not connected:
        report["connect_hint"] = (
            "No tools were connected before stop — run "
            "`scubiee connect --cursor` (or your IDE) after resume."
        )

    _save_state({"paused": False, "resumed_at": report["resumed_at"]})

    return report


# ── Back-compat aliases for tests ─────────────────────────────────────────────

def _pause_rule_files(tool: ToolDef) -> list[str]:
    """Legacy — stop now deletes surfaces instead of renaming."""
    report = _teardown_tool_surfaces(tool)
    removed: list[str] = []
    fan = report.get("project_fan_out") or {}
    for sub in fan.get("reports") or []:
        rules = sub.get("rules") or {}
        removed.extend(rules.get("removed") or [])
    removed.extend(report.get("user_rules_removed") or [])
    return removed


def _resume_rule_files(tool: ToolDef) -> list[str]:
    """Legacy — resume reconnects via install_tool."""
    from pipeline.rules_installer import install_tool

    install_tool(tool)
    return []


def _disable_mcp_for_tool(tool: ToolDef) -> list[str]:
    from pipeline.rules_installer import _remove_legacy_global_mcp, fan_out_tool_to_enrolled_repos

    removed = list(_remove_legacy_global_mcp(tool))
    fan = fan_out_tool_to_enrolled_repos(tool, remove=True, dry_run=False)
    for sub in fan.get("reports") or []:
        if sub.get("mcp_removed"):
            removed.append(str(sub.get("repo") or tool.slug))
    return removed


def _enable_mcp_for_tool(tool: ToolDef) -> list[str]:
    from pipeline.rules_installer import install_tool

    report = install_tool(tool)
    enabled: list[str] = []
    for path in report.get("mcp_paths") or []:
        enabled.append(str(path))
    fan = report.get("project_fan_out") or {}
    for sub in fan.get("reports") or []:
        for p in sub.get("mcp_paths") or []:
            enabled.append(str(p))
    return enabled
