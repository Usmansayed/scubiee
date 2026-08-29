"""Connect Scubiee to AI coding tools — global MCP only.

Usage:
    scubiee connect --all
    scubiee connect --cursor --claude-code --codex

Connect writes user-global MCP configs only (no always-on rules).
Per-repo binding uses ``scubiee init`` (``.scubiee/id.json`` + compact GATE
rules under the repo). After connect or init, reload MCP in each host.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline.mcp_install import server_entry
from pipeline.tool_registry import (
    LEGACY_WORKSPACE_MCP_SLUGS,
    TOOL_MAP,
    ToolDef,
    is_workspace_local_mcp_tool,
    resolve_mcp_project_paths,
    resolve_mcp_user_path,
    resolve_mcp_user_paths,
    resolve_mcp_write_targets,
    resolve_rule_user_path,
    resolve_rule_user_paths,
)


def _templates_dir() -> Path:
    return Path(__file__).resolve().parent / "templates"


def _rule_content_md(*, gate_line: str | None = None) -> str:
    if gate_line:
        return _render_gate_rule_md(gate_line)
    return (_templates_dir() / "scubiee.md").read_text(encoding="utf-8")


def _rule_content_mdc(*, gate_line: str | None = None) -> str:
    if gate_line:
        return _render_gate_rule_mdc(gate_line)
    return (_templates_dir() / "scubiee.mdc").read_text(encoding="utf-8")


# Shared GATE rule bodies — bans live here only, not in MCP instructions.


def managed_gate_rule_body(gate_line: str, project_id: str) -> str:
    return (
        f"**GATE {gate_line}** — Managed repo. "
        "BAN native Grep/Glob/codebase-search/Task for locate. "
        "USE Scubiee `map`|`focus`|`grep`|`glob` only. "
        "Native Edit/Shell for edits and tests. "
        f"`project_id={project_id!r}`."
    )


def unmanaged_gate_rule_body(gate_line: str = "0") -> str:
    return (
        f"**GATE {gate_line or '0'}** — Not managed (no `scubiee init`). "
        "BAN Scubiee MCP locate tools (`map`, `focus`, `grep`, `glob`, `workspace`). "
        "USE native Grep/Glob/Read/codebase-search only. "
        "Run `scubiee init .` to enroll."
    )


def paused_gate_rule_body() -> str:
    return "**GATE p** — Paused. Tell user `scubiee resume`."


def _render_gate_rule_mdc(gate_line: str) -> str:
    """Project rule on init — tool bans only (trajectory is in MCP instructions)."""
    if gate_line == "p":
        return (
            "---\n"
            "description: Scubiee GATE p paused\n"
            "alwaysApply: true\n"
            "---\n\n"
            f"{paused_gate_rule_body()}\n"
        )
    if gate_line.startswith("1:"):
        pid = gate_line.split(":", 1)[1]
        return (
            "---\n"
            f"description: GATE {gate_line} Scubiee managed\n"
            "alwaysApply: true\n"
            "---\n\n"
            f"{managed_gate_rule_body(gate_line, pid)}\n"
        )
    return (
        "---\n"
        f"description: GATE {gate_line or '0'} Scubiee\n"
        "alwaysApply: true\n"
        "---\n\n"
        f"{unmanaged_gate_rule_body(gate_line)}\n"
    )


def _render_gate_rule_md(gate_line: str) -> str:
    if gate_line == "p":
        return f"{paused_gate_rule_body()}\n"
    if gate_line.startswith("1:"):
        pid = gate_line.split(":", 1)[1]
        return f"{managed_gate_rule_body(gate_line, pid)}\n"
    return f"{unmanaged_gate_rule_body(gate_line)}\n"


def gate_line_for_repo(repo: Path | str) -> str:
    """Gate line from repo ``.scubiee/id.json`` (for project rules, no daemon)."""
    from pipeline.pause_resume import is_paused
    from pipeline.project_id import read_id_file

    root = Path(repo).resolve()
    if is_paused():
        return "p"
    try:
        pid = read_id_file(root) or ""
        if pid:
            return f"1:{pid}"
    except Exception:  # noqa: BLE001
        pass
    return "0"


def _project_rules_eligible(repo: Path) -> bool:
    root = Path(repo).resolve()
    if (root / ".scubiee" / "id.json").is_file():
        return True
    if (root / ".git").is_dir():
        return True
    return False


from pipeline.branding import (
    CONTINUE_YAML_MARKER,
    MARKER_END,
    MARKER_START,
    MCP_SERVER_NAME,
    MCP_SERVER_NAMES,
    strip_legacy_mcp_keys,
)

_MARKER_START = MARKER_START
_MARKER_END = MARKER_END
_SERVER_NAME = MCP_SERVER_NAME

# Never put ${workspaceFolder} or an absolute CTX_REPO in *global* MCP.
# Absolute pin lives in project files only. Literal tokens poison resolution
# or crash spawn (Codex Windows os error 267).
_GLOBAL_OMIT_CTX_REPO_SLUGS: frozenset[str] = frozenset(TOOL_MAP)


def _is_absolute_repo_pin(value: str) -> bool:
    """True for real filesystem pins; false for ${workspaceFolder} tokens."""
    raw = (value or "").strip()
    if not raw or "${" in raw or "$(" in raw or "%{" in raw:
        return False
    try:
        return Path(raw).expanduser().is_absolute()
    except OSError:
        return False


def _inject_global_workspace_hints(tool: ToolDef, env: dict[str, str]) -> None:
    """Global MCP must not interpolate workspace tokens (hosts often leave them literal)."""
    if tool.slug in _GLOBAL_OMIT_CTX_REPO_SLUGS:
        return
    env.pop("CTX_REPO", None)


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
    env.setdefault("CTX_MCP_SESSION_ISOLATE", "1")
    env.setdefault("CTX_MCP_CLIENT", tool.slug)
    if not pin_repo:
        _inject_global_workspace_hints(tool, env)

    use_schema = schema or tool.mcp_schema
    if use_schema == "claude":
        return {"command": cmd, "args": args, "env": env}
    if use_schema == "vscode":
        # Global user mcp.json does not expand ${workspaceFolder}.
        # Project .vscode/mcp.json gets an absolute cwd + CTX_REPO pin.
        payload: dict[str, Any] = {
            "type": "stdio",
            "command": cmd,
            "args": args,
            "env": env,
        }
        if pin_repo and repo is not None:
            payload["cwd"] = str(Path(repo).resolve()).replace("\\", "/")
        return payload
    if use_schema == "copilot_cli":
        return {
            "type": "local",
            "command": cmd,
            "args": args,
            "env": env,
            "tools": ["*"],
        }
    if use_schema == "opencode":
        payload: dict[str, Any] = {
            "type": "local",
            "enabled": True,
            "command": [cmd, *args],
            "environment": env,
            "timeout": 120000,
        }
        if pin_repo and repo is not None:
            payload["cwd"] = str(Path(repo).resolve()).replace("\\", "/")
        return payload
    if use_schema == "amp":
        return {"command": cmd, "args": args, "env": env}
    if use_schema == "codex":
        # Global: no cwd — Codex CLI does not expand ${workspaceFolder}
        # (Windows: os error 267). Spawn inherits the CLI's project cwd.
        # Project pin: absolute cwd (Desktop / per-repo .codex/config.toml).
        payload: dict[str, Any] = {
            "command": cmd,
            "args": args,
            "env": env,
        }
        if pin_repo and repo is not None:
            payload["cwd"] = str(Path(repo).resolve()).replace("\\", "/")
        return payload
    if use_schema == "continue":
        out: dict[str, Any] = {
            "name": _SERVER_NAME,
            "command": cmd,
            "args": args,
            "env": env,
        }
        if pin_repo and repo is not None:
            out["cwd"] = str(Path(repo).resolve()).replace("\\", "/")
        return out
    if use_schema == "zed":
        return {"command": cmd, "args": args, "env": env}
    raise ValueError(f"unknown mcp_schema: {use_schema}")


def _connect_repo(repo: Path | str | None) -> Path:
    return Path(repo if repo is not None else Path.cwd()).resolve()


def _workspace_mcp_eligible(root: Path, *, explicit_repo: bool) -> bool:
    if explicit_repo:
        return True
    if (root / ".git").exists():
        return True
    if (root / ".scubiee" / "id.json").is_file():
        return True
    return False


def _write_workspace_mcp(tool: ToolDef, repo: Path) -> list[Path]:
    """Write repo-pinned MCP config(s) for hosts that break global discovery."""
    written: list[Path] = []
    slug = tool.slug

    if slug == "kiro":
        path = repo / ".kiro" / "settings" / "mcp.json"
        entry = format_server_entry(tool, repo, pin_repo=True)
        write_mcp_config(tool, path, entry)
        written.append(path)
        return written

    if slug == "copilot":
        vscode_path = repo / ".vscode" / "mcp.json"
        vscode_entry = format_server_entry(tool, repo, pin_repo=True, schema="vscode")
        write_mcp_config(tool, vscode_path, vscode_entry, schema="vscode", key="servers")

        root_mcp = repo / ".mcp.json"
        agent_entry = format_server_entry(tool, repo, pin_repo=True, schema="claude")
        _write_mcp_json_keyed(root_mcp, "mcpServers", agent_entry)
        written.extend([vscode_path, root_mcp])
        return written

    if slug == "cline":
        path = repo / ".cline" / "mcp.json"
        entry = format_server_entry(tool, repo, pin_repo=True)
        write_mcp_config(tool, path, entry)
        written.append(path)
        return written

    if slug == "roo-code":
        path = repo / ".roo" / "mcp.json"
        entry = format_server_entry(tool, repo, pin_repo=True)
        write_mcp_config(tool, path, entry)
        written.append(path)
        return written

    if slug == "cursor":
        path = repo / ".cursor" / "mcp.json"
        entry = format_server_entry(tool, repo, pin_repo=True)
        write_mcp_config(tool, path, entry)
        written.append(path)
        return written

    if slug == "codex":
        path = repo / ".codex" / "config.toml"
        entry = format_server_entry(tool, repo, pin_repo=True)
        write_mcp_config(tool, path, entry)
        written.append(path)
        return written

    if slug == "continue":
        path = repo / ".continue" / "mcpServers" / "scubiee.yaml"
        entry = format_server_entry(tool, repo, pin_repo=True)
        _write_continue_project_mcp(path, entry)
        written.append(path)
        return written

    if slug == "opencode":
        path = repo / "opencode.json"
        entry = format_server_entry(tool, repo, pin_repo=True)
        write_mcp_config(tool, path, entry)
        written.append(path)
        return written

    if slug == "amp":
        path = repo / ".amp" / "settings.json"
        entry = format_server_entry(tool, repo, pin_repo=True)
        write_mcp_config(tool, path, entry)
        written.append(path)
        return written

    if slug == "pi":
        path = repo / ".mcp.json"
        entry = format_server_entry(tool, repo, pin_repo=True)
        write_mcp_config(tool, path, entry)
        written.append(path)
        return written

    return written


def _remove_workspace_mcp(tool: ToolDef, repo: Path) -> bool:
    removed = False
    for path in resolve_mcp_project_paths(tool, repo):
        if not path.is_file():
            continue
        if tool.slug == "copilot" and path.name == "mcp.json" and path.parent == repo:
            removed = _remove_mcp_json_keyed(path, "mcpServers") or removed
        elif tool.slug == "copilot" and ".vscode" in path.parts:
            removed = remove_mcp_config(tool, path, schema="vscode", key="servers") or removed
        elif tool.slug == "continue" and path.suffix in {".yaml", ".yml"}:
            # Standalone Continue block file — delete when ours.
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if "scubiee" in text or "# scubiee" in text:
                path.unlink(missing_ok=True)
                removed = True
        else:
            removed = remove_mcp_config(tool, path) or removed
    return removed


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
    strip_legacy_mcp_keys(servers)
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
    strip_legacy_mcp_keys(servers)
    servers[_SERVER_NAME] = entry
    data["amp.mcpServers"] = servers
    _write_json(path, data)


def _write_mcp_zed(path: Path, entry: dict[str, Any]) -> None:
    data = _load_json(path)
    servers = data.get("context_servers")
    if not isinstance(servers, dict):
        servers = {}
    strip_legacy_mcp_keys(servers)
    servers[_SERVER_NAME] = {
        "command": entry["command"],
        "args": entry.get("args") or [],
        "env": entry.get("env") or {},
    }
    data["context_servers"] = servers
    _write_json(path, data)


def verify_mcp_configs(slugs: list[str]) -> list[dict[str, Any]]:
    """Verify MCP config files have a valid scubiee entry.

    For each tool slug, reads its MCP config file(s) and checks that the
    'scubiee' server entry exists with 'command' + 'args' keys.
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
    skip_headers = {f"[mcp_servers.{n}]" for n in MCP_SERVER_NAMES}
    if path.is_file():
        existing = path.read_text(encoding="utf-8")
        new_lines: list[str] = []
        skip = False
        for line in existing.splitlines():
            if line.strip() in skip_headers:
                skip = True
                continue
            if skip and line.startswith("["):
                skip = False
            if not skip:
                new_lines.append(line)
        lines = new_lines
    lines.append("")
    lines.append(f"[mcp_servers.{_SERVER_NAME}]")
    lines.append(f'command = "{entry["command"]}"')
    args_str = ", ".join(f'"{a}"' for a in entry.get("args", []))
    lines.append(f"args = [{args_str}]")
    cwd = entry.get("cwd")
    if cwd:
        lines.append(f'cwd = "{cwd}"')
    if entry.get("env"):
        env_parts = [f'{k} = "{v}"' for k, v in entry["env"].items()]
        lines.append(f"env = {{ {', '.join(env_parts)} }}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_mcp_continue_yaml(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    markers = (CONTINUE_YAML_MARKER,)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    lines = existing.splitlines()
    new_lines: list[str] = []
    skip = False
    for line in lines:
        if any(m in line for m in markers):
            skip = True
            continue
        if skip and line.strip() and not line.startswith(" ") and not line.startswith("\t"):
            skip = False
        if not skip:
            new_lines.append(line)
    while new_lines and not new_lines[-1].strip():
        new_lines.pop()
    new_lines.append("")
    new_lines.append(f"mcpServers:  {CONTINUE_YAML_MARKER}")
    new_lines.append(f"  - name: {entry.get('name', _SERVER_NAME)}")
    new_lines.append(f'    command: "{entry["command"]}"')
    args_yaml = ", ".join(f'"{a}"' for a in entry.get("args", []))
    new_lines.append(f"    args: [{args_yaml}]")
    if entry.get("cwd"):
        new_lines.append(f'    cwd: "{entry["cwd"]}"')
    if entry.get("env"):
        new_lines.append("    env:")
        for k, v in entry["env"].items():
            new_lines.append(f'      {k}: "{v}"')
    new_lines.append("")
    path.write_text("\n".join(new_lines), encoding="utf-8")


def _write_continue_project_mcp(path: Path, entry: dict[str, Any]) -> None:
    """Standalone Continue workspace block (`.continue/mcpServers/*.yaml`)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "name: Scubiee",
        "version: 0.0.1",
        "schema: v1",
        "mcpServers:",
        f"  - name: {entry.get('name', _SERVER_NAME)}",
        f'    command: "{entry["command"]}"',
    ]
    args_yaml = ", ".join(f'"{a}"' for a in entry.get("args", []))
    lines.append(f"    args: [{args_yaml}]")
    if entry.get("cwd"):
        lines.append(f'    cwd: "{entry["cwd"]}"')
    if entry.get("env"):
        lines.append("    env:")
        for k, v in entry["env"].items():
            lines.append(f'      {k}: "{v}"')
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


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

def _write_rule_mdc(path: Path, *, gate_line: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_rule_content_mdc(gate_line=gate_line), encoding="utf-8")


def _write_rule_md(path: Path, *, gate_line: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_rule_content_md(gate_line=gate_line), encoding="utf-8")


def _write_rule_append_md(path: Path, *, gate_line: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    existing = _strip_marked_sections(existing)
    content = _rule_content_md(gate_line=gate_line)
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
    "none": lambda _path, gate_line=None: None,
}


def _write_rule(tool: ToolDef, path: Path, *, gate_line: str | None = None) -> None:
    writer = _RULE_WRITERS.get(tool.rule_format)
    if writer:
        writer(path, gate_line=gate_line)


def write_project_gate_rules(
    repo: Path | str,
    *,
    dry_run: bool = False,
    slugs: list[str] | None = None,
) -> dict[str, Any]:
    """Write compact GATE tool-ban rules under the repo after ``scubiee init``.

    Bans (native vs Scubiee) live here only. Locate trajectory (map→focus→grep)
    lives in MCP server instructions when managed — not duplicated here.
    """
    root = Path(repo).resolve()
    gate = gate_line_for_repo(root)
    report: dict[str, Any] = {
        "repo": str(root),
        "gate_line": gate,
        "ok": True,
        "skipped": False,
        "written": [],
        "dry_run": dry_run,
        "errors": [],
    }
    if not _project_rules_eligible(root):
        report["skipped"] = True
        report["skip_reason"] = "not a project folder"
        return report
    if not gate.startswith("1:") and gate != "p":
        report["skipped"] = True
        report["skip_reason"] = "repo not enrolled"
        return report

    from pipeline.tool_registry import TOOL_MAP, resolve_rule_project_paths

    selected = TOOL_MAP.values()
    if slugs:
        selected = [TOOL_MAP[s] for s in slugs if s in TOOL_MAP]

    for tool in selected:
        if tool.rule_format == "none":
            continue
        for path in resolve_rule_project_paths(tool, root):
            if dry_run:
                report["written"].append(str(path))
                continue
            try:
                _write_rule(tool, path, gate_line=gate)
                report["written"].append(str(path))
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(f"{path}: {exc}")
                report["ok"] = False

    agents = root / "AGENTS.md"
    if dry_run:
        report["written"].append(str(agents))
    else:
        try:
            _write_rule_append_md(agents, gate_line=gate)
            report["written"].append(str(agents))
        except Exception as exc:  # noqa: BLE001
            report["errors"].append(f"{agents}: {exc}")
            report["ok"] = False

    return report


def cleanup_project_gate_rules(
    repo: Path | str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Remove repo-local Scubiee rule files/sections left by older init/connect."""
    root = Path(repo).resolve()
    report: dict[str, Any] = {
        "repo": str(root),
        "ok": True,
        "skipped": False,
        "removed": [],
        "dry_run": dry_run,
        "errors": [],
    }
    if not _project_rules_eligible(root):
        report["skipped"] = True
        report["skip_reason"] = "not a project folder"
        return report

    from pipeline.tool_registry import TOOL_MAP, resolve_rule_project_paths

    for tool in TOOL_MAP.values():
        if tool.rule_format == "none":
            continue
        remover = _RULE_REMOVERS.get(tool.rule_format)
        if not remover:
            continue
        for path in resolve_rule_project_paths(tool, root):
            if not path.is_file():
                continue
            if dry_run:
                report["removed"].append(str(path))
                continue
            try:
                if remover(path):
                    report["removed"].append(str(path))
                    _prune_empty_parents(path, stop_at=root)
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(f"{path}: {exc}")
                report["ok"] = False

    agents = root / "AGENTS.md"
    if agents.is_file():
        if dry_run:
            if _MARKER_START in agents.read_text(encoding="utf-8"):
                report["removed"].append(str(agents))
        else:
            try:
                if _remove_rule_section(agents):
                    report["removed"].append(str(agents))
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(f"{agents}: {exc}")
                report["ok"] = False

    report["gate_line"] = gate_line_for_repo(root)
    return report


def _prune_empty_parents(path: Path, *, stop_at: Path) -> None:
    """Remove empty dirs up to stop_at after deleting a scubiee-only rule file."""
    current = path.parent
    stop = stop_at.resolve()
    while current != stop and current.is_dir():
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _strip_marked_sections(existing: str) -> str:
    """Remove Scubiee (and legacy) marked rule sections from a file body."""
    text = existing
    for start, end in ((_MARKER_START, _MARKER_END),):
        if start not in text:
            continue
        before = text.split(start)[0]
        after = text.split(end)[-1] if end in text else ""
        text = before.rstrip() + ("\n\n" if before.strip() else "")
        if after.strip():
            text += after.lstrip()
    return text


# ---------------------------------------------------------------------------
# Public installer (global only)
# ---------------------------------------------------------------------------

def install_tool(
    tool: ToolDef,
    *,
    dry_run: bool = False,
    repo: Path | str | None = None,
) -> dict[str, Any]:
    """Install global MCP + rule; workspace-local MCP for project-pin hosts."""
    explicit_repo = repo is not None
    target_repo = _connect_repo(repo)
    write_targets = resolve_mcp_write_targets(tool)
    mcp_paths = [p for p, _s, _k in write_targets]
    rule_paths = resolve_rule_user_paths(tool)
    primary = mcp_paths[0] if mcp_paths else None
    primary_rule = rule_paths[0] if rule_paths else None
    workspace_local = is_workspace_local_mcp_tool(tool.slug)
    workspace_paths = resolve_mcp_project_paths(tool, target_repo) if workspace_local else []

    report: dict[str, Any] = {
        "tool": tool.name,
        "slug": tool.slug,
        "mcp_schema": tool.mcp_schema,
        "scope": "global",
        "mcp_path": str(primary) if primary else None,
        "mcp_paths": [str(p) for p in mcp_paths],
        "rule_path": str(primary_rule) if primary_rule else None,
        "rule_paths": [str(p) for p in rule_paths],
        "workspace_mcp_paths": [str(p) for p in workspace_paths],
        "dry_run": dry_run,
        "ok": True,
        "errors": [],
    }

    if workspace_local:
        report["repo"] = str(target_repo)
        eligible = _workspace_mcp_eligible(target_repo, explicit_repo=explicit_repo)
        report["workspace_mcp_eligible"] = eligible
        if not eligible:
            report["workspace_mcp_skipped"] = True
            report["workspace_mcp_skip_reason"] = (
                "not a project folder — cd into the repo (or pass --repo) and run connect again"
            )
    elif repo is not None:
        report["repo_ignored"] = True
        report["note"] = "connect is global-only for this tool; --repo is ignored"

    if dry_run:
        report["would_write_mcp"] = str(primary) if primary else None
        report["would_write_mcp_paths"] = [str(p) for p in mcp_paths]
        report["would_write_rule"] = str(primary_rule) if primary_rule else None
        report["would_write_rule_paths"] = [str(p) for p in rule_paths]
        if workspace_local and report.get("workspace_mcp_eligible"):
            report["would_write_workspace_mcp_paths"] = [str(p) for p in workspace_paths]
        return report

    try:
        if not write_targets:
            report["errors"].append(f"{tool.slug}: no global MCP path configured")
            report["ok"] = False
        else:
            for path, schema, key in write_targets:
                entry = format_server_entry(tool, pin_repo=False, schema=schema)
                write_mcp_config(tool, path, entry, schema=schema, key=key)
                env_blob = entry.get("env") or entry.get("environment") or {}
                ctx = str(env_blob.get("CTX_REPO") or "")
                if ctx and _is_absolute_repo_pin(ctx):
                    report["errors"].append(
                        "internal error: absolute CTX_REPO leaked into global entry"
                    )
                    report["ok"] = False
            report["mcp_written"] = True
    except Exception as exc:  # noqa: BLE001
        report["mcp_written"] = False
        report["errors"].append(f"mcp write failed: {exc}")
        report["ok"] = False

    if workspace_local and report.get("workspace_mcp_eligible"):
        try:
            written = _write_workspace_mcp(tool, target_repo)
            report["workspace_mcp_written"] = True
            report["workspace_mcp_paths"] = [str(p) for p in written]
        except Exception as exc:  # noqa: BLE001
            report["workspace_mcp_written"] = False
            report["errors"].append(f"workspace mcp write failed: {exc}")
            report["ok"] = False
    elif workspace_local:
        report["workspace_mcp_written"] = False

    if (
        not dry_run
        and tool.slug in LEGACY_WORKSPACE_MCP_SLUGS
        and _project_rules_eligible(target_repo)
    ):
        try:
            if _remove_workspace_mcp(tool, target_repo):
                report["legacy_workspace_mcp_removed"] = True
        except Exception as exc:  # noqa: BLE001
            report.setdefault("errors", []).append(f"legacy workspace mcp cleanup: {exc}")

    # Connect is MCP-only — project GATE rules are written on ``scubiee init``.
    report["rule_written"] = None
    report["rule_skipped"] = "connect is MCP-only; rules written on init"

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
    target = _connect_repo(repo)
    if _project_rules_eligible(target) and not dry_run:
        cleanup = cleanup_project_gate_rules(target)
        for r in results:
            if cleanup.get("gate_line"):
                r["gate_line"] = cleanup["gate_line"]
            removed = cleanup.get("removed") or []
            if removed:
                r["legacy_project_rules_removed"] = removed
            if cleanup.get("errors"):
                for err in cleanup["errors"]:
                    r.setdefault("errors", []).append(err)
                r["ok"] = False
    return results


# ---------------------------------------------------------------------------
# Removers
# ---------------------------------------------------------------------------

def _remove_mcp_json_keyed(path: Path, key: str) -> bool:
    if not path.is_file():
        return False
    data = _load_json(path)
    servers = data.get(key)
    if not isinstance(servers, dict):
        return False
    removed = False
    for name in MCP_SERVER_NAMES:
        if name in servers:
            del servers[name]
            removed = True
    if not removed:
        return False
    if servers:
        data[key] = servers
        _write_json(path, data)
    else:
        data.pop(key, None)
        if data:
            _write_json(path, data)
        else:
            path.unlink()
    return True


def _remove_mcp_amp(path: Path) -> bool:
    if not path.is_file():
        return False
    data = _load_json(path)
    servers = data.get("amp.mcpServers")
    if not isinstance(servers, dict):
        return False
    removed = False
    for name in MCP_SERVER_NAMES:
        if name in servers:
            del servers[name]
            removed = True
    if not removed:
        return False
    data["amp.mcpServers"] = servers
    _write_json(path, data)
    return True


def _remove_mcp_zed(path: Path) -> bool:
    return _remove_mcp_json_keyed(path, "context_servers")


def _remove_mcp_toml(path: Path) -> bool:
    if not path.is_file():
        return False
    existing = path.read_text(encoding="utf-8")
    skip_headers = {f"[mcp_servers.{n}]" for n in MCP_SERVER_NAMES}
    if not any(h in existing for h in skip_headers):
        return False
    new_lines: list[str] = []
    skip = False
    for line in existing.splitlines():
        if line.strip() in skip_headers:
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
    markers = (CONTINUE_YAML_MARKER,)
    if not any(m in existing for m in markers):
        return False
    lines = existing.splitlines()
    new_lines: list[str] = []
    skip = False
    for line in lines:
        if any(m in line for m in markers):
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
    result = _strip_marked_sections(existing).strip()
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


def _registered_connect_repos(extra: Path | None = None) -> list[Path]:
    """Repos where workspace-local MCP may have been written."""
    roots: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            return
        key = str(resolved).replace("\\", "/").lower()
        if key in seen:
            return
        seen.add(key)
        roots.append(resolved)

    try:
        from pipeline.project_id import load_registry

        for meta in (load_registry().get("projects") or {}).values():
            if not isinstance(meta, dict):
                continue
            for key in ("root",):
                raw = meta.get(key)
                if isinstance(raw, str) and raw.strip():
                    add(Path(raw))
            paths = meta.get("paths")
            if isinstance(paths, list):
                for raw in paths:
                    if isinstance(raw, str) and raw.strip():
                        add(Path(raw))
    except Exception:  # noqa: BLE001
        pass
    if extra is not None:
        add(Path(extra))
    add(Path.cwd())
    return roots


def uninstall_tool(
    tool: ToolDef,
    *,
    dry_run: bool = False,
    repo: Path | str | None = None,
    all_workspaces: bool = False,
) -> dict[str, Any]:
    target_repo = _connect_repo(repo)
    write_targets = resolve_mcp_write_targets(tool)
    mcp_paths = [p for p, _s, _k in write_targets]
    rule_paths = resolve_rule_user_paths(tool)
    primary = mcp_paths[0] if mcp_paths else None
    primary_rule = rule_paths[0] if rule_paths else None
    writes_legacy_workspace = tool.slug in LEGACY_WORKSPACE_MCP_SLUGS
    workspace_roots = (
        _registered_connect_repos(target_repo)
        if (writes_legacy_workspace and all_workspaces)
        else ([target_repo] if writes_legacy_workspace else [])
    )
    workspace_paths: list[Path] = []
    for root in workspace_roots:
        workspace_paths.extend(resolve_mcp_project_paths(tool, root))

    report: dict[str, Any] = {
        "tool": tool.name,
        "slug": tool.slug,
        "scope": "global",
        "mcp_path": str(primary) if primary else None,
        "mcp_paths": [str(p) for p in mcp_paths],
        "rule_path": str(primary_rule) if primary_rule else None,
        "rule_paths": [str(p) for p in rule_paths],
        "workspace_mcp_paths": [str(p) for p in workspace_paths],
        "all_workspaces": bool(all_workspaces and writes_legacy_workspace),
        "dry_run": dry_run,
        "ok": True,
        "errors": [],
        "mcp_removed": False,
        "rule_removed": False,
        "workspace_mcp_removed": False,
    }
    if writes_legacy_workspace:
        report["repo"] = str(target_repo)

    if dry_run:
        report["would_remove_mcp"] = str(primary) if primary else None
        report["would_remove_mcp_paths"] = [str(p) for p in mcp_paths]
        report["would_remove_rule"] = str(primary_rule) if primary_rule else None
        report["would_remove_rule_paths"] = [str(p) for p in rule_paths]
        if writes_legacy_workspace:
            report["would_remove_workspace_mcp_paths"] = [str(p) for p in workspace_paths]
        return report

    try:
        removed = False
        for path, schema, key in write_targets:
            removed = remove_mcp_config(tool, path, schema=schema, key=key) or removed
        report["mcp_removed"] = removed
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"mcp removal failed: {exc}")
        report["ok"] = False

    if writes_legacy_workspace:
        try:
            any_removed = False
            for root in workspace_roots:
                any_removed = _remove_workspace_mcp(tool, root) or any_removed
            report["workspace_mcp_removed"] = any_removed
        except Exception as exc:  # noqa: BLE001
            report["errors"].append(f"workspace mcp removal failed: {exc}")
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
    all_workspaces: bool = False,
) -> list[dict[str, Any]]:
    results = []
    for slug in slugs:
        tool = TOOL_MAP.get(slug)
        if not tool:
            results.append({"tool": slug, "ok": False, "errors": [f"unknown tool: {slug}"]})
            continue
        results.append(
            uninstall_tool(
                tool,
                dry_run=dry_run,
                repo=repo,
                all_workspaces=all_workspaces,
            )
        )
    return results
