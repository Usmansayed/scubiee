"""Per-host MCP workspace discovery and global vs special-4 classification.

Research: docs/global-mcp-hosts-research.md

Global MCP tools work with ``scubiee connect`` once (no per-repo MCP pin).
Special-4 tools (Kiro, Copilot, Cline, Roo) need project-level MCP or connect
from inside each repo — see docs/mcp-workspace-resolution-issue.md.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HostWorkspaceSpec:
    """How a host tells Scubiee which repo is open."""

    slug: str
    name: str
    workspace_env_keys: tuple[str, ...]
    global_connect: bool
    discovery: str  # env | cwd | env_or_cwd | project_mcp_required
    notes: str = ""


# Hosts that cannot resolve workspace from user-global MCP alone.
SPECIAL_WORKSPACE_LOCAL_MCP_SLUGS: frozenset[str] = frozenset(
    {"kiro", "copilot", "cline", "roo-code"}
)

_HOST_SPECS: tuple[HostWorkspaceSpec, ...] = (
    HostWorkspaceSpec(
        slug="cursor",
        name="Cursor",
        workspace_env_keys=(
            "CURSOR_PROJECT_DIR",
            "CURSOR_WORKSPACE",
            "CURSOR_CWD",
            "WORKSPACE_FOLDER_PATHS",
        ),
        global_connect=True,
        discovery="env",
        notes="Official spawn env; WORKSPACE_FOLDER_PATHS when sidebar multi-root.",
    ),
    HostWorkspaceSpec(
        slug="claude-code",
        name="Claude Code",
        workspace_env_keys=("CLAUDE_PROJECT_DIR", "CLAUDE_CODE_PROJECT_DIR"),
        global_connect=True,
        discovery="env",
        notes="Official CLAUDE_PROJECT_DIR on MCP child; do not trust process cwd.",
    ),
    HostWorkspaceSpec(
        slug="codex",
        name="Codex (OpenAI)",
        workspace_env_keys=("CODEX_WORKSPACE_ROOT",),
        global_connect=True,
        discovery="env_or_cwd",
        notes="CLI cwd OK; Desktop/IDE uses CODEX_WORKSPACE_ROOT or project cwd.",
    ),
    HostWorkspaceSpec(
        slug="windsurf",
        name="Windsurf",
        workspace_env_keys=("CODEIUM_WINDSURF_WORKSPACE", "WINDSURF_WORKSPACE"),
        global_connect=True,
        discovery="env_or_cwd",
        notes="Global ~/.codeium/windsurf/mcp_config.json; Cascade cwd often project root.",
    ),
    HostWorkspaceSpec(
        slug="continue",
        name="Continue",
        workspace_env_keys=("CONTINUE_PROJECT_DIR", "CONTINUE_WORKSPACE"),
        global_connect=True,
        discovery="env_or_cwd",
        notes="VS Code extension may also inject VSCODE_WORKSPACE_FOLDER.",
    ),
    HostWorkspaceSpec(
        slug="zed",
        name="Zed",
        workspace_env_keys=("ZED_PROJECT_DIR", "ZED_WORKSPACE"),
        global_connect=True,
        discovery="env_or_cwd",
        notes="Project-scoped context_servers use project root cwd; global may be $HOME.",
    ),
    HostWorkspaceSpec(
        slug="opencode",
        name="OpenCode",
        workspace_env_keys=("OPENCODE_DEFAULT_PROJECT", "OPENCODE_PROJECT"),
        global_connect=True,
        discovery="env_or_cwd",
        notes="CLI --dir sets cwd; global opencode.json without project override.",
    ),
    HostWorkspaceSpec(
        slug="amp",
        name="Amp",
        workspace_env_keys=("AMP_PROJECT_DIR", "AMP_WORKSPACE"),
        global_connect=True,
        discovery="env_or_cwd",
        notes="Global ~/.config/amp/settings.json skips workspace approval.",
    ),
    HostWorkspaceSpec(
        slug="pi",
        name="Pi",
        workspace_env_keys=("PI_PROJECT_DIR", "PI_WORKSPACE"),
        global_connect=True,
        discovery="env_or_cwd",
        notes="Launched from repo dir when using pi agent in project.",
    ),
    HostWorkspaceSpec(
        slug="kiro",
        name="Kiro",
        workspace_env_keys=("KIRO_PROJECT_DIR", "KIRO_WORKSPACE"),
        global_connect=False,
        discovery="project_mcp_required",
        notes="Spawns from install dir; needs .kiro/settings/mcp.json per repo.",
    ),
    HostWorkspaceSpec(
        slug="copilot",
        name="VS Code / Copilot",
        workspace_env_keys=("COPILOT_WORKSPACE_FOLDER", "COPILOT_WORKSPACE"),
        global_connect=False,
        discovery="project_mcp_required",
        notes="User mcp.json does not expand ${workspaceFolder}; needs .vscode/mcp.json.",
    ),
    HostWorkspaceSpec(
        slug="cline",
        name="Cline",
        workspace_env_keys=("CLINE_PROJECT_DIR", "CLINE_WORKSPACE"),
        global_connect=False,
        discovery="project_mcp_required",
        notes="GlobalStorage spawn cwd unreliable; needs .cline/mcp.json per repo.",
    ),
    HostWorkspaceSpec(
        slug="roo-code",
        name="Roo Code",
        workspace_env_keys=("ROO_PROJECT_DIR", "ROO_WORKSPACE"),
        global_connect=False,
        discovery="project_mcp_required",
        notes="Same VS Code-family cwd issue as Cline; needs .roo/mcp.json per repo.",
    ),
)

HOST_SPECS: dict[str, HostWorkspaceSpec] = {s.slug: s for s in _HOST_SPECS}

# Shared fallbacks (VS Code family, npm INIT_CWD, etc.)
_SHARED_WORKSPACE_ENV_KEYS: tuple[str, ...] = (
    "VSCODE_WORKSPACE_FOLDER",
    "VSCODE_CWD",
    "WORKSPACE_FOLDER",
    "INIT_CWD",
)

GLOBAL_MCP_TOOL_SLUGS: frozenset[str] = frozenset(
    s.slug for s in _HOST_SPECS if s.global_connect
)


def host_env_signals() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """(slug, env_keys) for session_isolation.detect_mcp_host."""
    vscode_keys = ("VSCODE_WORKSPACE_FOLDER", "VSCODE_CWD", "WORKSPACE_FOLDER_PATHS")
    out: list[tuple[str, tuple[str, ...]]] = []
    for spec in _HOST_SPECS:
        keys = spec.workspace_env_keys
        if spec.slug == "copilot":
            keys = keys + vscode_keys
        out.append((spec.slug, keys))
    out.append(("vscode", vscode_keys))
    return tuple(out)


def ide_workspace_env_keys() -> tuple[str, ...]:
    """Ordered env keys for mcp_locate repo resolution (first match wins)."""
    seen: set[str] = set()
    ordered: list[str] = []
    for spec in _HOST_SPECS:
        for key in spec.workspace_env_keys:
            if key not in seen:
                seen.add(key)
                ordered.append(key)
    for key in _SHARED_WORKSPACE_ENV_KEYS:
        if key not in seen:
            seen.add(key)
            ordered.append(key)
    return tuple(ordered)


def global_mcp_slugs() -> frozenset[str]:
    return GLOBAL_MCP_TOOL_SLUGS


def is_global_mcp_tool(slug: str) -> bool:
    return slug in GLOBAL_MCP_TOOL_SLUGS


def is_special_workspace_local_tool(slug: str) -> bool:
    return slug in SPECIAL_WORKSPACE_LOCAL_MCP_SLUGS
