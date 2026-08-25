"""Registry of AI coding tools: global MCP + rules paths.

See docs/connect-global-mcp-research.md for sources (Win/Mac) researched 2026-08-23.

Most tools: connect writes user-global MCP + rules only (no CTX_REPO pin).

Kiro, Copilot, Cline, and Roo Code also need a workspace-local MCP file because
those hosts do not pass the open folder to user-global MCP spawns.
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ToolDef:
    """Definition of an AI coding tool's global configuration locations."""

    name: str
    slug: str
    mcp_schema: str  # claude | vscode | opencode | amp | codex | continue | zed | copilot_cli
    mcp_key: str
    mcp_format: str  # json | toml | yaml
    # Relative to home, or special token resolved in resolve_mcp_user_paths()
    mcp_user_path: str | None
    # Extra MCP paths (e.g. Cline CLI + VS Code) — same schema/key as primary
    mcp_user_path_extra: tuple[str, ...] = ()
    # Extra MCP writes with a different schema: (path_token, schema, key)
    mcp_alt_targets: tuple[tuple[str, str, str], ...] = ()
    rule_format: str = "none"  # mdc | md | append-md | none
    rule_user_path: str | None = None
    # Extra rule files (same rule_format as primary)
    rule_user_path_extra: tuple[str, ...] = ()
    notes: str = ""


def _is_windows() -> bool:
    return platform.system() == "Windows" or os.name == "nt"


def _is_darwin() -> bool:
    return platform.system() == "Darwin"


def _home() -> Path:
    return Path.home()


def _appdata() -> Path:
    return Path(os.environ.get("APPDATA") or (_home() / "AppData" / "Roaming"))


def _vscode_user_dir() -> Path:
    """VS Code User/ directory (Mac/Linux/Windows)."""
    if _is_windows():
        return _appdata() / "Code" / "User"
    if _is_darwin():
        return _home() / "Library" / "Application Support" / "Code" / "User"
    return _home() / ".config" / "Code" / "User"


def _vscode_global_storage(*parts: str) -> Path:
    return _vscode_user_dir().joinpath("globalStorage", *parts)


# ---------------------------------------------------------------------------
# Tool definitions (global only)
# ---------------------------------------------------------------------------

