"""Install global MCP config + rules for AI coding tools.

Usage from CLI:
    ctx install rules --cursor --claude-code --kiro --copilot
    ctx install rules --all
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path
from typing import Any

from pipeline.mcp_install import interpreter, server_entry
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
    """Cursor MDC format with frontmatter."""
    path = _templates_dir() / "context-engine.mdc"
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

def install_tool(
    tool: ToolDef,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Install MCP config + rule for one tool. Returns a report dict."""
    mcp_path = resolve_mcp_path(tool)
    rule_path = resolve_rule_path(tool)
    entry = server_entry()  # uses current Python interpreter

    report: dict[str, Any] = {
        "tool": tool.name,
        "slug": tool.slug,
        "mcp_path": str(mcp_path),
        "rule_path": str(rule_path) if rule_path else None,
        "dry_run": dry_run,
        "ok": True,
        "errors": [],
    }

    if dry_run:
        report["would_write_mcp"] = str(mcp_path)
        report["would_write_rule"] = str(rule_path) if rule_path else None
        return report

    # Write MCP config
    try:
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
) -> list[dict[str, Any]]:
    """Install for multiple tools. Returns list of reports."""
    results = []
    for slug in slugs:
        tool = TOOL_MAP.get(slug)
        if not tool:
            results.append({"tool": slug, "ok": False, "errors": [f"unknown tool: {slug}"]})
            continue
        results.append(install_tool(tool, dry_run=dry_run))
    return results
