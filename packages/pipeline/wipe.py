"""Complete removal of all Scubiee data from this machine.

Usage:
    scubiee wipe --confirm              # engine data only (indexes, logs, accel)
    scubiee wipe --confirm --all        # EVERYTHING: engine + models + tool configs + repo markers
    scubiee wipe --confirm --models     # engine data + embedding model cache
    scubiee wipe --confirm --tools      # engine data + disconnect from all AI tools
    scubiee wipe --confirm --repos      # engine data + per-repo .context-engine/ dirs
    scubiee wipe --dry-run --all        # preview what would be deleted

Does NOT remove the Python package itself (use: pip uninstall scubiee).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any


def _rmtree_force(path: Path, retries: int = 3, delay: float = 2.0) -> None:
    """Remove a directory tree, force-killing any processes holding files open on Windows."""
    for attempt in range(retries):
        try:
            shutil.rmtree(path)
            return
        except PermissionError:
            if attempt == retries - 1:
                raise
            _kill_ce_processes()
            time.sleep(delay)


def _kill_ce_processes() -> None:
    """Force-kill any running scubiee engine/watchdog processes."""
    try:
        import psutil
    except ImportError:
        return
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            cmd_str = " ".join(cmdline).lower()
            if "pipeline" in cmd_str and ("engine" in cmd_str or "watchdog" in cmd_str):
                proc.kill()
                proc.wait(timeout=5)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
            pass


def _is_safe_to_wipe(path: Path) -> bool:
    """Refuse to wipe system directories or paths that aren't a CE home."""
    resolved = path.resolve()
    resolved_str = str(resolved)

    _DANGEROUS = {
        "/", "/tmp", "/var", "/home", "/usr", "/etc", "/opt",
        "/bin", "/sbin", "/lib", "/dev", "/proc", "/sys",
        str(Path.home()),
    }
    if resolved_str in _DANGEROUS:
        return False
    if len(resolved.parts) <= 2:
        return False
    if resolved.name == ".context-engine":
        return True
    if (resolved / "registry.json").exists():
        return True
    if (resolved / "accel.json").exists():
        return True
    if not resolved.exists():
        return True
    return False


def _find_model_cache_dirs() -> list[Path]:
    """Find Scubiee-related model cache directories."""
    dirs: list[Path] = []

    # fastembed cache (stores ONNX models)
    fastembed_cache = Path.home() / ".cache" / "fastembed"
    if fastembed_cache.is_dir():
        # Look for CodeRankEmbed specifically
        for child in fastembed_cache.iterdir():
            if child.is_dir() and "coderank" in child.name.lower():
                dirs.append(child)
        # If no specific match, flag the whole fastembed cache
        if not dirs and fastembed_cache.is_dir():
            dirs.append(fastembed_cache)

    # huggingface hub cache for CodeRankEmbed
    hf_cache = Path(os.environ.get("HF_HOME", "")) or Path.home() / ".cache" / "huggingface"
    hf_hub = hf_cache / "hub"
    if hf_hub.is_dir():
        for child in hf_hub.iterdir():
            if child.is_dir() and "coderank" in child.name.lower():
                dirs.append(child)

    # MLX converted weights (inside CE home, but also check standalone)
    mlx_dir = Path.home() / ".context-engine" / "mlx"
    if mlx_dir.is_dir():
        dirs.append(mlx_dir)

    return dirs


def wipe_context_engine(
    *,
    confirm: bool = False,
    include_all: bool = False,
    include_repos: bool = False,
    include_mcp: bool = False,
    include_models: bool = False,
    include_tools: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Remove Scubiee data from this machine.

    --all expands to: repos + tools (disconnect) + models + mcp configs.
    """
    from pipeline.project_id import context_engine_home, load_registry

    # --all enables everything
    if include_all:
        include_repos = True
        include_mcp = True
        include_models = True
        include_tools = True

    ce_home = context_engine_home()

    if not confirm:
        return {
            "ok": False,
            "error": "confirmation_required",
            "message": "Pass --confirm to proceed. This permanently deletes all Scubiee data.",
            "hint": "Use --all to remove everything, or --dry-run to preview.",
            "ce_home": str(ce_home),
            "exists": ce_home.exists(),
        }

    if not _is_safe_to_wipe(ce_home):
        return {
            "ok": False,
            "error": "unsafe_path",
            "message": f"Refusing to wipe '{ce_home}' — does not look like a Scubiee home directory.",
            "ce_home": str(ce_home),
        }

    result: dict[str, Any] = {
        "ok": True,
        "ce_home": str(ce_home),
        "dry_run": dry_run,
        "daemon_stopped": False,
        "ce_home_deleted": False,
        "repo_dirs_cleaned": [],
        "tools_disconnected": [],
        "mcp_configs_cleaned": [],
        "models_cleaned": [],
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

    # 3. Disconnect from all AI tools (remove MCP configs + rule files)
    if include_tools:
        try:
            from pipeline.rules_installer import uninstall_tools
            from pipeline.tool_registry import ALL_SLUGS

            reports = uninstall_tools(ALL_SLUGS, dry_run=dry_run)
            for r in reports:
                if r.get("mcp_removed") or r.get("rule_removed"):
                    result["tools_disconnected"].append(r["slug"])
        except Exception as exc:  # noqa: BLE001
            result["tools_disconnect_error"] = str(exc)

    # 4. Delete ~/.context-engine/
    if ce_home.exists():
        if not dry_run:
            _rmtree_force(ce_home)
        result["ce_home_deleted"] = True

    # 5. Remove per-repo .context-engine/ dirs
    if include_repos:
        for repo in repo_paths:
            ce_dir = repo / ".context-engine"
            if ce_dir.is_dir():
                if not dry_run:
                    shutil.rmtree(ce_dir, ignore_errors=True)
                result["repo_dirs_cleaned"].append(str(ce_dir))

    # 6. Remove MCP config entries (legacy path — covered by --tools but kept for compat)
    if include_mcp and not include_tools:
        mcp_paths = _find_mcp_configs()
        for mcp_path in mcp_paths:
            removed = _remove_ce_from_mcp_json(mcp_path, dry_run=dry_run)
            if removed:
                result["mcp_configs_cleaned"].append(str(mcp_path))

    # 7. Remove cached embedding models
    if include_models:
        model_dirs = _find_model_cache_dirs()
        for model_dir in model_dirs:
            if model_dir.is_dir():
                if not dry_run:
                    shutil.rmtree(model_dir, ignore_errors=True)
                result["models_cleaned"].append(str(model_dir))

    return result


def _find_mcp_configs() -> list[Path]:
    """Find known MCP config files that may reference context-engine."""
    candidates: list[Path] = []
    home = Path.home()

    cursor_user = home / ".cursor" / "mcp.json"
    if cursor_user.exists():
        candidates.append(cursor_user)

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
