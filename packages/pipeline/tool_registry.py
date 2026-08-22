"""Registry of AI coding tools: MCP config paths, rules paths, and formats."""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ToolDef:
    """Definition of an AI coding tool's configuration locations."""

    name: str
    slug: str  # CLI flag name (e.g. "claude-code")
    mcp_path: str  # relative to home, or absolute template
    mcp_key: str  # top-level key in the MCP JSON ("mcpServers" or "servers")
    mcp_format: str  # "json" | "toml" | "yaml" | "jsonc"
    rule_path: str | None  # relative to home; None = no file-based rules
    rule_format: str  # "mdc" | "md" | "toml" | "yaml" | "append-md" | "none"
    rule_append: bool = False  # append to existing file vs overwrite
    rule_marker: str = "context-engine"  # idempotent section marker
    notes: str = ""


def _home() -> Path:
    return Path.home()


def _appdata() -> Path:
    """Windows %APPDATA% or fallback."""
    return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[ToolDef] = [
    ToolDef(
        name="Cursor",
        slug="cursor",
        mcp_path=".cursor/mcp.json",
        mcp_key="mcpServers",
        mcp_format="json",
        rule_path=".cursor/rules/context-engine.mdc",
        rule_format="mdc",
    ),
    ToolDef(
        name="Claude Code",
        slug="claude-code",
        mcp_path=".claude.json",
        mcp_key="mcpServers",
        mcp_format="json",
        rule_path=".claude/CLAUDE.md",
        rule_format="append-md",
        rule_append=True,
    ),
    ToolDef(
        name="Codex (OpenAI)",
        slug="codex",
        mcp_path=".codex/config.toml",
        mcp_key="mcp_servers",
        mcp_format="toml",
        rule_path=".codex/instructions.md",
        rule_format="append-md",
        rule_append=True,
    ),
    ToolDef(
        name="Kiro",
        slug="kiro",
        mcp_path=".kiro/settings/mcp.json",
        mcp_key="mcpServers",
        mcp_format="json",
        rule_path=".kiro/steering/context-engine.md",
        rule_format="md",
    ),
    ToolDef(
        name="Windsurf",
        slug="windsurf",
        mcp_path=".codeium/windsurf/mcp_config.json",
        mcp_key="mcpServers",
        mcp_format="json",
        rule_path=None,
        rule_format="none",
        notes="No file-based global rules; instruction is set in MCP server description.",
    ),
    ToolDef(
        name="VS Code / Copilot",
        slug="copilot",
        mcp_path=".vscode/mcp.json",
        mcp_key="servers",
        mcp_format="json",
        rule_path=".github/copilot-instructions.md",
        rule_format="append-md",
        rule_append=True,
    ),
    ToolDef(
        name="Cline",
        slug="cline",
        mcp_path=".cline/mcp.json",
        mcp_key="mcpServers",
        mcp_format="json",
        rule_path=".cline/rules/context-engine.md",
        rule_format="md",
    ),
    ToolDef(
        name="Roo Code",
        slug="roo-code",
        mcp_path=".cline/mcp.json",  # Roo is a Cline fork, same path
        mcp_key="mcpServers",
        mcp_format="json",
        rule_path=".cline/rules/context-engine.md",
        rule_format="md",
        notes="Roo Code uses Cline's config paths.",
    ),
    ToolDef(
        name="Continue",
        slug="continue",
        mcp_path=".continue/config.yaml",
        mcp_key="mcpServers",
        mcp_format="yaml",
        rule_path=".continue/rules/context-engine.md",
        rule_format="md",
    ),
    ToolDef(
        name="Zed",
        slug="zed",
        mcp_path=".config/zed/settings.json" if platform.system() != "Windows" else ".config/zed/settings.json",
        mcp_key="context_servers",
        mcp_format="json",
        rule_path=None,
        rule_format="none",
        notes="No standalone global rules file; instruction baked into server description.",
    ),
    ToolDef(
        name="OpenCode",
        slug="opencode",
        mcp_path=".config/opencode/config.json",
        mcp_key="mcp",
        mcp_format="json",
        rule_path=".config/opencode/instructions.md",
        rule_format="append-md",
        rule_append=True,
    ),
]

TOOL_MAP: dict[str, ToolDef] = {t.slug: t for t in TOOLS}
ALL_SLUGS: list[str] = [t.slug for t in TOOLS]


def get_tool(slug: str) -> ToolDef | None:
    return TOOL_MAP.get(slug)


def resolve_mcp_path(tool: ToolDef) -> Path:
    """Resolve the global (user-level) MCP config path for a tool."""
    return _home() / tool.mcp_path


def resolve_rule_path(tool: ToolDef) -> Path | None:
    """Resolve the global (user-level) rule file path for a tool."""
    if tool.rule_path is None:
        return None
    return _home() / tool.rule_path
