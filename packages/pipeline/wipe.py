"""Wipe Scubiee state — repo-local or full machine (``--all``).

Normal path stays untouched: ``setup`` → ``init`` → use. Wipe is opt-in cleanup.
``wipe --all --confirm`` removes home state, MCP wiring for every connect target,
rules/steering, and CodeRank model caches so a fresh install starts clean.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from pipeline.branding import (
    DATA_DIR_NAMES,
    MARKER_START,
    MCP_SERVER_NAMES,
)
from pipeline.project_id import context_engine_home

# Cursor rule filenames written by connect.
_CURSOR_RULE_NAMES = ("scubiee.mdc",)


def _cursor_rule_paths(base: Path) -> list[Path]:
    rules = base / ".cursor" / "rules"
    return [rules / name for name in _CURSOR_RULE_NAMES]


def _kiro_mcp_paths(base: Path) -> list[Path]:
    """All .kiro/settings/mcp.json locations that connect may have written."""
    return [base / ".kiro" / "settings" / "mcp.json"]


def _kiro_steering_paths(base: Path) -> list[Path]:
    """Steering files scubiee connect may have written (current + legacy)."""
    return [base / ".kiro" / "steering" / "scubiee.md"]


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


def _drop_mcp_server(path: Path, *, name: str | None = None) -> dict[str, Any]:
    names = (name,) if name else MCP_SERVER_NAMES
    if not path.is_file():
        return {"path": str(path), "removed": False, "missing": True}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"path": str(path), "removed": False, "error": str(exc)}
    if not isinstance(data, dict):
        return {"path": str(path), "removed": False, "error": "not_object"}

    removed_names: list[str] = []
    for key in ("mcpServers", "servers", "mcp", "context_servers", "amp.mcpServers"):
        servers = data.get(key)
        if not isinstance(servers, dict):
            continue
        for n in names:
            if n not in servers:
                continue
            servers.pop(n, None)
            removed_names.append(n)
        if servers:
            data[key] = servers
        else:
            data.pop(key, None)

    if not removed_names:
        return {"path": str(path), "removed": False, "absent": True}
    try:
        if data:
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        else:
            path.unlink(missing_ok=True)
        return {"path": str(path), "removed": True, "name": removed_names}
    except OSError as exc:
        return {"path": str(path), "removed": False, "error": str(exc)}


def _workspace_local_mcp_paths(repo: Path) -> list[Path]:
    """Local MCP files written by connect for Kiro/Copilot/Cline/Roo."""
    from pipeline.tool_registry import all_workspace_local_mcp_paths

    return all_workspace_local_mcp_paths(repo)


def _coderank_model_dirs() -> list[Path]:
    """Locate FastEmbed / Hugging Face caches that hold CodeRank weights."""
    from pipeline.accel import CODERANK_HF_ONNX, CODERANK_MODEL, default_fastembed_cache_root

    hf_repo_slugs = (
        CODERANK_MODEL.replace("/", "--"),
        CODERANK_HF_ONNX.replace("/", "--"),
    )
    hub_prefixes = tuple(f"models--{slug}" for slug in hf_repo_slugs) + (
        "models--nomic-ai--CodeRankEmbed",
        "models--jamie8johnson--CodeRankEmbed-onnx",
    )

    roots: list[Path] = [default_fastembed_cache_root()]

    home = Path.home()
    candidates = [
        home / ".cache" / "fastembed",
        home / ".cache" / "huggingface",
        home / ".cache" / "huggingface" / "hub",
        Path(tempfile.gettempdir()) / "fastembed_cache",
    ]
    for env_name in ("HF_HOME", "HUGGINGFACE_HUB_CACHE", "FASTEMBED_CACHE", "FASTEMBED_CACHE_PATH"):
        raw = os.environ.get(env_name, "").strip()
        if raw:
            candidates.append(Path(raw))
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        candidates.extend(
            [
                Path(local) / "fastembed",
                Path(local) / "huggingface",
                Path(local) / "huggingface" / "hub",
            ]
        )

    # Unique candidate roots (existing or not — we may create paths during setup).
    seen: set[str] = set()
    uniq: list[Path] = []
    for r in roots + candidates:
        if not r or str(r) in {"", "."}:
            continue
        key = str(r)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)

    found: list[Path] = []
    for root in uniq:
        if not root.exists():
            continue
        low = str(root).lower()
        if root.name.lower() == "fastembed" or "fastembed" in low:
            found.append(root)
            continue
        hub = root if root.name.lower() == "hub" else root / "hub"
        if hub.is_dir():
            for child in hub.iterdir():
                if not child.is_dir():
                    continue
                name = child.name
                if name.startswith(hub_prefixes) or any(
                    token in name.lower()
                    for token in ("coderank", "nomic-ai", "jamie8johnson")
                ):
                    found.append(child)
            continue
        # Fallback: shallow pattern scan for odd cache layouts.
        try:
            for child in root.iterdir():
                name = child.name
                if child.is_dir() and any(
                    token in name.lower()
                    for token in ("coderank", "nomic-ai", "jamie8johnson", "model_fp16")
                ):
                    found.append(child)
        except OSError:
            continue

    found_sorted = sorted({p.resolve() for p in found if p.exists()}, key=lambda p: len(str(p)))
    pruned: list[Path] = []
    for p in found_sorted:
        if any(str(p).startswith(str(keep) + os.sep) or p == keep for keep in pruned):
            continue
        pruned.append(p)

    # MLX FP16 weights live under ~/.scubiee/mlx/CodeRankEmbed — include
    # them explicitly so --all plans/audits list model data even when only the
    # parent home was expected to vanish.
    for home in _context_engine_homes():
        mlx_dir = home / "mlx" / "CodeRankEmbed"
        if mlx_dir.is_dir():
            try:
                resolved = mlx_dir.resolve()
            except OSError:
                resolved = mlx_dir
            if not any(
                str(resolved).startswith(str(keep) + os.sep) or resolved == keep
                for keep in pruned
            ):
                # Prefer listing the leaf model dir; home wipe still removes parent.
                pruned.append(resolved)
    return pruned


def _context_engine_homes() -> list[Path]:
    """Every Scubiee home directory (CTX_HOME / ``~/.scubiee``)."""
    homes: list[Path] = [context_engine_home()]
    for name in DATA_DIR_NAMES:
        homes.append(Path.home() / name)
    seen: set[str] = set()
    out: list[Path] = []
    for home in homes:
        try:
            key = str(home.resolve())
        except OSError:
            key = str(home)
        if key in seen:
            continue
        seen.add(key)
        out.append(home)
    return out


def _vectordb_roots() -> list[Path]:
    from pipeline.vectordb import default_vectordb_root

    root = default_vectordb_root()
    homes = {str(h.resolve()) for h in _context_engine_homes() if h.exists()}
    try:
        resolved = str(root.resolve())
    except OSError:
        resolved = str(root)
    if any(resolved == home or resolved.startswith(home + os.sep) for home in homes):
        return []
    return [root]


def _discover_repo_id_dirs(root: Path) -> list[Path]:
    """Every repo-local ``.scubiee`` directory under ``root`` (includes nested checkouts)."""
    root = root.resolve()
    if not root.is_dir():
        return []
    found: list[Path] = []
    seen: set[str] = set()
    for name in DATA_DIR_NAMES:
        try:
            for path in root.rglob(name):
                if path.name != name or not path.is_dir():
                    continue
                try:
                    key = str(path.resolve())
                except OSError:
                    continue
                if os.name == "nt":
                    key = key.lower()
                if key in seen:
                    continue
                seen.add(key)
                found.append(path)
        except OSError:
            continue
    return sorted(found, key=lambda p: len(str(p)), reverse=True)


def _registered_repo_roots() -> list[Path]:
    """All checkout paths known to the registry, including resolved moved paths (before home is deleted)."""
    from pipeline.project_id import load_registry
    from pipeline.hw_track import resolve_moved_path

    roots: list[Path] = []
    seen: set[str] = set()
    reg = load_registry()
    for meta in (reg.get("projects") or {}).values():
        if not isinstance(meta, dict):
            continue
        # Check standard registered paths
        for raw in meta.get("paths") or []:
            try:
                path = Path(str(raw)).resolve()
            except OSError:
                continue
            key = str(path).lower() if os.name == "nt" else str(path)
            if key in seen or not path.exists():
                continue
            seen.add(key)
            roots.append(path)
        root = meta.get("root")
        if root:
            try:
                path = Path(str(root)).resolve()
            except OSError:
                continue
            key = str(path).lower() if os.name == "nt" else str(path)
            if key not in seen and path.exists():
                seen.add(key)
                roots.append(path)

        # Hardware reference check: if paths moved, resolve via permanent OS File ID / Inode
        fs_id = meta.get("fs_id")
        if isinstance(fs_id, dict):
            try:
                resolved_moved = resolve_moved_path(fs_id)
                if resolved_moved and resolved_moved.exists():
                    key = str(resolved_moved).lower() if os.name == "nt" else str(resolved_moved)
                    if key not in seen:
                        seen.add(key)
                        roots.append(resolved_moved)
            except Exception:
                pass
    return roots


def _uv_tool_dir() -> Path | None:
    try:
        from pipeline.process_control import uv_tool_root

        return uv_tool_root()
    except Exception:  # noqa: BLE001
        raw = os.environ.get("APPDATA", "").strip()
        if not raw:
            return None
        return Path(raw) / "uv" / "tools" / "scubiee"


def _mcp_has_context_engine(path: Path, *, name: str | None = None) -> bool:
    names = (name,) if name else MCP_SERVER_NAMES
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    if any(n in text for n in names) and path.suffix.lower() in {".toml", ".yaml", ".yml"}:
        return True
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return any(n in text for n in names)
    if not isinstance(data, dict):
        return False
    for key in ("mcpServers", "servers", "mcp", "context_servers", "amp.mcpServers"):
        servers = data.get(key)
        if isinstance(servers, dict) and any(n in servers for n in names):
            return True
        if isinstance(servers, list):
            for item in servers:
                if isinstance(item, dict) and item.get("name") in names:
                    return True
    return False


def _connected_tool_mcp_paths() -> list[tuple[str, Path]]:
    """Global MCP paths connect may have written (for wipe audit)."""
    from pipeline.tool_registry import TOOLS, resolve_mcp_write_targets

    out: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for tool in TOOLS:
        for path, _schema, _key in resolve_mcp_write_targets(tool):
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            out.append((tool.slug, path))
    return out


def audit_scubiee_artifacts(*, include_package: bool = True, include_models: bool = True) -> dict[str, Any]:
    """Report CE-owned paths still present after a wipe (for honest CLI output)."""
    remaining: list[dict[str, Any]] = []

    def note(path: Path, *, kind: str) -> None:
        if not path.exists():
            return
        try:
            if path.is_dir():
                size = sum(
                    f.stat().st_size
                    for f in path.rglob("*")
                    if f.is_file()
                )
            else:
                size = path.stat().st_size
        except OSError:
            size = None
        remaining.append(
            {
                "kind": kind,
                "path": str(path),
                "size_bytes": size,
            }
        )

    for home in _context_engine_homes():
        note(home, kind="ctx_home")
    for root in _vectordb_roots():
        note(root, kind="vectordb")
    if include_models:
        for model in _coderank_model_dirs():
            note(model, kind="model_cache")
    for slug, mcp_path in _connected_tool_mcp_paths():
        if _mcp_has_context_engine(mcp_path):
            note(mcp_path, kind=f"tool_mcp:{slug}")
    # Rules/steering connect may have written for any tool.
    try:
        from pipeline.tool_registry import TOOLS, resolve_rule_user_paths

        for tool in TOOLS:
            for rule_path in resolve_rule_user_paths(tool):
                if not rule_path.is_file():
                    continue
                if tool.rule_format in {"mdc", "md"}:
                    note(rule_path, kind=f"tool_rule:{tool.slug}")
                elif tool.rule_format == "append-md":
                    try:
                        text = rule_path.read_text(encoding="utf-8")
                    except (OSError, UnicodeError):
                        continue
                    if MARKER_START in text:
                        note(rule_path, kind=f"tool_rule:{tool.slug}")
    except Exception:  # noqa: BLE001
        pass
    for rule_path in _cursor_rule_paths(Path.home()):
        if rule_path.is_file() and not any(
            r.get("path") == str(rule_path) for r in remaining
        ):
            note(rule_path, kind="user_rule")
    for steering_path in _kiro_steering_paths(Path.home()):
        if steering_path.is_file() and not any(
            r.get("path") == str(steering_path) for r in remaining
        ):
            note(steering_path, kind="kiro_user_steering")
    tool = _uv_tool_dir()
    if tool is not None and include_package:
        note(tool, kind="uv_tool")
    for shim in (
        Path.home() / ".local" / "bin" / "scubiee.exe",
        Path.home() / ".local" / "bin" / "scubiee",
        Path.home() / ".local" / "bin" / "ctx.exe",
        Path.home() / ".local" / "bin" / "ctx-mcp.exe",
    ):
        note(shim, kind="tool_shim")

    # Repo-local enrollment markers left behind (root + nested checkouts).
    checked_roots: set[str] = set()
    for repo in _registered_repo_roots():
        repo_key = str(repo.resolve()).lower() if os.name == "nt" else str(repo.resolve())
        if repo_key in checked_roots:
            continue
        checked_roots.add(repo_key)
        for id_dir in _discover_repo_id_dirs(repo):
            note(id_dir, kind="repo_id_dir")
        for rule_path in _cursor_rule_paths(repo):
            if rule_path.is_file():
                note(rule_path, kind="repo_rule")
        project_mcp = repo / ".cursor" / "mcp.json"
        if _mcp_has_context_engine(project_mcp):
            note(project_mcp, kind="repo_mcp")
        for local_mcp in _workspace_local_mcp_paths(repo):
            if _mcp_has_context_engine(local_mcp):
                note(local_mcp, kind="workspace_local_mcp")
        for steering_path in _kiro_steering_paths(repo):
            if steering_path.is_file():
                note(steering_path, kind="kiro_repo_steering")

    return {
        "clean": not remaining,
        "remaining": remaining,
        "hint": (
            "If paths remain, quit Cursor completely (MCP locks files), run "
            "`scubiee stop`, then `scubiee wipe --all --confirm` again."
            if remaining
            else None
        ),
    }


def _halt_scubiee_before_wipe(
    *,
    scope: str,
    repo: Path | None = None,
) -> dict[str, Any]:
    """Kill/disable everything that can respawn or lock files during wipe.

    Wipe is destructive cleanup — same intent as ``scubiee stop``, then kill any
    stragglers. Callers must run this *before* deleting on-disk state.
    """
    actions: dict[str, Any] = {}
    target = (repo or Path.cwd()).resolve()
    home = context_engine_home()

    # 1. Remove MCP wiring first so IDEs do not respawn scubiee-mcp mid-wipe.
    if scope == "all":
        try:
            from pipeline.rules_installer import uninstall_tools
            from pipeline.tool_registry import ALL_SLUGS

            actions["disconnect_all_tools"] = uninstall_tools(
                list(ALL_SLUGS),
                dry_run=False,
                repo=target,
                all_workspaces=True,
            )
        except Exception as exc:  # noqa: BLE001
            actions["disconnect_all_tools"] = {"ok": False, "error": str(exc)}
            actions["user_cursor_mcp"] = _drop_mcp_server(Path.home() / ".cursor" / "mcp.json")
            for kiro_mcp in _kiro_mcp_paths(Path.home()):
                actions[f"kiro_user_mcp:{kiro_mcp.name}"] = _drop_mcp_server(kiro_mcp)
        actions["project_cursor_mcp"] = _drop_mcp_server(target / ".cursor" / "mcp.json")
        for local_mcp in _workspace_local_mcp_paths(target):
            actions[f"workspace_local_mcp:{local_mcp.name}"] = _drop_mcp_server(local_mcp)
    elif repo is not None:
        try:
            from pipeline.rules_installer import strip_all_project_tool_surfaces

            actions["project_tool_surfaces"] = strip_all_project_tool_surfaces(repo)
        except Exception as exc:  # noqa: BLE001
            actions["project_tool_surfaces"] = {"ok": False, "error": str(exc)}

    # 2. Same as ``scubiee stop``: disable MCP + stop daemon/watchdog.
    try:
        from pipeline.pause_resume import is_paused, pause

        actions["pause"] = (
            {"ok": True, "already_paused": True}
            if is_paused()
            else pause()
        )
    except Exception as exc:  # noqa: BLE001
        actions["pause"] = {"ok": False, "error": str(exc)}

    # 3. Kill uv-tool / mcp_locate / daemon stragglers (Windows file locks).
    try:
        from pipeline.process_control import (
            kill_all_scubiee_processes,
            stop_all_context_engine_processes,
        )

        if scope == "all":
            actions["kill_all"] = kill_all_scubiee_processes(exclude_self=True)
        else:
            actions["stop_all"] = stop_all_context_engine_processes(ctx_home=home)
    except Exception as exc:  # noqa: BLE001
        actions["stop_all" if scope != "all" else "kill_all"] = {
            "ok": False,
            "error": str(exc),
        }

    if scope == "all":
        try:
            from pipeline.lifecycle_runtime import unregister_logon_autostart

            actions["unregister_autostart"] = unregister_logon_autostart()
        except Exception as exc:  # noqa: BLE001
            actions["unregister_autostart"] = {"ok": False, "error": str(exc)}

    critical = ("kill_all", "stop_all")
    halt_ok = all(
        not isinstance(actions.get(key), dict) or actions[key].get("ok", True) is not False
        for key in critical
        if key in actions
    )
    remaining = []
    for key in ("kill_all", "stop_all"):
        block = actions.get(key)
        if isinstance(block, dict):
            remaining.extend(block.get("remaining") or [])
    return {
        "ok": halt_ok,
        "scope": scope,
        "actions": actions,
        "remaining_processes": remaining,
    }


def wipe_repo(root: Path | str, *, mcp: bool = True, rule: bool = True) -> dict[str, Any]:
    """Remove this repository's CE enrollment + on-disk index store."""
    from pipeline.project_id import read_id_file
    from pipeline.repo_lifecycle import remove_repo

    root = Path(root).resolve()
    out: dict[str, Any] = {"ok": True, "scope": "repo", "root": str(root), "actions": []}

    halt = _halt_scubiee_before_wipe(scope="repo", repo=root)
    out["actions"].append({"halt": halt})
    for key, val in (halt.get("actions") or {}).items():
        out["actions"].append({key: val})
    if not halt.get("ok"):
        out["halt_warning"] = (
            "Some Scubiee processes may still be running — quit Cursor/Kiro, then retry wipe."
        )

    project_id = read_id_file(root)
    if not project_id:
        from pipeline.repo_lifecycle import _project

        project_id, _entry = _project(root)

    try:
        removed = remove_repo(root, delete_store=True)
        out["actions"].append({"remove_repo": removed})
        if not removed.get("ok") and removed.get("error") not in {"unmanaged"}:
            out["ok"] = False
    except Exception as exc:  # noqa: BLE001
        out["ok"] = False
        out["actions"].append({"remove_repo": {"ok": False, "error": str(exc)}})

    removed_id_dirs: list[str] = []
    for id_dir in _discover_repo_id_dirs(root):
        if id_dir.exists():
            result = _rm_tree(id_dir)
            out["actions"].append({"id_dir": result})
            removed_id_dirs.append(str(id_dir))

    out["removed_id_dirs"] = removed_id_dirs
    if removed_id_dirs:
        out["id_dirs_removed"] = len(removed_id_dirs)

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
        "Full clean (home + models + MCP + daemon + uninstall scubiee): scubiee wipe --all --confirm\n"
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
    homes = _context_engine_homes()
    home = homes[0]
    plan = {
        "ctx_homes": [str(h) for h in homes],
        "vectordb_roots": [str(p) for p in _vectordb_roots()],
        "user_mcp": str(Path.home() / ".cursor" / "mcp.json"),
        "models": models,
        "model_targets": [str(p) for p in _coderank_model_dirs()] if models else [],
        "registered_repos": [str(p) for p in _registered_repo_roots()],
        "package": package,
        "repo": str(Path(repo).resolve()) if repo else None,
    }
    if not yes:
        return {
            "ok": False,
            "status": "warning",
            "scope": "all",
            "warning": "confirm_required",
            "error": "confirm_required",
            "needs_confirm": True,
            "plan": plan,
            "message": (
                "Safety pause: full machine wipe was not run. "
                "This is intentional — confirm only when you mean to delete everything."
            ),
            "hint": (
                "This removes ALL Scubiee state: every enrolled repo's "
                ".scubiee + MCP/rules, all connect tool MCP entries "
                "(Cursor, Claude Code, Codex, Windsurf, Copilot, Cline, Roo, …), "
                "all home dirs (~/.scubiee), CodeRank/FastEmbed/"
                "HuggingFace model caches, uv tool shims, and the scubiee package. "
                "Re-run with: scubiee wipe --all --confirm. "
                "Wipe stops Scubiee automatically; quit Cursor/Kiro first on Windows "
                "so MCP does not hold file locks."
            ),
        }

    if package is None:
        package = True
    plan["package"] = package

    actions: list[dict[str, Any]] = []

    target = Path(repo).resolve() if repo else Path.cwd().resolve()
    halt = _halt_scubiee_before_wipe(scope="all", repo=target)
    actions.append({"halt": halt})
    for key, val in (halt.get("actions") or {}).items():
        actions.append({key: val})

    # Every enrolled checkout (registry) + explicit target/cwd.
    repo_targets: list[Path] = []
    seen_repo: set[str] = set()
    for candidate in list(_registered_repo_roots()):
        key = str(candidate).lower() if os.name == "nt" else str(candidate)
        if key in seen_repo:
            continue
        seen_repo.add(key)
        repo_targets.append(candidate)
    target_key = str(target).lower() if os.name == "nt" else str(target)
    if target_key not in seen_repo:
        repo_targets.append(target)

    repo_actions: list[dict[str, Any]] = []
    for repo_root in repo_targets:
        try:
            repo_actions.append(
                {"root": str(repo_root), **wipe_repo(repo_root, mcp=True, rule=True)}
            )
        except Exception as exc:  # noqa: BLE001
            repo_actions.append(
                {"root": str(repo_root), "ok": False, "error": str(exc)}
            )
    actions.append({"wipe_repos": repo_actions})

    actions.append({"user_mcp": _drop_mcp_server(Path.home() / ".cursor" / "mcp.json")})
    # Also clean Kiro user-level MCP and steering
    for kiro_mcp in _kiro_mcp_paths(Path.home()):
        actions.append({"kiro_user_mcp": _drop_mcp_server(kiro_mcp)})
    for rule_path in _cursor_rule_paths(Path.home()):
        actions.append({"user_rule": _rm_tree(rule_path)})
    for steering_path in _kiro_steering_paths(Path.home()):
        actions.append({"kiro_user_steering": _rm_tree(steering_path)})

    for ctx_home in homes:
        actions.append({f"ctx_home:{ctx_home.name}": _rm_tree(ctx_home)})

    for vroot in _vectordb_roots():
        actions.append({f"vectordb:{vroot.name}": _rm_tree(vroot)})

    from pipeline.process_control import remove_tool_shims

    actions.append({"tool_shims": remove_tool_shims()})

    model_removed: list[dict[str, Any]] = []
    if models:
        for d in _coderank_model_dirs():
            model_removed.append(_rm_tree(d))
        actions.append({"models": model_removed})

    pkg_out: dict[str, Any] | None = None
    if package:
        import shutil
        import subprocess

        from pipeline.process_control import force_remove_uv_tool_dir, is_uv_tool_install, uv_tool_uninstall

        # Try uv tool uninstall first (covers uv tool installs AND detects the tool dir)
        uv_tool_dir = _uv_tool_dir()
        uv_bin = shutil.which("uv")
        if is_uv_tool_install() or (uv_tool_dir and uv_tool_dir.exists()):
            pkg_out = uv_tool_uninstall()
        elif uv_bin:
            # uv available but not a tool install — try uv pip uninstall
            cmd = [uv_bin, "pip", "uninstall", "--python", sys.executable, "scubiee"]
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
        else:
            # Fallback: plain pip
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
        tool = _uv_tool_dir()
        if tool is not None and tool.exists():
            forced = force_remove_uv_tool_dir()
            if isinstance(pkg_out, dict):
                pkg_out["forced_tool_dir"] = forced
                if not forced.get("ok"):
                    pkg_out["ok"] = False
        actions.append({"uninstall_scubiee": pkg_out})

    # After all state is gone, any remaining Scubiee process is pointless — kill again.
    try:
        from pipeline.process_control import kill_all_scubiee_processes

        final_kill = kill_all_scubiee_processes(exclude_self=True, rounds=3)
        actions.append({"final_kill": final_kill})
    except Exception as exc:  # noqa: BLE001
        final_kill = {"ok": False, "error": str(exc), "remaining": []}
        actions.append({"final_kill": final_kill})

    audit = audit_scubiee_artifacts(include_package=package, include_models=models)
    actions.append({"audit": audit})

    remaining_processes = final_kill.get("remaining") or []

    ok = True
    for a in actions:
        for v in a.values():
            if isinstance(v, dict) and v.get("ok") is False and v.get("error") not in {
                "unmanaged",
                "confirm_required",
            }:
                if v.get("error") and not v.get("missing") and not v.get("absent"):
                    ok = False
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, dict) and item.get("removed") is False and item.get("error"):
                        ok = False
    if not audit.get("clean"):
        ok = False
    if not final_kill.get("ok"):
        ok = False

    return {
        "ok": ok,
        "scope": "all",
        "plan": plan,
        "actions": actions,
        "remaining": audit.get("remaining") or [],
        "remaining_processes": remaining_processes,
        "audit": audit,
        "next": (
            "Machine is clean. Reinstall: "
            "uv tool install scubiee --index-url https://pypi.org/simple && scubiee setup"
            if package and audit.get("clean") and final_kill.get("ok")
            else (
                "Some Scubiee files may remain (see remaining). Quit Cursor completely "
                "so MCP releases file locks, then run `scubiee wipe --all --confirm` again."
                if audit.get("remaining")
                else (
                    "Scubiee processes still running after wipe (see remaining_processes). "
                    "Quit Cursor/Kiro — its MCP host may have respawned scubiee-mcp."
                    if remaining_processes
                    else (
                        "Re-run: scubiee setup && scubiee init ."
                        if not package
                        else "Reinstall: uv tool install scubiee && scubiee setup"
                    )
                )
            )
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
