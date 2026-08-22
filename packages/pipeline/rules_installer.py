"""Connect Scubiee to AI coding tools (MCP config + rules).

Usage from CLI:
    scubiee connect --cursor --claude-code --kiro --copilot
    scubiee connect --all
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path
from typing import Any

from pipeline.mcp_install import interpreter, server_entry, write_kiro_mcp
from pipeline.tool_registry import (
    ALL_SLUGS,
    TOOL_MAP,
    ToolDef,
    resolve_mcp_path,
    resolve_rule_path,
)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

def _templates_dir() -> Path:
    return Path(__file__).resolve().parent / "templates"


def _rule_content_md() -> str:
    """Universal markdown rule content."""
    path = _templates_dir() / "context-engine.md"
    return path.read_text(encoding="utf-8")


def _rule_content_mdc() -> str:
    """Cursor MDC format with frontmatter (same file as setup's write_cursor_rule)."""
    path = _templates_dir() / "context-agent.mdc"
    return path.read_text(encoding="utf-8")


# Marker for idempotent append operations
_MARKER_START = "<!-- context-engine:start -->"
_MARKER_END = "<!-- context-engine:end -->"


# ---------------------------------------------------------------------------
# MCP config writers (per format)
# ---------------------------------------------------------------------------

def _write_mcp_json(path: Path, key: str, entry: dict[str, Any]) -> None:
    """Merge a context-engine server entry into a JSON MCP config."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    if not isinstance(data, dict):
        data = {}
    servers = data.setdefault(key, {})
    if not isinstance(servers, dict):
        servers = {}
        data[key] = servers
    servers["context-engine"] = entry
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _write_mcp_toml(path: Path, _key: str, entry: dict[str, Any]) -> None:
    """Write/merge context-engine into a TOML config (Codex style)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Codex TOML format:
    # [mcp_servers.context-engine]
    # command = "python"
    # args = ["-u", "-m", "pipeline.mcp_locate"]
    # env = { CTX_ENGINE_URL = "..." }
    lines: list[str] = []
    if path.is_file():
        existing = path.read_text(encoding="utf-8")
        # Remove any previous context-engine section
        new_lines = []
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
    # Append new section
    lines.append("")
    lines.append("[mcp_servers.context-engine]")
    lines.append(f'command = "{entry["command"]}"')
    args_str = ", ".join(f'"{a}"' for a in entry.get("args", []))
    lines.append(f"args = [{args_str}]")
    if entry.get("env"):
        env_parts = []
        for k, v in entry["env"].items():
            env_parts.append(f'{k} = "{v}"')
        lines.append(f"env = {{ {', '.join(env_parts)} }}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_mcp_yaml(path: Path, _key: str, entry: dict[str, Any]) -> None:
    """Merge context-engine into a YAML config (Continue style)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Continue uses mcpServers as a top-level list of objects
    # We'll write a simple YAML block — avoid pulling in pyyaml dependency
    marker = "# context-engine"
    existing = ""
    if path.is_file():
        existing = path.read_text(encoding="utf-8")
    # Remove previous CE block
    lines = existing.splitlines()
    new_lines = []
    skip = False
    for line in lines:
        if marker in line:
            skip = True
            continue
        if skip and line.strip() and not line.startswith(" ") and not line.startswith("\t"):
            skip = False
        if not skip:
            new_lines.append(line)
    # Append new CE block
    new_lines.append("")
    new_lines.append(f"mcpServers:  {marker}")
    new_lines.append(f"  - name: context-engine")
    new_lines.append(f'    command: "{entry["command"]}"')
    args_yaml = ", ".join(f'"{a}"' for a in entry.get("args", []))
    new_lines.append(f"    args: [{args_yaml}]")
    if entry.get("env"):
        new_lines.append("    env:")
        for k, v in entry["env"].items():
            new_lines.append(f'      {k}: "{v}"')
    new_lines.append("")
    path.write_text("\n".join(new_lines), encoding="utf-8")


_MCP_WRITERS = {
    "json": _write_mcp_json,
    "jsonc": _write_mcp_json,
    "toml": _write_mcp_toml,
    "yaml": _write_mcp_yaml,
}


# ---------------------------------------------------------------------------
# Rule writers
# ---------------------------------------------------------------------------

def _write_rule_mdc(path: Path) -> None:
    """Write Cursor MDC rule file (overwrite)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_rule_content_mdc(), encoding="utf-8")


def _write_rule_md(path: Path) -> None:
    """Write standalone markdown rule file (overwrite)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_rule_content_md(), encoding="utf-8")


def _write_rule_append_md(path: Path) -> None:
    """Append CE rule section to an existing markdown file (idempotent)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if path.is_file():
        existing = path.read_text(encoding="utf-8")
    # If already present, replace the section
    if _MARKER_START in existing:
        before = existing.split(_MARKER_START)[0]
        after = existing.split(_MARKER_END)[-1] if _MARKER_END in existing else ""
        existing = before.rstrip() + "\n\n" if before.strip() else ""
        existing += after.lstrip() if after.strip() else ""
    # Append the marked section
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


# ---------------------------------------------------------------------------
# Public installer
# ---------------------------------------------------------------------------

def _server_entry_for_tool(tool: ToolDef, repo: Path | str | None = None) -> dict[str, Any]:
    """Format MCP block for the target tool (OpenCode uses a different schema)."""
    entry = server_entry(repo)
    if tool.slug != "opencode":
        return entry
    cmd = [str(entry["command"])]
    cmd.extend(str(a) for a in entry.get("args") or [])
    env = {str(k): str(v) for k, v in (entry.get("env") or {}).items()}
    if repo is not None:
        env["CTX_REPO"] = str(Path(repo).resolve()).replace("\\", "/")
    return {
        "type": "local",
        "enabled": True,
        "command": cmd,
        "environment": env,
        "timeout": 120000,
    }


def install_tool(
    tool: ToolDef,
    *,
    dry_run: bool = False,
    repo: Path | str | None = None,
) -> dict[str, Any]:
    """Install MCP config + rule for one tool. Returns a report dict.

    Kiro is special: its user-level entry remains repo-neutral while a
    workspace-level entry carries the explicit repository path.
    """
    mcp_path = resolve_mcp_path(tool)
    rule_path = resolve_rule_path(tool)
    entry = _server_entry_for_tool(tool, repo)
    workspace_root = Path(repo or Path.cwd()).resolve() if tool.slug == "kiro" else None
    workspace_mcp_path = workspace_root / tool.mcp_path if workspace_root else None

    report: dict[str, Any] = {
        "tool": tool.name,
        "slug": tool.slug,
        "mcp_path": str(mcp_path),
        "rule_path": str(rule_path) if rule_path else None,
        "dry_run": dry_run,
        "ok": True,
        "errors": [],
    }
    if workspace_mcp_path is not None:
        report["workspace_mcp_path"] = str(workspace_mcp_path)
        report["workspace_repo"] = str(workspace_root)

    if dry_run:
        report["would_write_mcp"] = str(mcp_path)
        report["would_write_rule"] = str(rule_path) if rule_path else None
        if workspace_mcp_path is not None:
            report["would_write_workspace_mcp"] = str(workspace_mcp_path)
        return report

    # Write MCP config
    try:
        if tool.slug == "kiro":
            paths = write_kiro_mcp(workspace_root)
            report["mcp_path"] = paths["user"]
            report["workspace_mcp_path"] = paths["project"]
            report["mcp_written"] = True
            report["workspace_mcp_written"] = True
        else:
            writer = _MCP_WRITERS.get(tool.mcp_format)
            if writer:
                writer(mcp_path, tool.mcp_key, entry)
                report["mcp_written"] = True
            else:
                report["mcp_written"] = False
                report["errors"].append(f"unsupported mcp_format: {tool.mcp_format}")
    except Exception as exc:
        report["mcp_written"] = False
        report["errors"].append(f"mcp write failed: {exc}")
        report["ok"] = False

    # Write rule
    if rule_path and tool.rule_format != "none":
        try:
            rule_writer = _RULE_WRITERS.get(tool.rule_format)
            if rule_writer:
                rule_writer(rule_path)
                report["rule_written"] = True
            else:
                report["rule_written"] = False
                report["errors"].append(f"unsupported rule_format: {tool.rule_format}")
        except Exception as exc:
            report["rule_written"] = False
            report["errors"].append(f"rule write failed: {exc}")
            report["ok"] = False
    else:
        report["rule_written"] = None  # not applicable

    return report


def install_tools(
    slugs: list[str],
    *,
    dry_run: bool = False,
    repo: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Install for multiple tools. Returns list of reports."""
    results = []
    for slug in slugs:
        tool = TOOL_MAP.get(slug)
        if not tool:
            results.append({"tool": slug, "ok": False, "errors": [f"unknown tool: {slug}"]})
            continue
        results.append(install_tool(tool, dry_run=dry_run, repo=repo))
    return results


# ---------------------------------------------------------------------------
# MCP config removers (per format)
# ---------------------------------------------------------------------------

def _remove_mcp_json(path: Path, key: str) -> bool:
    """Remove context-engine from a JSON MCP config. Returns True if removed."""
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    servers = data.get(key, {})
    if not isinstance(servers, dict) or "context-engine" not in servers:
        return False
    del servers["context-engine"]
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def _remove_mcp_toml(path: Path, _key: str) -> bool:
    """Remove context-engine section from a TOML config."""
    if not path.is_file():
        return False
    existing = path.read_text(encoding="utf-8")
    if "[mcp_servers.context-engine]" not in existing:
        return False
    new_lines = []
    skip = False
    for line in existing.splitlines():
        if line.strip() == "[mcp_servers.context-engine]":
            skip = True
            continue
        if skip and line.startswith("["):
            skip = False
        if not skip:
            new_lines.append(line)
    # Strip trailing blank lines from removal
    while new_lines and not new_lines[-1].strip():
        new_lines.pop()
    new_lines.append("")
    path.write_text("\n".join(new_lines), encoding="utf-8")
    return True


def _remove_mcp_yaml(path: Path, _key: str) -> bool:
    """Remove context-engine block from a YAML config."""
    if not path.is_file():
        return False
    existing = path.read_text(encoding="utf-8")
    marker = "# context-engine"
    if marker not in existing:
        return False
    lines = existing.splitlines()
    new_lines = []
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


_MCP_REMOVERS = {
    "json": _remove_mcp_json,
    "jsonc": _remove_mcp_json,
    "toml": _remove_mcp_toml,
    "yaml": _remove_mcp_yaml,
}


# ---------------------------------------------------------------------------
# Rule removers
# ---------------------------------------------------------------------------

def _remove_rule_file(path: Path) -> bool:
    """Delete a standalone rule file (mdc or md format)."""
    if not path.is_file():
        return False
    path.unlink()
    return True


def _remove_rule_section(path: Path) -> bool:
    """Remove the context-engine section from an append-md file."""
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


# ---------------------------------------------------------------------------
# Public uninstaller
# ---------------------------------------------------------------------------

def uninstall_tool(
    tool: ToolDef,
    *,
    dry_run: bool = False,
    repo: Path | str | None = None,
) -> dict[str, Any]:
    """Remove MCP config entry + rule for one tool. Returns a report dict."""
    mcp_path = resolve_mcp_path(tool)
    rule_path = resolve_rule_path(tool)
    workspace_root = Path(repo or Path.cwd()).resolve() if tool.slug == "kiro" else None
    workspace_mcp_path = workspace_root / tool.mcp_path if workspace_root else None

    report: dict[str, Any] = {
        "tool": tool.name,
        "slug": tool.slug,
        "mcp_path": str(mcp_path),
        "rule_path": str(rule_path) if rule_path else None,
        "dry_run": dry_run,
        "ok": True,
        "errors": [],
        "mcp_removed": False,
        "rule_removed": False,
    }
    if workspace_mcp_path is not None:
        report["workspace_mcp_path"] = str(workspace_mcp_path)

    if dry_run:
        report["would_remove_mcp"] = str(mcp_path)
        report["would_remove_rule"] = str(rule_path) if rule_path else None
        if workspace_mcp_path is not None:
            report["would_remove_workspace_mcp"] = str(workspace_mcp_path)
        return report

    # Remove MCP config entry
    try:
        if tool.slug == "kiro":
            # Remove from both user and workspace level
            user_path = Path.home() / ".kiro" / "settings" / "mcp.json"
            removed_user = _remove_mcp_json(user_path, tool.mcp_key)
            removed_project = False
            if workspace_mcp_path:
                removed_project = _remove_mcp_json(workspace_mcp_path, tool.mcp_key)
            report["mcp_removed"] = removed_user or removed_project
            if removed_user:
                report["user_mcp_removed"] = True
            if removed_project:
                report["workspace_mcp_removed"] = True
        elif tool.slug == "cursor":
            removed = _remove_mcp_json(mcp_path, tool.mcp_key)
            report["mcp_removed"] = removed
            # Legacy name from pre-0.2.54 connect (before rule unification).
            legacy_rule = Path.home() / ".cursor" / "rules" / "context-engine.mdc"
            if legacy_rule.is_file():
                legacy_rule.unlink()
                report["legacy_rule_removed"] = str(legacy_rule)
        else:
            remover = _MCP_REMOVERS.get(tool.mcp_format)
            if remover:
                report["mcp_removed"] = remover(mcp_path, tool.mcp_key)
            else:
                report["errors"].append(f"unsupported mcp_format: {tool.mcp_format}")
    except Exception as exc:
        report["errors"].append(f"mcp removal failed: {exc}")
        report["ok"] = False

    # Remove rule
    if rule_path and tool.rule_format != "none":
        try:
            rule_remover = _RULE_REMOVERS.get(tool.rule_format)
            if rule_remover:
                report["rule_removed"] = rule_remover(rule_path)
            else:
                report["errors"].append(f"unsupported rule_format: {tool.rule_format}")
        except Exception as exc:
            report["errors"].append(f"rule removal failed: {exc}")
            report["ok"] = False
    else:
        report["rule_removed"] = None  # not applicable

    return report


def uninstall_tools(
    slugs: list[str],
    *,
    dry_run: bool = False,
    repo: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Uninstall for multiple tools. Returns list of reports."""
    results = []
    for slug in slugs:
        tool = TOOL_MAP.get(slug)
        if not tool:
            results.append({"tool": slug, "ok": False, "errors": [f"unknown tool: {slug}"]})
            continue
        results.append(uninstall_tool(tool, dry_run=dry_run, repo=repo))
    return results
