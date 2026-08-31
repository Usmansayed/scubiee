"""Cross-host MCP tool permission presets for Scubiee locate tools.

Each AI host implements approvals differently (embedded MCP fields, sidecar JSON,
host settings, or UI-only). This module applies the best available mechanism per
tool so agents can run read-only Scubiee locate without repeated prompts.

Research sources (2026):
- Cursor: permissions.json mcpAllowlist (server:tool)
- Claude Code: settings.json permissions.allow mcp__server__tool
- Cline/Roo: mcpServers.autoApprove / alwaysAllow
- Copilot CLI: mcpServers.tools wildcard
- OpenCode/chatcli: autoApprove on server entry
- Continue: ~/.continue/permissions.yaml (UI-managed; we ship a merge template)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pipeline.branding import MCP_SERVER_NAME

PermissionProfile = Literal["locate", "all"]

# Phase surface (default product MCP tools) — read-only locate/navigation.
PHASE_LOCATE_TOOLS: tuple[str, ...] = (
    "gate",
    "map",
    "focus",
    "grep",
    "glob",
    "workspace",
    "expand",
    "status",
)

# Legacy / rich surfaces — still read-only for typical use.
LEGACY_LOCATE_TOOLS: tuple[str, ...] = (
    "search",
    "files",
    "read",
    "recall",
    "neighbors",
    "graph",
    "outline",
)

PermissionMechanism = Literal[
    "embedded_mcp",  # autoApprove / alwaysAllow / tools on server block
    "sidecar_json",  # separate host settings file
    "sidecar_yaml",  # Continue-style permissions template
    "docs_only",  # host has no file API — instructions only
    "already_builtin",  # connect already sets wildcard (copilot CLI)
]


@dataclass(frozen=True)
class ToolPermissionPlan:
    slug: str
    mechanism: PermissionMechanism
    sidecar_paths: tuple[str, ...] = ()
    notes: str = ""


# Hosts that accept autoApprove/alwaysAllow on the mcpServers entry (Claude-style JSON).
_EMBEDDED_MCP_SLUGS: frozenset[str] = frozenset(
    {
        "cline",
        "roo-code",
        "cursor",
        "kiro",
        "devin-desktop",
        "pi",
        "claude-code",
    }
)

_TOOL_PLANS: dict[str, ToolPermissionPlan] = {
    "cursor": ToolPermissionPlan(
        slug="cursor",
        mechanism="sidecar_json",
        sidecar_paths=(".cursor/permissions.json",),
        notes="Cursor Run Mode + mcpAllowlist; also embedded autoApprove on MCP entry.",
    ),
    "claude-code": ToolPermissionPlan(
        slug="claude-code",
        mechanism="sidecar_json",
        sidecar_paths=(".claude/settings.json",),
        notes="Claude Code permissions.allow mcp__scubiee__* rules.",
    ),
    "codex": ToolPermissionPlan(
        slug="codex",
        mechanism="docs_only",
        sidecar_paths=(".codex/SCUBIEE_MCP_PERMISSIONS.md",),
        notes="Codex has no stable MCP auto-approve file; AGENTS.md + doc stub.",
    ),
    "copilot": ToolPermissionPlan(
        slug="copilot",
        mechanism="already_builtin",
        notes="Copilot CLI entry uses tools:[*]; VS Code uses host UI.",
    ),
    "continue": ToolPermissionPlan(
        slug="continue",
        mechanism="sidecar_yaml",
        sidecar_paths=(
            ".continue/scubiee-permissions.yaml",
            ".continue/SCUBIEE_MCP_PERMISSIONS.md",
        ),
        notes="Continue stores policies in ~/.continue/permissions.yaml — template provided.",
    ),
    "opencode": ToolPermissionPlan(
        slug="opencode",
        mechanism="embedded_mcp",
        notes="OpenCode supports autoApprove on MCP server entries.",
    ),
    "zed": ToolPermissionPlan(
        slug="zed",
        mechanism="docs_only",
        sidecar_paths=(".zed/SCUBIEE_MCP_PERMISSIONS.md",),
        notes="Zed MCP approvals are host UI settings.",
    ),
    "amp": ToolPermissionPlan(
        slug="amp",
        mechanism="docs_only",
        sidecar_paths=(".amp/SCUBIEE_MCP_PERMISSIONS.md",),
        notes="Amp global install skips workspace approval; use host UI if prompted.",
    ),
}

for _slug in _EMBEDDED_MCP_SLUGS:
    _TOOL_PLANS.setdefault(
        _slug,
        ToolPermissionPlan(
            slug=_slug,
            mechanism="embedded_mcp",
            notes="autoApprove + alwaysAllow on mcpServers.scubiee",
        ),
    )


def locate_tool_names(*, profile: PermissionProfile = "locate") -> list[str]:
    if profile == "all":
        return list(PHASE_LOCATE_TOOLS) + list(LEGACY_LOCATE_TOOLS)
    return list(PHASE_LOCATE_TOOLS)


def tool_permission_plan(slug: str) -> ToolPermissionPlan | None:
    return _TOOL_PLANS.get(slug)


def _merge_unique_strings(existing: list[str], additions: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in [*existing, *additions]:
        key = str(item).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def enrich_server_entry_permissions(
    entry: dict[str, Any],
    tool_slug: str,
    *,
    profile: PermissionProfile = "locate",
) -> dict[str, Any]:
    """Add host-native auto-approve fields to an MCP server block when supported."""
    plan = tool_permission_plan(tool_slug)
    if plan is None or plan.mechanism in {"already_builtin", "docs_only"}:
        return entry

    out = dict(entry)
    tools = locate_tool_names(profile=profile)

    if plan.mechanism == "embedded_mcp" or tool_slug in _EMBEDDED_MCP_SLUGS:
        out.setdefault("disabled", False)
        out["autoApprove"] = list(tools) if profile == "locate" else ["*"]
        out["alwaysAllow"] = list(out["autoApprove"])
        return out

    if tool_slug == "opencode":
        out["autoApprove"] = list(tools) if profile == "locate" else ["*"]
        out.setdefault("enabled", True)
        return out

    return out


def _cursor_mcp_allowlist(*, profile: PermissionProfile) -> list[str]:
    """Cursor permissions.json entries (server:tool syntax, case-insensitive)."""
    server = MCP_SERVER_NAME
    if profile == "all":
        return [f"{server}:*", "*:*"]
    entries = [f"{server}:*"]
    # Project-scoped Cursor namespaces sometimes prefix the server name — tool
    # wildcards keep locate tools unblocked even when the prefix differs.
    for tool in PHASE_LOCATE_TOOLS:
        entries.append(f"*:{tool}")
    return entries


def _claude_allow_rules(*, profile: PermissionProfile) -> list[str]:
    server = MCP_SERVER_NAME.replace("-", "_")
    if profile == "all":
        return [f"mcp__{server}__*"]
    return [f"mcp__{server}__{tool}" for tool in PHASE_LOCATE_TOOLS] + [
        f"mcp__{server}__*"
    ]


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_object(path: Path, document: dict[str, Any]) -> None:
    from pipeline.artifact_guard import atomic_write_text

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        path,
        json.dumps(document, indent=2, sort_keys=True) + "\n",
    )


def merge_cursor_permissions(
    path: Path,
    *,
    profile: PermissionProfile = "locate",
) -> dict[str, Any]:
    """Merge Scubiee entries into Cursor permissions.json without wiping user rules."""
    document = _load_json_object(path)
    additions = _cursor_mcp_allowlist(profile=profile)
    existing = document.get("mcpAllowlist")
    existing_list = existing if isinstance(existing, list) else []
    document["mcpAllowlist"] = _merge_unique_strings(
        [str(x) for x in existing_list],
        additions,
    )
    auto_run = document.get("autoRun")
    if not isinstance(auto_run, dict):
        auto_run = {}
    allow_instructions = auto_run.get("allow_instructions")
    instr_list = allow_instructions if isinstance(allow_instructions, list) else []
    instr_list = _merge_unique_strings(
        [str(x) for x in instr_list],
        [
            "Allow Scubiee MCP locate tools (gate, map, focus, grep, glob, "
            "workspace, expand, status) for read-only codebase navigation."
        ],
    )
    auto_run["allow_instructions"] = instr_list
    document["autoRun"] = auto_run
    _write_json_object(path, document)
    return {
        "ok": True,
        "path": str(path),
        "mcpAllowlist": document["mcpAllowlist"],
        "mechanism": "cursor_permissions_json",
    }


def merge_claude_settings_permissions(
    path: Path,
    *,
    profile: PermissionProfile = "locate",
) -> dict[str, Any]:
    """Merge mcp__scubiee__* allow rules into Claude Code settings.json."""
    document = _load_json_object(path)
    document.setdefault(
        "$schema",
        "https://json.schemastore.org/claude-code-settings.json",
    )
    permissions = document.get("permissions")
    if not isinstance(permissions, dict):
        permissions = {}
    allow = permissions.get("allow")
    allow_list = allow if isinstance(allow, list) else []
    permissions["allow"] = _merge_unique_strings(
        [str(x) for x in allow_list],
        _claude_allow_rules(profile=profile),
    )
    document["permissions"] = permissions
    _write_json_object(path, document)
    return {
        "ok": True,
        "path": str(path),
        "allow": permissions["allow"],
        "mechanism": "claude_settings_json",
    }


def _continue_permissions_yaml(*, profile: PermissionProfile) -> str:
    tools = locate_tool_names(profile=profile)
    lines = [
        "# Scubiee locate tool permissions for Continue",
        "# Continue reads persistent policies from ~/.continue/permissions.yaml",
        "# Merge the allow: section below into that file (or symlink this file).",
        "# Docs: https://docs.continue.dev/cli/tool-permissions",
        "",
        "allow:",
    ]
    for tool in tools:
        lines.append(f'  - "Mcp({MCP_SERVER_NAME}:{tool})"')
    if profile == "all":
        lines.append(f'  - "Mcp({MCP_SERVER_NAME}:*)"')
    lines.extend(
        [
            "",
            "ask: []",
            "exclude: []",
            "",
        ]
    )
    return "\n".join(lines)


def _permissions_readme(tool_name: str, *, extra: str = "") -> str:
    body = (
        f"# Scubiee MCP permissions ({tool_name})\n\n"
        "Scubiee locate tools are read-only (gate, map, focus, grep, glob, "
        "workspace, expand, status). Pre-approve them in your host so agents "
        "are not blocked with **permissions configuration** errors.\n\n"
    )
    if extra:
        body += extra + "\n\n"
    body += (
        "Re-run from the repo root:\n\n"
        "```bash\n"
        "scubiee connect --cursor\n"
        "# or reconnect all hosts:\n"
        "scubiee connect --all\n"
        "```\n"
    )
    return body


def write_tool_permission_artifacts(
    tool_slug: str,
    repo: Path | str,
    *,
    profile: PermissionProfile = "locate",
    dry_run: bool = False,
    include_user_home: bool | None = None,
) -> dict[str, Any]:
    """Write sidecar permission files for one connected tool under ``repo``."""
    root = Path(repo).resolve()
    plan = tool_permission_plan(tool_slug)
    report: dict[str, Any] = {
        "ok": True,
        "slug": tool_slug,
        "repo": str(root),
        "profile": profile,
        "dry_run": dry_run,
        "artifacts": [],
        "skipped": False,
    }
    if plan is None:
        report["skipped"] = True
        report["skip_reason"] = "unknown tool"
        return report
    if plan.mechanism == "already_builtin":
        report["skipped"] = True
        report["skip_reason"] = plan.notes
        return report

    if include_user_home is None:
        include_user_home = os.environ.get("CTX_MCP_PERMISSIONS_USER", "").strip() in {
            "1",
            "true",
            "yes",
        }

    def _record(path: Path, action: str, detail: dict[str, Any] | None = None) -> None:
        item: dict[str, Any] = {"path": str(path), "action": action}
        if detail:
            item.update(detail)
        report["artifacts"].append(item)

    if tool_slug == "cursor":
        project_path = root / ".cursor" / "permissions.json"
        if dry_run:
            _record(project_path, "would_write")
        else:
            report["cursor"] = merge_cursor_permissions(project_path, profile=profile)
        if include_user_home:
            user_path = Path.home() / ".cursor" / "permissions.json"
            if dry_run:
                _record(user_path, "would_write_user")
            else:
                report["cursor_user"] = merge_cursor_permissions(
                    user_path, profile=profile
                )

    elif tool_slug == "claude-code":
        project_path = root / ".claude" / "settings.json"
        if dry_run:
            _record(project_path, "would_write")
        else:
            report["claude"] = merge_claude_settings_permissions(
                project_path, profile=profile
            )
        if include_user_home:
            user_path = Path.home() / ".claude" / "settings.json"
            if dry_run:
                _record(user_path, "would_write_user")
            else:
                report["claude_user"] = merge_claude_settings_permissions(
                    user_path, profile=profile
                )

    elif tool_slug == "continue":
        yaml_path = root / ".continue" / "scubiee-permissions.yaml"
        md_path = root / ".continue" / "SCUBIEE_MCP_PERMISSIONS.md"
        content = _continue_permissions_yaml(profile=profile)
        readme = _permissions_readme(
            "Continue",
            extra=(
                "Copy or merge `.continue/scubiee-permissions.yaml` into "
                "`~/.continue/permissions.yaml`, then restart Continue."
            ),
        )
        if dry_run:
            _record(yaml_path, "would_write")
            _record(md_path, "would_write")
        else:
            from pipeline.artifact_guard import atomic_write_text

            yaml_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(yaml_path, content)
            atomic_write_text(md_path, readme)
            _record(yaml_path, "written")
            _record(md_path, "written")

    elif tool_slug in {"codex", "zed", "amp"}:
        rel = plan.sidecar_paths[0] if plan.sidecar_paths else f".{tool_slug}/SCUBIEE_MCP_PERMISSIONS.md"
        doc_path = root / rel
        readme = _permissions_readme(
            tool_slug,
            extra=plan.notes,
        )
        if dry_run:
            _record(doc_path, "would_write")
        else:
            from pipeline.artifact_guard import atomic_write_text

            doc_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(doc_path, readme)
            _record(doc_path, "written")

    elif plan.mechanism == "embedded_mcp":
        report["skipped"] = True
        report["skip_reason"] = "embedded on mcpServers entry during connect"

    _write_permissions_manifest(root, tool_slug, report, dry_run=dry_run)
    return report


def _write_permissions_manifest(
    root: Path,
    tool_slug: str,
    perm_report: dict[str, Any],
    *,
    dry_run: bool,
) -> None:
    manifest_path = root / ".scubiee" / "mcp-permissions.json"
    if dry_run:
        perm_report.setdefault("artifacts", []).append(
            {"path": str(manifest_path), "action": "would_write_manifest"}
        )
        return
    existing = _load_json_object(manifest_path)
    tools = existing.get("tools")
    tools_map = tools if isinstance(tools, dict) else {}
    tools_map[tool_slug] = {
        "profile": perm_report.get("profile"),
        "plan": (
            tool_permission_plan(tool_slug).__dict__
            if tool_permission_plan(tool_slug)
            else None
        ),
        "artifacts": perm_report.get("artifacts"),
        "skipped": perm_report.get("skipped"),
    }
    existing["tools"] = tools_map
    existing["server"] = MCP_SERVER_NAME
    existing["locate_tools"] = locate_tool_names()
    _write_json_object(manifest_path, existing)


def apply_permissions_to_repo_tool_surface(
    tool_slug: str,
    repo: Path | str,
    *,
    profile: PermissionProfile = "locate",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Sidecar permission files for one tool + repo (called after MCP write)."""
    return write_tool_permission_artifacts(
        tool_slug,
        repo,
        profile=profile,
        dry_run=dry_run,
    )


