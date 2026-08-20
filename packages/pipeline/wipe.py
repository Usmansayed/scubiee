"""Complete removal of all Context Engine data from this machine.

ctx wipe --confirm removes:
  - The running daemon + watchdog
  - ~/.context-engine/ (registry, projects, vectordb, accel, logs, locks)

Does NOT remove:
  - The installed Python package (user must pip uninstall scubiee)
  - Per-repo .context-engine/id.json files (harmless; use --include-repos to remove)
  - MCP json entries in IDE configs (use --include-mcp to remove)
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any


def _is_safe_to_wipe(path: Path) -> bool:
    """Refuse to wipe system directories or paths that aren't a CE home."""
    resolved = path.resolve()
    resolved_str = str(resolved)

    # Never wipe root-level system directories
    _DANGEROUS = {
        "/", "/tmp", "/var", "/home", "/usr", "/etc", "/opt",
        "/bin", "/sbin", "/lib", "/dev", "/proc", "/sys",
        str(Path.home()),  # Never wipe the entire home directory
    }
    if resolved_str in _DANGEROUS:
        return False

    # Must be at least 3 path components deep (e.g. /Users/x/.context-engine)
    if len(resolved.parts) <= 2:
        return False

    # Should look like a CE home (has registry.json or accel.json, or the dir name is .context-engine)
    if resolved.name == ".context-engine":
        return True
    if (resolved / "registry.json").exists():
        return True
    if (resolved / "accel.json").exists():
        return True

    # Non-existent path is safe to "wipe" (no-op)
    if not resolved.exists():
        return True

    return False


def wipe_context_engine(
    *,
    confirm: bool = False,
    include_repos: bool = False,
    include_mcp: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Remove all Context Engine state from this machine.

    Returns a result dict describing what was (or would be) deleted.
    """
    from pipeline.project_id import context_engine_home, load_registry

    ce_home = context_engine_home()

    if not confirm:
        return {
            "ok": False,
            "error": "confirmation_required",
            "message": "Pass --confirm to proceed. This permanently deletes all CE data.",
            "ce_home": str(ce_home),
            "exists": ce_home.exists(),
        }

    # Safety: refuse to wipe dangerous system paths
    if not _is_safe_to_wipe(ce_home):
        return {
            "ok": False,
            "error": "unsafe_path",
            "message": f"Refusing to wipe '{ce_home}' — does not look like a Context Engine home directory.",
            "ce_home": str(ce_home),
        }

    result: dict[str, Any] = {
        "ok": True,
        "ce_home": str(ce_home),
        "dry_run": dry_run,
        "daemon_stopped": False,
        "ce_home_deleted": False,
        "repo_dirs_cleaned": [],
        "mcp_configs_cleaned": [],
    }

    # 1. Stop daemon + watchdog
    try:
        from pipeline.daemon import is_running, stop_daemon
        from pipeline.watchdog import stop_watchdog

        if is_running():
            if not dry_run:
                stop_watchdog()
                stop_daemon()
            result["daemon_stopped"] = True
    except Exception as exc:  # noqa: BLE001
        result["daemon_stop_error"] = str(exc)

    # 2. Collect repo paths before we delete registry
    repo_paths: list[Path] = []
    if include_repos and ce_home.exists():
        try:
            registry = load_registry()
            for _pid, entry in registry.get("projects", {}).items():
                if isinstance(entry, dict):
                    for p in entry.get("paths", []):
                        repo_paths.append(Path(p))
        except Exception:  # noqa: BLE001
            pass

    # 3. Delete ~/.context-engine/
    if ce_home.exists():
        if not dry_run:
            shutil.rmtree(ce_home)
        result["ce_home_deleted"] = True

    # 4. Remove per-repo .context-engine/ dirs
    if include_repos:
        for repo in repo_paths:
            ce_dir = repo / ".context-engine"
            if ce_dir.is_dir():
                if not dry_run:
                    shutil.rmtree(ce_dir)
                result["repo_dirs_cleaned"].append(str(ce_dir))

    # 5. Remove MCP config entries (best-effort)
    if include_mcp:
        mcp_paths = _find_mcp_configs()
        for mcp_path in mcp_paths:
            removed = _remove_ce_from_mcp_json(mcp_path, dry_run=dry_run)
            if removed:
                result["mcp_configs_cleaned"].append(str(mcp_path))

    return result


def _find_mcp_configs() -> list[Path]:
    """Find known MCP config files that may reference context-engine."""
    candidates: list[Path] = []
    home = Path.home()

    # Cursor configs
    cursor_user = home / ".cursor" / "mcp.json"
    if cursor_user.exists():
        candidates.append(cursor_user)

    # Kiro configs
    kiro_user = home / ".kiro" / "settings" / "mcp.json"
    if kiro_user.exists():
        candidates.append(kiro_user)

    return candidates


def _remove_ce_from_mcp_json(path: Path, *, dry_run: bool = False) -> bool:
    """Remove the context-engine entry from an MCP JSON config file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        servers = data.get("mcpServers", {})
        if "context-engine" not in servers:
            return False
        if not dry_run:
            del servers["context-engine"]
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return True
    except Exception:  # noqa: BLE001
        return False
