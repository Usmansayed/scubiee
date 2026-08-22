"""Wipe Context Engine state — repo-local or full machine (``--all``).

Normal path stays untouched: ``setup`` → ``init`` → use. Wipe is opt-in cleanup.
``wipe --all --yes`` removes home state, MCP wiring, Cursor rules, and CodeRank
model caches so a fresh install starts clean on any laptop.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


def _rm_tree(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "removed": False, "missing": True}
    try:
        if path.is_file() or path.is_symlink():
            path.unlink(missing_ok=True)
        else:
            shutil.rmtree(path, ignore_errors=False)
        return {"path": str(path), "removed": True}
    except Exception as exc:  # noqa: BLE001
        # Best-effort: still try ignore_errors for stubborn Windows locks.
        try:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        still = path.exists()
        return {
            "path": str(path),
            "removed": not still,
            "error": str(exc),
        }


def _drop_mcp_server(path: Path, *, name: str = "context-engine") -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "removed": False, "missing": True}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"path": str(path), "removed": False, "error": str(exc)}
    if not isinstance(data, dict):
        return {"path": str(path), "removed": False, "error": "not_object"}
    servers = data.get("mcpServers")
    if not isinstance(servers, dict) or name not in servers:
        return {"path": str(path), "removed": False, "absent": True}
    servers.pop(name, None)
    try:
        if servers:
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        else:
            # Empty mcpServers — leave a clean stub so Cursor stays happy.
            path.write_text(
                json.dumps({"mcpServers": {}}, indent=2) + "\n", encoding="utf-8"
            )
        return {"path": str(path), "removed": True, "name": name}
    except OSError as exc:
        return {"path": str(path), "removed": False, "error": str(exc)}


def _coderank_model_dirs() -> list[Path]:
    """Locate FastEmbed / Hugging Face caches that hold CodeRank weights."""
    roots: list[Path] = []
    try:
        from fastembed.common.utils import define_cache_dir

        roots.append(Path(define_cache_dir()))
    except Exception:  # noqa: BLE001
        pass

    home = Path.home()
    candidates = [
        home / ".cache" / "fastembed",
        home / ".cache" / "huggingface",
        home / ".cache" / "huggingface" / "hub",
        Path(tempfile.gettempdir()) / "fastembed_cache",
        Path(os.environ.get("HF_HOME", "")),
        Path(os.environ.get("HUGGINGFACE_HUB_CACHE", "")),
        Path(os.environ.get("FASTEMBED_CACHE", "")),
    ]
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        candidates.extend(
            [
                Path(local) / "fastembed",
                Path(local) / "huggingface",
                Path(local) / "huggingface" / "hub",
            ]
        )
    for c in candidates:
        if c and str(c) not in {"", "."}:
            roots.append(c)

    # Unique existing roots
    seen: set[str] = set()
    uniq: list[Path] = []
    for r in roots:
        key = str(r.resolve()) if r.exists() else str(r)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)

    patterns = (
        "coderank",
        "CodeRank",
        "nomic-ai",
        "jamie8johnson",
        "model_fp16",
    )
    found: list[Path] = []
    for root in uniq:
        if not root.exists():
            continue
        # Whole FastEmbed cache is CE-owned enough on wipe --all models.
        if root.name.lower() in {"fastembed"} or "fastembed" in str(root).lower():
            found.append(root)
            continue
        try:
            for child in root.rglob("*"):
                name = child.name
                if any(p.lower() in name.lower() for p in patterns):
                    # Prefer top-ish model dirs, not every file.
                    target = child if child.is_dir() else child.parent
                    found.append(target)
        except OSError:
            continue

    # Dedup by path, prefer shorter (parent) paths
    found_sorted = sorted({p.resolve() for p in found if p.exists()}, key=lambda p: len(str(p)))
    pruned: list[Path] = []
    for p in found_sorted:
        if any(str(p).startswith(str(keep) + os.sep) or p == keep for keep in pruned):
            continue
        pruned.append(p)
    return pruned


def wipe_repo(root: Path | str, *, mcp: bool = True, rule: bool = True) -> dict[str, Any]:
    """Remove this repository's CE enrollment + on-disk index store."""
    from pipeline.project_id import id_file_path, read_id_file
    from pipeline.repo_lifecycle import remove_repo

    root = Path(root).resolve()
    out: dict[str, Any] = {"ok": True, "scope": "repo", "root": str(root), "actions": []}
    project_id = read_id_file(root)
    try:
        removed = remove_repo(root, delete_store=True)
        out["actions"].append({"remove_repo": removed})
        if not removed.get("ok") and removed.get("error") not in {"unmanaged"}:
            out["ok"] = False
    except Exception as exc:  # noqa: BLE001
        out["ok"] = False
        out["actions"].append({"remove_repo": {"ok": False, "error": str(exc)}})

    id_path = id_file_path(root)
    if id_path.is_file() or id_path.parent.is_dir():
        out["actions"].append({"id_dir": _rm_tree(id_path.parent)})

    if mcp:
        out["actions"].append(
            {"mcp": _drop_mcp_server(root / ".cursor" / "mcp.json")}
        )
    if rule:
        rule_path = root / ".cursor" / "rules" / "context-agent.mdc"
        out["actions"].append({"rule": _rm_tree(rule_path)})

    out["project_id"] = project_id
    from pipeline.project_id import context_engine_home

    home = context_engine_home()
    out["still_on_machine"] = {
        "ctx_home": str(home),
        "accel_json": (home / "accel.json").is_file(),
        "note": (
            "Repo index/MCP removed only. GPU runtime, accel.json, and CodeRank "
            "model caches were kept — that is why `scubiee setup` can finish in seconds."
        ),
    }
    out["hint"] = (
        "Full clean (home + models + MCP + daemon + uninstall scubiee): scubiee wipe --all --yes\n"
        "Then reinstall: uv tool install scubiee --index-url https://pypi.org/simple && scubiee setup"
    )
    return out