def audit_permissions(repo: Path | str | None = None) -> dict[str, Any]:
    """Report permission artifact status for connected tools (doctor)."""
    from pipeline.connect_state import load_connected_tools
    from pipeline.tool_registry import TOOL_MAP

    root = Path(repo or Path.cwd()).resolve()
    slugs = load_connected_tools()
    checks: list[dict[str, Any]] = []
    ok = True
    for slug in slugs:
        tool = TOOL_MAP.get(slug)
        plan = tool_permission_plan(slug)
        item: dict[str, Any] = {"slug": slug, "ok": True, "plan": plan.__dict__ if plan else None}
        if plan is None:
            item["ok"] = False
            item["hint"] = "unknown tool"
            ok = False
            checks.append(item)
            continue
        if slug == "cursor":
            path = root / ".cursor" / "permissions.json"
            data = _load_json_object(path)
            allowlist = data.get("mcpAllowlist") if isinstance(data.get("mcpAllowlist"), list) else []
            has_scubiee = any(
                str(x).lower().startswith(f"{MCP_SERVER_NAME}:") or str(x).startswith("*:")
                for x in allowlist
            )
            item["path"] = str(path)
            item["configured"] = path.is_file() and has_scubiee
            if not item["configured"]:
                item["ok"] = False
                item["hint"] = f"Run: scubiee connect --cursor (writes {path})"
        elif slug == "claude-code":
            path = root / ".claude" / "settings.json"
            data = _load_json_object(path)
            perms = data.get("permissions") if isinstance(data.get("permissions"), dict) else {}
            allow = perms.get("allow") if isinstance(perms.get("allow"), list) else []
            prefix = f"mcp__{MCP_SERVER_NAME.replace('-', '_')}__"
            item["path"] = str(path)
            item["configured"] = any(str(x).startswith(prefix) for x in allow)
            if not item["configured"]:
                item["ok"] = False
                item["hint"] = "Run: scubiee connect --claude-code"
        elif slug == "continue":
            path = root / ".continue" / "scubiee-permissions.yaml"
            item["path"] = str(path)
            item["configured"] = path.is_file()
            if not item["configured"]:
                item["ok"] = False
                item["hint"] = "Run: scubiee connect --continue; merge yaml into ~/.continue/permissions.yaml"
        elif plan.mechanism == "embedded_mcp":
            mcp_path = None
            if tool is not None:
                from pipeline.tool_registry import resolve_mcp_project_paths

                paths = resolve_mcp_project_paths(tool, root)
                mcp_path = paths[0] if paths else None
            item["path"] = str(mcp_path) if mcp_path else None
            configured = False
            if mcp_path and mcp_path.is_file():
                try:
                    blob = json.loads(mcp_path.read_text(encoding="utf-8"))
                    servers = blob.get("mcpServers") if isinstance(blob, dict) else None
                    entry = servers.get(MCP_SERVER_NAME) if isinstance(servers, dict) else None
                    if isinstance(entry, dict):
                        aa = entry.get("autoApprove") or entry.get("alwaysAllow") or []
                        configured = bool(aa)
                except Exception:  # noqa: BLE001
                    configured = False
            item["configured"] = configured
            if not configured:
                item["ok"] = False
                item["hint"] = f"Re-run: scubiee connect --{slug}"
        elif plan.mechanism == "already_builtin":
            item["configured"] = True
            item["note"] = plan.notes
        elif plan.mechanism == "docs_only":
            rel = plan.sidecar_paths[0] if plan.sidecar_paths else ""
            path = root / rel if rel else None
            item["path"] = str(path) if path else None
            item["configured"] = bool(path and path.is_file())
            if not item["configured"]:
                item["ok"] = False
                item["hint"] = f"Run: scubiee connect --{slug}"
        else:
            item["configured"] = bool(plan.sidecar_paths)
        checks.append(item)
        if not item.get("ok", True):
            ok = False
    return {
        "ok": ok,
        "repo": str(root),
        "connected_tools": slugs,
        "checks": checks,
        "hint": (
            "Pre-approve Scubiee locate MCP tools to avoid Cursor/host "
            "'Blocked by permissions configuration' errors."
        ),
    }
