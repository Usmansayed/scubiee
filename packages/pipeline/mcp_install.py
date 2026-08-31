"""Cursor MCP entry for an installed Scubiee package (no source tree)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def interpreter() -> str:
    """Python that can ``import pipeline`` for Cursor MCP.

    Do **not** ``Path.resolve()`` the executable: on macOS a venv's
    ``bin/python`` is a symlink into Homebrew's Cellar, and resolving it
    drops the venv ``site-packages`` → ``ModuleNotFoundError: pipeline``.
    Prefer ``CTX_PYTHON``, then ``sys.prefix``'s python, then ``sys.executable``
    as written (symlink preserved).
    """
    override = (os.environ.get("CTX_PYTHON") or "").strip()
    if override:
        return override.replace("\\", "/")
    if os.name == "nt":
        candidate = Path(sys.prefix) / "Scripts" / "python.exe"
    else:
        candidate = Path(sys.prefix) / "bin" / "python"
    if candidate.is_file():
        return str(candidate).replace("\\", "/")
    return str(Path(sys.executable)).replace("\\", "/")


def server_entry(
    repo: Path | str | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> dict[str, Any]:
    """MCP server block that works after `pip install scubiee`.

    Prefers ``scubiee-mcp-bridge`` (stable stdio proxy; hot-respawns workers after
    upgrade). Falls back to ``scubiee-mcp``, then ``python -m pipeline.mcp_locate``.
    """
    import shutil

    from pipeline.mcp_hot_reload import current_build_id, write_active_build_stamp

    engine_url = os.environ.get("CTX_ENGINE_URL") or f"http://{host}:{port}"
    from pipeline.settings import get_registration_mode

    reg_mode = get_registration_mode()
    env: dict[str, str] = {
        "CTX_ENGINE_URL": engine_url,
        "CTX_TOKEN_MODE": "savings",
        "CTX_BACKGROUND_SYNC": "1",
        "CTX_ALLOW_BG_FULL": "0",
        "CTX_AUTO_INDEX": "1",
        "CTX_SYNC_INTERVAL_MS": "300000",
        "CTX_REGISTRATION_MODE": reg_mode,
        "CTX_MCP_SURFACE": "phase",
        "CTX_MCP_SESSION_ISOLATE": "1",
        "CTX_MCP_BRIDGE_MODE": "auto",
        "CTX_ENGINE_IDLE_S": "25",
        "CTX_ENGINE_TRANSITION_DEBOUNCE_S": "25",
        "PYTHONUTF8": "1",
    }
    build_id = current_build_id()
    if not build_id:
        build_id = write_active_build_stamp()["build_id"]
    env["CTX_SCUBIEE_BUILD"] = build_id
    # Per-chat isolation: host-native keys (CLAUDE_CODE_SESSION_ID, MCP_SESSION_ID, …)
    # or explicit CTX_MCP_SESSION_ID — see session_isolation.detect_host_chat_session_from_env
    for session_key in (
        "CTX_MCP_SESSION_ID",
        "MCP_SESSION_ID",
        "CLAUDE_CODE_SESSION_ID",
    ):
        session_val = (os.environ.get(session_key) or "").strip()
        if session_val:
            env[session_key] = session_val
            break
    if repo is not None:
        resolved = Path(repo).resolve()
        env["CTX_REPO"] = str(resolved).replace("\\", "/")
        try:
            from pipeline.project_id import read_id_file

            project_id = read_id_file(resolved)
            if project_id:
                env["CTX_PROJECT_ID"] = project_id
        except Exception:  # noqa: BLE001
            pass

    # Prefer the bridge — stable entry for hot reload after upgrade.
    bridge_exe = shutil.which("scubiee-mcp-bridge")
    if bridge_exe:
        return {
            "command": bridge_exe.replace("\\", "/"),
            "args": [],
            "env": env,
        }
    # Fallback: direct scubiee-mcp executable.
    mcp_exe = shutil.which("scubiee-mcp")
    if mcp_exe:
        return {
            "command": mcp_exe.replace("\\", "/"),
            "args": [],
            "env": env,
        }
    # Fallback: raw Python interpreter + module
    return {
        "command": interpreter(),
        "args": ["-u", "-m", "pipeline.mcp_locate"],
        "env": env,
    }


def merge_mcp_json(
    path: Path,
    *,
    name: str | None = None,
    repo: Path | str | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    from pipeline.branding import MCP_SERVER_NAME, strip_legacy_mcp_keys

    server_name = name or MCP_SERVER_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {"mcpServers": {}}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict):
            data = loaded
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        servers = {}
        data["mcpServers"] = servers
    strip_legacy_mcp_keys(servers)
    servers[server_name] = server_entry(repo, host=host, port=port)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _find_mcp_server_entry(data: dict[str, Any], name: str) -> dict[str, Any] | None:
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = data.get("servers")
    if isinstance(servers, dict):
        entry = servers.get(name)
        if isinstance(entry, dict):
            return entry
    mcp = data.get("mcp")
    if isinstance(mcp, dict):
        nested = mcp.get("servers")
        if isinstance(nested, dict):
            entry = nested.get(name)
            if isinstance(entry, dict):
                return entry
        entry = mcp.get(name)
        if isinstance(entry, dict):
            return entry
    return None


def _entry_command_text(entry: dict[str, Any]) -> str:
    cmd = entry.get("command")
    if isinstance(cmd, list):
        return " ".join(str(x) for x in cmd)
    return str(cmd or "")


def verify_mcp_json(path: Path, *, server_name: str | None = None) -> dict[str, Any]:
    """Post-write check: scubiee entry exists and points at bridge/worker with build env."""
    from pipeline.branding import MCP_SERVER_NAME

    name = server_name or MCP_SERVER_NAME
    report: dict[str, Any] = {"ok": False, "path": str(path)}
    if not path.is_file():
        report["error"] = "missing_file"
        return report
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        report["error"] = f"invalid_json: {exc}"
        return report
    if not isinstance(data, dict):
        report["error"] = "invalid_root"
        return report
    entry = _find_mcp_server_entry(data, name)
    if entry is None:
        report["error"] = "server_missing"
        return report
    cmd = _entry_command_text(entry)
    uses_bridge = "scubiee-mcp-bridge" in cmd
    uses_worker = "scubiee-mcp" in cmd and not uses_bridge
    env_raw = entry.get("env")
    if not isinstance(env_raw, dict):
        env_raw = entry.get("environment")
    env = env_raw if isinstance(env_raw, dict) else {}
    has_build = bool(str(env.get("CTX_SCUBIEE_BUILD") or "").strip())
    report.update(
        {
            "uses_bridge": uses_bridge,
            "uses_worker": uses_worker,
            "has_build_env": has_build,
        }
    )
    if not (uses_bridge or uses_worker):
        report["error"] = "bad_command"
        return report
    if not has_build:
        report["error"] = "missing_build_env"
        return report
    report["ok"] = True
    return report


def write_kiro_mcp(
    repo: Path | str | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> dict[str, str]:
    """Write repo-aware and repo-neutral Kiro MCP configuration.

    Kiro loads user-level settings for every workspace, so that entry must not
    contain ``CTX_REPO``.  The workspace-level entry is the one that pins the
    server to the repository being configured.
    """
    target_repo = Path(repo or Path.cwd()).resolve()
    project = target_repo / ".kiro" / "settings" / "mcp.json"
    user = Path.home() / ".kiro" / "settings" / "mcp.json"

    # Keep the global entry usable from any workspace, then let the closer
    # workspace scope provide the repository-specific environment.
    merge_mcp_json(user, repo=None, host=host, port=port)
    merge_mcp_json(project, repo=target_repo, host=host, port=port)
    return {"project": str(project), "user": str(user)}


def _context_agent_rule_template() -> Path:
    import pipeline

    return Path(pipeline.__file__).resolve().parent / "templates" / "scubiee.mdc"


def write_cursor_rule(repo: Path | str | None = None) -> str | None:
    """Write repo rule with real ``GATE 1:ce_…`` (included every chat by Cursor)."""
    from pipeline.rules_installer import _rule_content_mdc, gate_line_for_repo

    target = Path(repo or Path.cwd()).resolve()
    dest = target / ".cursor" / "rules" / "scubiee.mdc"
    dest.parent.mkdir(parents=True, exist_ok=True)
    gate = gate_line_for_repo(target)
    dest.write_text(_rule_content_mdc(gate_line=gate), encoding="utf-8")
    return str(dest)


def write_cursor_mcp(
    repo: Path | str | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> dict[str, str]:
    """Write project mcp.json with CTX_REPO; avoid a user-level CE block that overrides it."""
    project = Path.cwd() / ".cursor" / "mcp.json"
    user = Path.home() / ".cursor" / "mcp.json"
    target_repo = repo or Path.cwd()
    merge_mcp_json(project, repo=target_repo, host=host, port=port)
    _drop_user_context_engine_when_project_configured(project, user)
    out = {"project": str(project), "user": str(user)}
    rule = write_cursor_rule()
    if rule:
        out["rule"] = rule
    return out


def _drop_user_context_engine_when_project_configured(
    project: Path,
    user: Path,
    *,
    name: str | None = None,
) -> None:
    """Cursor merges user + project MCP; a user Scubiee block without CTX_REPO breaks locate."""
    from pipeline.branding import MCP_SERVER_NAMES

    if not project.is_file() or not user.is_file():
        return
    try:
        data = json.loads(user.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return
    if not isinstance(data, dict):
        return
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return
    names = (name,) if name else MCP_SERVER_NAMES
    changed = False
    for n in names:
        if n in servers:
            servers.pop(n, None)
            changed = True
    if not changed:
        return
    user.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