def wipe_all(
    *,
    yes: bool = False,
    models: bool = True,
    package: bool | None = None,
    repo: Path | str | None = None,
) -> dict[str, Any]:
    """Nuclear wipe: daemon, home, MCP, rules, and optionally models / pip package."""
    from pipeline.project_id import context_engine_home

    home = context_engine_home()
    plan = {
        "ctx_home": str(home),
        "user_mcp": str(Path.home() / ".cursor" / "mcp.json"),
        "models": models,
        "package": package,
        "repo": str(Path(repo).resolve()) if repo else None,
    }
    if not yes:
        return {
            "ok": False,
            "scope": "all",
            "error": "confirm_required",
            "plan": plan,
            "hint": (
                "This deletes ALL Context Engine state on this machine "
                "(indexes, prefs, MCP wiring, CodeRank model caches, and the scubiee tool). "
                "Re-run with: scubiee wipe --all --yes"
                "  (or: scubiee wipe --all --confirm)"
            ),
        }

    if package is None:
        package = True
    plan["package"] = package

    actions: list[dict[str, Any]] = []

    from pipeline.process_control import remove_tool_shims, stop_all_context_engine_processes

    # Stop background processes first so files unlock on Windows.
    try:
        actions.append({"stop_all": stop_all_context_engine_processes(ctx_home=home)})
    except Exception as exc:  # noqa: BLE001
        actions.append({"stop_all": {"ok": False, "error": str(exc)}})

    try:
        from pipeline.watchdog import stop_watchdog

        actions.append({"stop_watchdog": stop_watchdog()})
    except Exception as exc:  # noqa: BLE001
        actions.append({"stop_watchdog": {"ok": False, "error": str(exc)}})

    try:
        from pipeline.daemon import stop_daemon

        actions.append({"stop_daemon": stop_daemon()})
    except Exception as exc:  # noqa: BLE001
        actions.append({"stop_daemon": {"ok": False, "error": str(exc)}})

    try:
        from pipeline.lifecycle_runtime import unregister_logon_autostart

        actions.append({"unregister_autostart": unregister_logon_autostart()})
    except Exception as exc:  # noqa: BLE001
        actions.append({"unregister_autostart": {"ok": False, "error": str(exc)}})

    # Repo-local leftovers (cwd / explicit path) before deleting the registry.
    target = Path(repo).resolve() if repo else Path.cwd().resolve()
    try:
        actions.append({"wipe_repo": wipe_repo(target, mcp=True, rule=True)})
    except Exception as exc:  # noqa: BLE001
        actions.append({"wipe_repo": {"ok": False, "error": str(exc)}})

    actions.append({"user_mcp": _drop_mcp_server(Path.home() / ".cursor" / "mcp.json")})
    # Also clear project mcp if still present after wipe_repo.
    actions.append({"project_mcp": _drop_mcp_server(target / ".cursor" / "mcp.json")})

    actions.append({"ctx_home": _rm_tree(home)})

    actions.append({"tool_shims": remove_tool_shims()})

    # Legacy / hard-coded home if CTX_HOME pointed elsewhere.
    default_home = Path.home() / ".context-engine"
    if default_home.resolve() != home.resolve() and default_home.exists():
        actions.append({"default_ctx_home": _rm_tree(default_home)})

    model_removed: list[dict[str, Any]] = []
    if models:
        for d in _coderank_model_dirs():
            model_removed.append(_rm_tree(d))
        actions.append({"models": model_removed})

    pkg_out: dict[str, Any] | None = None
    if package:
        from pipeline.process_control import is_uv_tool_install, uv_tool_uninstall

        if is_uv_tool_install():
            pkg_out = uv_tool_uninstall()
        else:
            import subprocess

            cmd = [sys.executable, "-m", "pip", "uninstall", "-y", "scubiee"]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
                pkg_out = {
                    "ok": proc.returncode == 0,
                    "cmd": cmd,
                    "stdout": (proc.stdout or "")[-500:],
                    "stderr": (proc.stderr or "")[-500:],
                }
            except Exception as exc:  # noqa: BLE001
                pkg_out = {"ok": False, "error": str(exc)}
        actions.append({"uninstall_scubiee": pkg_out})

    ok = True
    for a in actions:
        for v in a.values():
            if isinstance(v, dict) and v.get("ok") is False and v.get("error") not in {
                "unmanaged",
                "confirm_required",
            }:
                # Soft failures (missing paths) are fine; hard errors flip ok.
                if v.get("error") and not v.get("missing") and not v.get("absent"):
                    ok = False
    return {
        "ok": ok,
        "scope": "all",
        "plan": plan,
        "actions": actions,
        "next": (
            "Machine is clean. Reinstall: "
            "uv tool install scubiee --index-url https://pypi.org/simple && scubiee setup"
            if package
            else "Re-run: scubiee setup && scubiee init ."
        ),
    }


def wipe(
    *,
    all: bool = False,
    yes: bool = False,
    models: bool = True,
    package: bool | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    if all:
        return wipe_all(yes=yes, models=models, package=package, repo=path)
    root = Path(path).resolve() if path else Path.cwd().resolve()
    return wipe_repo(root)