TOOLS: list[ToolDef] = [
    ToolDef(
        name="Cursor",
        slug="cursor",
        mcp_schema="claude",
        mcp_key="mcpServers",
        mcp_format="json",
        mcp_user_path=".cursor/mcp.json",
        rule_format="mdc",
        rule_user_path=".cursor/rules/context-agent.mdc",
        notes="Global MCP + machine-local ~/.cursor/rules/*.mdc (official help).",
    ),
    ToolDef(
        name="Claude Code",
        slug="claude-code",
        mcp_schema="claude",
        mcp_key="mcpServers",
        mcp_format="json",
        mcp_user_path=".claude.json",
        rule_format="append-md",
        rule_user_path=".claude/CLAUDE.md",
        notes="User-scope mcpServers in ~/.claude.json; append ~/.claude/CLAUDE.md.",
    ),
    ToolDef(
        name="Codex (OpenAI)",
        slug="codex",
        mcp_schema="codex",
        mcp_key="mcp_servers",
        mcp_format="toml",
        mcp_user_path=".codex/config.toml",
        rule_format="append-md",
        rule_user_path=".codex/AGENTS.md",
        notes="CODEX_HOME overrides ~/.codex. Official instructions file is AGENTS.md.",
    ),
    ToolDef(
        name="Kiro",
        slug="kiro",
        mcp_schema="claude",
        mcp_key="mcpServers",
        mcp_format="json",
        mcp_user_path=".kiro/settings/mcp.json",
        rule_format="md",
        rule_user_path=".kiro/steering/context-engine.md",
        notes="Global ~/.kiro + workspace .kiro/settings/mcp.json when connect runs from a project folder.",
    ),
    ToolDef(
        name="Windsurf",
        slug="windsurf",
        mcp_schema="claude",
        mcp_key="mcpServers",
        mcp_format="json",
        mcp_user_path=".codeium/windsurf/mcp_config.json",
        rule_format="none",
        notes="Cascade mcp_config.json is user-global.",
    ),
    ToolDef(
        name="VS Code / Copilot",
        slug="copilot",
        mcp_schema="vscode",
        mcp_key="servers",
        mcp_format="json",
        mcp_user_path="vscode_user_mcp",
        mcp_alt_targets=(("copilot_cli_mcp", "copilot_cli", "mcpServers"),),
        rule_format="append-md",
        rule_user_path=".copilot/copilot-instructions.md",
        rule_user_path_extra=(".copilot/instructions/context-engine.instructions.md",),
        notes=(
            "VS Code user mcp.json (servers+stdio) + Copilot CLI ~/.copilot/mcp-config.json "
            "(mcpServers+type:local) + global instructions. Also writes .vscode/mcp.json + "
            ".mcp.json per repo when connect runs from a project folder."
        ),
    ),
    ToolDef(
        name="Cline",
        slug="cline",
        mcp_schema="claude",
        mcp_key="mcpServers",
        mcp_format="json",
        mcp_user_path="cline_vscode",
        mcp_user_path_extra=("cline_cli",),
        rule_format="md",
        rule_user_path=".cline/rules/context-engine.md",
        notes="Writes VS Code globalStorage + ~/.cline CLI MCP globally; .cline/mcp.json per repo when connect runs from a project folder.",
    ),
    ToolDef(
        name="Roo Code",
        slug="roo-code",
        mcp_schema="claude",
        mcp_key="mcpServers",
        mcp_format="json",
        mcp_user_path="roo_vscode",
        rule_format="none",
        notes="VS Code globalStorage globally; .roo/mcp.json per repo when connect runs from a project folder.",
    ),
    ToolDef(
        name="Continue",
        slug="continue",
        mcp_schema="continue",
        mcp_key="mcpServers",
        mcp_format="yaml",
        mcp_user_path=".continue/config.yaml",
        rule_format="md",
        rule_user_path=".continue/rules/context-engine.md",
        notes="mcpServers is a YAML list of named objects.",
    ),
    ToolDef(
        name="Zed",
        slug="zed",
        mcp_schema="zed",
        mcp_key="context_servers",
        mcp_format="json",
        mcp_user_path="zed_settings",
        rule_format="none",
        notes="Mac/Linux ~/.config/zed; Windows %APPDATA%/Zed/settings.json.",
    ),
    ToolDef(
        name="OpenCode",
        slug="opencode",
        mcp_schema="opencode",
        mcp_key="mcp",
        mcp_format="json",
        mcp_user_path=".config/opencode/opencode.json",
        rule_format="append-md",
        rule_user_path=".config/opencode/AGENTS.md",
        notes="Global file is opencode.json; type=local, command[], environment.",
    ),
    ToolDef(
        name="Amp",
        slug="amp",
        mcp_schema="amp",
        mcp_key="amp.mcpServers",
        mcp_format="json",
        mcp_user_path=".config/amp/settings.json",
        rule_format="append-md",
        rule_user_path=".config/amp/AGENTS.md",
        notes="Literal dotted key amp.mcpServers; global skips workspace approval.",
    ),
    ToolDef(
        name="Pi",
        slug="pi",
        mcp_schema="claude",
        mcp_key="mcpServers",
        mcp_format="json",
        mcp_user_path=".pi/agent/mcp.json",
        rule_format="append-md",
        rule_user_path=".pi/agent/AGENTS.md",
        notes="Requires pi-mcp-adapter for MCP.",
    ),
]

TOOL_MAP: dict[str, ToolDef] = {t.slug: t for t in TOOLS}
ALL_SLUGS: list[str] = [t.slug for t in TOOLS]

# Hosts where user-global MCP cannot resolve the workspace (IDE spawn/cwd bugs).
# connect still writes global rules + global MCP, but also needs a per-repo file.
WORKSPACE_LOCAL_MCP_SLUGS: frozenset[str] = frozenset(
    {"kiro", "copilot", "cline", "roo-code"}
)

WORKSPACE_LOCAL_MCP_NOTICES: dict[str, str] = {
    "kiro": (
        "Kiro IDE cannot detect your workspace from global MCP alone. "
        "Run `scubiee connect --kiro` inside each project to write "
        "`.kiro/settings/mcp.json` (local MCP with CTX_REPO)."
    ),
    "copilot": (
        "VS Code / Copilot global MCP does not expand ${workspaceFolder}. "
        "Run `scubiee connect --copilot` inside each project to write "
        "`.vscode/mcp.json` and `.mcp.json` for that repo."
    ),
    "cline": (
        "Cline global MCP may spawn with the wrong working directory. "
        "Run `scubiee connect --cline` inside each project to write "
        "`.cline/mcp.json` for that repo."
    ),
    "roo-code": (
        "Roo Code global MCP may spawn with the wrong working directory. "
        "Run `scubiee connect --roo-code` inside each project to write "
        "`.roo/mcp.json` for that repo."
    ),
}


def get_tool(slug: str) -> ToolDef | None:
    return TOOL_MAP.get(slug)


