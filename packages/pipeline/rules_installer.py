"""Connect Scubiee to AI coding tools — global MCP + rules only.

Usage:
    scubiee connect --all
    scubiee connect --cursor --claude-code --codex --kiro --opencode

Never writes project configs. Never pins CTX_REPO.
See docs/connect-global-mcp-research.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline.mcp_install import server_entry
from pipeline.tool_registry import (
    TOOL_MAP,
    ToolDef,
    resolve_mcp_user_path,
    resolve_mcp_user_paths,
    resolve_mcp_write_targets,
    resolve_rule_user_path,
    resolve_rule_user_paths,
)


def _templates_dir() -> Path:
    return Path(__file__).resolve().parent / "templates"


def _rule_content_md() -> str:
    return (_templates_dir() / "context-engine.md").read_text(encoding="utf-8")


def _rule_content_mdc() -> str:
    return (_templates_dir() / "context-agent.mdc").read_text(encoding="utf-8")


_MARKER_START = "<!-- context-engine:start -->"
_MARKER_END = "<!-- context-engine:end -->"
_SERVER_NAME = "context-engine"


# ---------------------------------------------------------------------------
# Entry shaping
# ---------------------------------------------------------------------------

def format_server_entry(
    tool: ToolDef,
    repo: Path | str | None = None,
    *,
    pin_repo: bool = False,
    schema: str | None = None,
) -> dict[str, Any]:
    """Return only fields accepted by the target tool's MCP schema.

    Global connect always uses pin_repo=False (repo ignored).
    """
    base = server_entry(repo if pin_repo else None)
    cmd = str(base["command"])
    args = [str(a) for a in base.get("args") or []]
    env = {str(k): str(v) for k, v in (base.get("env") or {}).items()}

    use_schema = schema or tool.mcp_schema
    if use_schema == "claude":
        return {"command": cmd, "args": args, "env": env}
    if use_schema == "vscode":
        # When repo-neutral (no CTX_REPO in env), inject WORKSPACE_FOLDER so
        # VS Code resolves the active workspace before launching the process.
        # _default_repo() already checks this variable for workspace discovery.
        if "CTX_REPO" not in env:
            env.setdefault("WORKSPACE_FOLDER", "${workspaceFolder}")
        return {"type": "stdio", "command": cmd, "args": args, "env": env}
    if use_schema == "copilot_cli":
        # GitHub Copilot CLI ~/.copilot/mcp-config.json
        # Inject WORKSPACE_FOLDER for workspace discovery when repo-neutral.
        if "CTX_REPO" not in env:
            env.setdefault("WORKSPACE_FOLDER", "${workspaceFolder}")
        return {
            "type": "local",
            "command": cmd,
            "args": args,
            "env": env,
            "tools": ["*"],
        }
    if use_schema == "opencode":
        return {
            "type": "local",
            "enabled": True,
            "command": [cmd, *args],
            "environment": env,
            "timeout": 120000,
        }
    if use_schema == "amp":
        return {"command": cmd, "args": args, "env": env}
    if use_schema == "codex":
        return {"command": cmd, "args": args, "env": env}
    if use_schema == "continue":
        return {"name": _SERVER_NAME, "command": cmd, "args": args, "env": env}
    if use_schema == "zed":
        return {"command": cmd, "args": args, "env": env}
    raise ValueError(f"unknown mcp_schema: {use_schema}")


def _server_entry_for_tool(tool: ToolDef, repo: Path | str | None = None) -> dict[str, Any]:
    return format_server_entry(tool, repo, pin_repo=False)


# ---------------------------------------------------------------------------
# MCP writers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _write_mcp_json_keyed(path: Path, key: str, entry: dict[str, Any]) -> None:
    """Write a server entry into a keyed MCP JSON config file.

    Defensive read-before-write: validates the loaded structure is a dict
    and logs a warning if it contains unexpected data (but still proceeds
    to avoid blocking the user's workflow).
    """
    import sys

    data = _load_json(path)

    # Defensive check: warn if the file has unexpected structure.
    # _load_json already returns {} for non-dict data, but if the file has
    # keys suggesting a completely different format, log a heads-up.
    if path.is_file() and data:
        _KNOWN_MCP_KEYS = {
            "mcpServers", "servers", "mcp", "$schema",
            "amp.mcpServers", "context_servers",
        }
        if key not in data and not any(k in _KNOWN_MCP_KEYS for k in data):
            print(
                f"[scubiee] WARNING: {path} has unexpected keys "
                f"({list(data.keys())[:5]}); writing '{key}' anyway.",
                file=sys.stderr,
                flush=True,
            )

    servers = data.get(key)
    if not isinstance(servers, dict):
        servers = {}
    servers[_SERVER_NAME] = entry
    data[key] = servers
    if key == "mcp" and "$schema" not in data:
        data = {"$schema": "https://opencode.ai/config.json", **data}
    _write_json(path, data)


def _write_mcp_amp(path: Path, entry: dict[str, Any]) -> None:
    data = _load_json(path)
    servers = data.get("amp.mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    servers[_SERVER_NAME] = entry
    data["amp.mcpServers"] = servers
    _write_json(path, data)


def _write_mcp_zed(path: Path, entry: dict[str, Any]) -> None:
    data = _load_json(path)
    servers = data.get("context_servers")
    if not isinstance(servers, dict):
        servers = {}
    servers[_SERVER_NAME] = {
        "command": entry["command"],
        "args": entry.get("args") or [],
        "env": entry.get("env") or {},
    }
    data["context_servers"] = servers
    _write_json(path, data)


def verify_mcp_configs(slugs: list[str]) -> list[dict[str, Any]]:
    """Verify MCP config files have a valid context-engine entry.

    For each tool slug, reads its MCP config file(s) and checks that the
    'context-engine' server entry exists with 'command' + 'args' keys.
    Callable from `scubiee doctor`.

    Returns a list of {tool, path, ok, error} dicts.
    """
    results: list[dict[str, Any]] = []
    for slug in slugs:
        tool = TOOL_MAP.get(slug)
        if not tool:
            results.append({"tool": slug, "path": None, "ok": False, "error": f"unknown tool: {slug}"})
            continue
        write_targets = resolve_mcp_write_targets(tool)
        if not write_targets:
            results.append({"tool": slug, "path": None, "ok": False, "error": "no MCP path configured"})
            continue
        for path, schema, key in write_targets:
            result: dict[str, Any] = {"tool": slug, "path": str(path), "ok": False, "error": None}
            if not path.is_file():
                result["error"] = "file does not exist"
                results.append(result)
                continue
            data = _load_json(path)
            if not data:
                result["error"] = "file is empty or not valid JSON"
                results.append(result)
                continue
            # Find the server entry depending on schema
            use_key = key if key is not None else tool.mcp_key
            if schema == "amp":
                servers = data.get("amp.mcpServers", {})
            elif schema == "zed":
                servers = data.get("context_servers", {})
            else:
                servers = data.get(use_key, {})
            if not isinstance(servers, dict):
                result["error"] = f"'{use_key}' is not a dict"
                results.append(result)
                continue
            entry = servers.get(_SERVER_NAME)
            if entry is None:
                result["error"] = f"'{_SERVER_NAME}' entry missing"
                results.append(result)
                continue
            if not isinstance(entry, dict):
                result["error"] = f"'{_SERVER_NAME}' entry is not a dict"
                results.append(result)
                continue
            # Check for required keys: command + args (or 'command' list for opencode)
            has_command = "command" in entry
            has_args = "args" in entry or (
                isinstance(entry.get("command"), list) and len(entry["command"]) > 1
            )
            if not has_command:
                result["error"] = "'command' key missing in server entry"
                results.append(result)
                continue
            if not has_args and schema != "opencode":
                result["error"] = "'args' key missing in server entry"
                results.append(result)
                continue
            result["ok"] = True
            results.append(result)
    return results


def _write_mcp_toml(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if path.is_file():
        existing = path.read_text(encoding="utf-8")
        new_lines: list[str] = []
        skip = False
        for line in existing.splitlines():
            if line.strip() == "[mcp_servers.context-engine]":
                skip = True
                continue
            if skip and line.startswith("["):
                skip = False
            if not skip:
                new_lines.append(line)
        lines = new_lines
    lines.append("")
    lines.append("[mcp_servers.context-engine]")
    lines.append(f'command = "{entry["command"]}"')
    args_str = ", ".join(f'"{a}"' for a in entry.get("args", []))
    lines.append(f"args = [{args_str}]")
    if entry.get("env"):
        env_parts = [f'{k} = "{v}"' for k, v in entry["env"].items()]
        lines.append(f"env = {{ {', '.join(env_parts)} }}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_mcp_continue_yaml(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    marker = "# context-engine"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    lines = existing.splitlines()
    new_lines: list[str] = []
    skip = False
    for line in lines:
        if marker in line:
            skip = True
            continue
        if skip and line.strip() and not line.startswith(" ") and not line.startswith("\t"):
            skip = False
        if not skip:
            new_lines.append(line)
    while new_lines and not new_lines[-1].strip():
        new_lines.pop()
    new_lines.append("")
    new_lines.append(f"mcpServers:  {marker}")
    new_lines.append(f"  - name: {entry.get('name', _SERVER_NAME)}")
    new_lines.append(f'    command: "{entry["command"]}"')
    args_yaml = ", ".join(f'"{a}"' for a in entry.get("args", []))
    new_lines.append(f"    args: [{args_yaml}]")
    if entry.get("env"):
        new_lines.append("    env:")
        for k, v in entry["env"].items():
            new_lines.append(f'      {k}: "{v}"')
    new_lines.append("")
    path.write_text("\n".join(new_lines), encoding="utf-8")


def write_mcp_config(
    tool: ToolDef,
    path: Path,
    entry: dict[str, Any],
    *,
    schema: str | None = None,
    key: str | None = None,
) -> None:
    use_schema = schema or tool.mcp_schema
    use_key = key if key is not None else tool.mcp_key
    if use_schema == "amp":
        _write_mcp_amp(path, entry)
    elif use_schema == "zed":
        _write_mcp_zed(path, entry)
    elif use_schema == "codex":
        _write_mcp_toml(path, entry)
    elif use_schema == "continue":
        _write_mcp_continue_yaml(path, entry)
    else:
        _write_mcp_json_keyed(path, use_key, entry)


# ---------------------------------------------------------------------------
# Rule writers
# ---------------------------------------------------------------------------

def _write_rule_mdc(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_rule_content_mdc(), encoding="utf-8")


def _write_rule_md(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_rule_content_md(), encoding="utf-8")


def _write_rule_append_md(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if _MARKER_START in existing:
        before = existing.split(_MARKER_START)[0]
        after = existing.split(_MARKER_END)[-1] if _MARKER_END in existing else ""
        existing = before.rstrip() + "\n\n" if before.strip() else ""
        existing += after.lstrip() if after.strip() else ""
    content = _rule_content_md()
    section = f"{_MARKER_START}\n{content}\n{_MARKER_END}\n"
    if existing and not existing.endswith("\n"):
        existing += "\n"
    if existing and not existing.endswith("\n\n"):
        existing += "\n"
    path.write_text(existing + section, encoding="utf-8")


_RULE_WRITERS = {
    "mdc": _write_rule_mdc,
    "md": _write_rule_md,
    "append-md": _write_rule_append_md,
    "none": lambda _path: None,
}


def _write_rule(tool: ToolDef, path: Path) -> None:
    writer = _RULE_WRITERS.get(tool.rule_format)
    if writer:
        writer(path)


# ---------------------------------------------------------------------------
# Public installer (global only)
# ---------------------------------------------------------------------------

def install_tool(
    tool: ToolDef,
    *,
    dry_run: bool = False,
    repo: Path | str | None = None,
) -> dict[str, Any]:
    """Install global MCP + rule for one tool. ``repo`` is ignored (compat)."""
    write_targets = resolve_mcp_write_targets(tool)
    mcp_paths = [p for p, _s, _k in write_targets]
    rule_paths = resolve_rule_user_paths(tool)
    primary = mcp_paths[0] if mcp_paths else None
    primary_rule = rule_paths[0] if rule_paths else None

    report: dict[str, Any] = {
        "tool": tool.name,
        "slug": tool.slug,
        "mcp_schema": tool.mcp_schema,
        "scope": "global",
        "mcp_path": str(primary) if primary else None,
        "mcp_paths": [str(p) for p in mcp_paths],
        "rule_path": str(primary_rule) if primary_rule else None,
        "rule_paths": [str(p) for p in rule_paths],
        "dry_run": dry_run,
        "ok": True,
        "errors": [],
    }
    if repo is not None:
        report["repo_ignored"] = True
        report["note"] = "connect is global-only; --repo is ignored"

    if dry_run:
        report["would_write_mcp"] = str(primary) if primary else None
        report["would_write_mcp_paths"] = [str(p) for p in mcp_paths]
        report["would_write_rule"] = str(primary_rule) if primary_rule else None
        report["would_write_rule_paths"] = [str(p) for p in rule_paths]
        return report

    try:
        if not write_targets:
            report["errors"].append(f"{tool.slug}: no global MCP path configured")
            report["ok"] = False
        else:
            for path, schema, key in write_targets:
                entry = format_server_entry(tool, pin_repo=False, schema=schema)
                write_mcp_config(tool, path, entry, schema=schema, key=key)
                if "CTX_REPO" in (entry.get("env") or {}) or "CTX_REPO" in (
                    entry.get("environment") or {}
                ):
                    report["errors"].append(
                        "internal error: CTX_REPO leaked into global entry"
                    )
                    report["ok"] = False
            report["mcp_written"] = True
    except Exception as exc:  # noqa: BLE001
        report["mcp_written"] = False
        report["errors"].append(f"mcp write failed: {exc}")
        report["ok"] = False

    try:
        if rule_paths and tool.rule_format != "none":
            for rule_path in rule_paths:
                _write_rule(tool, rule_path)
            report["rule_written"] = True
        else:
            report["rule_written"] = None
    except Exception as exc:  # noqa: BLE001
        report["rule_written"] = False
        report["errors"].append(f"rule write failed: {exc}")
        report["ok"] = False

    return report


def install_tools(
    slugs: list[str],
    *,
    dry_run: bool = False,
    repo: Path | str | None = None,
) -> list[dict[str, Any]]:
    results = []
    for slug in slugs:
        tool = TOOL_MAP.get(slug)
        if not tool:
            results.append({"tool": slug, "ok": False, "errors": [f"unknown tool: {slug}"]})
            continue
        results.append(install_tool(tool, dry_run=dry_run, repo=repo))
    return results


# ---------------------------------------------------------------------------
# Removers
# ---------------------------------------------------------------------------

def _remove_mcp_json_keyed(path: Path, key: str) -> bool:
    if not path.is_file():
        return False
    data = _load_json(path)
    servers = data.get(key)
    if not isinstance(servers, dict) or _SERVER_NAME not in servers:
        return False
    del servers[_SERVER_NAME]
    data[key] = servers
    _write_json(path, data)
    return True


def _remove_mcp_amp(path: Path) -> bool:
    if not path.is_file():
        return False
    data = _load_json(path)
    servers = data.get("amp.mcpServers")
    if not isinstance(servers, dict) or _SERVER_NAME not in servers:
        return False
    del servers[_SERVER_NAME]
    data["amp.mcpServers"] = servers
    _write_json(path, data)
    return True


def _remove_mcp_zed(path: Path) -> bool:
    return _remove_mcp_json_keyed(path, "context_servers")


def _remove_mcp_toml(path: Path) -> bool:
    if not path.is_file():
        return False
    existing = path.read_text(encoding="utf-8")
    if "[mcp_servers.context-engine]" not in existing:
        return False
    new_lines: list[str] = []
    skip = False
    for line in existing.splitlines():
        if line.strip() == "[mcp_servers.context-engine]":
            skip = True
            continue
        if skip and line.startswith("["):
            skip = False
        if not skip:
            new_lines.append(line)
    while new_lines and not new_lines[-1].strip():
        new_lines.pop()
    new_lines.append("")
    path.write_text("\n".join(new_lines), encoding="utf-8")
    return True


def _remove_mcp_continue_yaml(path: Path) -> bool:
    if not path.is_file():
        return False
    existing = path.read_text(encoding="utf-8")
    marker = "# context-engine"
    if marker not in existing:
        return False
    lines = existing.splitlines()
    new_lines: list[str] = []
    skip = False
    for line in lines:
        if marker in line:
            skip = True
            continue
        if skip and line.strip() and not line.startswith(" ") and not line.startswith("\t"):
            skip = False
        if not skip:
            new_lines.append(line)
    while new_lines and not new_lines[-1].strip():
        new_lines.pop()
    new_lines.append("")
    path.write_text("\n".join(new_lines), encoding="utf-8")
    return True


def remove_mcp_config(
    tool: ToolDef,
    path: Path,
    *,
    schema: str | None = None,
    key: str | None = None,
) -> bool:
    use_schema = schema or tool.mcp_schema
    use_key = key if key is not None else tool.mcp_key
    if use_schema == "amp":
        return _remove_mcp_amp(path)
    if use_schema == "zed":
        return _remove_mcp_zed(path)
    if use_schema == "codex":
        return _remove_mcp_toml(path)
    if use_schema == "continue":
        return _remove_mcp_continue_yaml(path)
    return _remove_mcp_json_keyed(path, use_key)


def _remove_rule_file(path: Path) -> bool:
    if not path.is_file():
        return False
    path.unlink()
    return True


def _remove_rule_section(path: Path) -> bool:
    if not path.is_file():
        return False
    existing = path.read_text(encoding="utf-8")
    if _MARKER_START not in existing:
        return False
    before = existing.split(_MARKER_START)[0]
    after = existing.split(_MARKER_END)[-1] if _MARKER_END in existing else ""
    result = before.rstrip()
    if after.strip():
        result += "\n\n" + after.lstrip()
    result = result.strip()
    if result:
        result += "\n"
    path.write_text(result, encoding="utf-8")
    return True


_RULE_REMOVERS = {
    "mdc": _remove_rule_file,
    "md": _remove_rule_file,
    "append-md": _remove_rule_section,
    "none": lambda _path: False,
}


def uninstall_tool(
    tool: ToolDef,
    *,
    dry_run: bool = False,
    repo: Path | str | None = None,
) -> dict[str, Any]:
    write_targets = resolve_mcp_write_targets(tool)
    mcp_paths = [p for p, _s, _k in write_targets]
    rule_paths = resolve_rule_user_paths(tool)
    primary = mcp_paths[0] if mcp_paths else None
    primary_rule = rule_paths[0] if rule_paths else None

    report: dict[str, Any] = {
        "tool": tool.name,
        "slug": tool.slug,
        "scope": "global",
        "mcp_path": str(primary) if primary else None,
        "mcp_paths": [str(p) for p in mcp_paths],
        "rule_path": str(primary_rule) if primary_rule else None,
        "rule_paths": [str(p) for p in rule_paths],
        "dry_run": dry_run,
        "ok": True,
        "errors": [],
        "mcp_removed": False,
        "rule_removed": False,
    }

    if dry_run:
        report["would_remove_mcp"] = str(primary) if primary else None
        report["would_remove_mcp_paths"] = [str(p) for p in mcp_paths]
        report["would_remove_rule"] = str(primary_rule) if primary_rule else None
        report["would_remove_rule_paths"] = [str(p) for p in rule_paths]
        return report

    try:
        removed = False
        for path, schema, key in write_targets:
            removed = remove_mcp_config(tool, path, schema=schema, key=key) or removed
        report["mcp_removed"] = removed
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"mcp removal failed: {exc}")
        report["ok"] = False

    try:
        remover = _RULE_REMOVERS.get(tool.rule_format)
        if remover and rule_paths and tool.rule_format != "none":
            any_removed = False
            for rule_path in rule_paths:
                any_removed = remover(rule_path) or any_removed
            report["rule_removed"] = any_removed
        else:
            report["rule_removed"] = None
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"rule removal failed: {exc}")
        report["ok"] = False

    return report


def uninstall_tools(
    slugs: list[str],
    *,
    dry_run: bool = False,
    repo: Path | str | None = None,
) -> list[dict[str, Any]]:
    results = []
    for slug in slugs:
        tool = TOOL_MAP.get(slug)
        if not tool:
            results.append({"tool": slug, "ok": False, "errors": [f"unknown tool: {slug}"]})
            continue
        results.append(uninstall_tool(tool, dry_run=dry_run, repo=repo))
    return results