def _resolve_token(token: str) -> Path:
    if token == "vscode_user_mcp":
        return _vscode_user_dir() / "mcp.json"
    if token == "cline_vscode":
        return _vscode_global_storage(
            "saoudrizwan.claude-dev", "settings", "cline_mcp_settings.json"
        )
    if token == "cline_cli":
        return _home() / ".cline" / "data" / "settings" / "cline_mcp_settings.json"
    if token == "roo_vscode":
        return _vscode_global_storage(
            "rooveterinaryinc.roo-cline", "settings", "mcp_settings.json"
        )
    if token == "zed_settings":
        if _is_windows():
            return _appdata() / "Zed" / "settings.json"
        return _home() / ".config" / "zed" / "settings.json"
    if token == "copilot_cli_mcp":
        return _home() / ".copilot" / "mcp-config.json"
    return _home() / token


def resolve_mcp_user_paths(tool: ToolDef) -> list[Path]:
    """All global MCP config paths to write for this tool (primary + extras + alts)."""
    paths: list[Path] = []
    if tool.mcp_user_path:
        paths.append(_resolve_token(tool.mcp_user_path))
    for extra in tool.mcp_user_path_extra:
        paths.append(_resolve_token(extra))
    for token, _schema, _key in tool.mcp_alt_targets:
        paths.append(_resolve_token(token))
    return paths


def resolve_mcp_write_targets(tool: ToolDef) -> list[tuple[Path, str, str]]:
    """(path, schema, key) for every global MCP file this tool writes."""
    targets: list[tuple[Path, str, str]] = []
    if tool.mcp_user_path:
        targets.append((_resolve_token(tool.mcp_user_path), tool.mcp_schema, tool.mcp_key))
    for extra in tool.mcp_user_path_extra:
        targets.append((_resolve_token(extra), tool.mcp_schema, tool.mcp_key))
    for token, schema, key in tool.mcp_alt_targets:
        targets.append((_resolve_token(token), schema, key))
    return targets


def resolve_rule_user_paths(tool: ToolDef) -> list[Path]:
    paths: list[Path] = []
    if tool.rule_user_path:
        paths.append(_home() / tool.rule_user_path)
    for extra in tool.rule_user_path_extra:
        paths.append(_home() / extra)
    return paths


def resolve_mcp_user_path(tool: ToolDef) -> Path | None:
    """Primary global MCP path (first)."""
    paths = resolve_mcp_user_paths(tool)
    return paths[0] if paths else None


def resolve_rule_user_path(tool: ToolDef) -> Path | None:
    paths = resolve_rule_user_paths(tool)
    return paths[0] if paths else None


# Back-compat aliases
def resolve_mcp_path(tool: ToolDef) -> Path:
    primary = resolve_mcp_user_path(tool)
    if primary is not None:
        return primary
    return _home() / ".mcp.json"


def resolve_rule_path(tool: ToolDef) -> Path | None:
    return resolve_rule_user_path(tool)


def is_workspace_local_mcp_tool(slug: str) -> bool:
    return slug in WORKSPACE_LOCAL_MCP_SLUGS


def resolve_mcp_project_paths(tool: ToolDef, repo: Path | None) -> list[Path]:
    """Workspace-local MCP files written by connect for broken global hosts."""
    if repo is None or not is_workspace_local_mcp_tool(tool.slug):
        return []
    root = Path(repo).resolve()
    if tool.slug == "kiro":
        return [root / ".kiro" / "settings" / "mcp.json"]
    if tool.slug == "copilot":
        return [root / ".vscode" / "mcp.json", root / ".mcp.json"]
    if tool.slug == "cline":
        return [root / ".cline" / "mcp.json"]
    if tool.slug == "roo-code":
        return [root / ".roo" / "mcp.json"]
    return []


def resolve_mcp_project_path(tool: ToolDef, repo: Path | None) -> Path | None:
    paths = resolve_mcp_project_paths(tool, repo)
    return paths[0] if paths else None


def all_workspace_local_mcp_paths(repo: Path | None) -> list[Path]:
    """Every workspace-local MCP path connect may write for the special-4 hosts."""
    if repo is None:
        return []
    root = Path(repo).resolve()
    return [
        root / ".kiro" / "settings" / "mcp.json",
        root / ".vscode" / "mcp.json",
        root / ".mcp.json",
        root / ".cline" / "mcp.json",
        root / ".roo" / "mcp.json",
    ]


def resolve_rule_project_path(tool: ToolDef, repo: Path | None) -> Path | None:
    """Global-only install: never writes project rules."""
    return None
