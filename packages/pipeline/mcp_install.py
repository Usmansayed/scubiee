"""Cursor MCP entry for an installed Context Engine package (no source tree)."""

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

    Does not set PYTHONPATH to a git checkout. Cursor starts
    ``python -m pipeline.mcp_locate`` from the same interpreter that has CE.
    """
    engine_url = os.environ.get("CTX_ENGINE_URL") or f"http://{host}:{port}"
    env: dict[str, str] = {
        "CTX_ENGINE_URL": engine_url,
        "CTX_TOKEN_MODE": "savings",
        "CTX_BACKGROUND_SYNC": "1",
        "CTX_ALLOW_BG_FULL": "0",
        "CTX_AUTO_INDEX": "1",
        "CTX_SYNC_INTERVAL_MS": "300000",
        "CTX_REGISTRATION_MODE": "automatic",
        "CTX_MCP_SURFACE": "phase",
        "CTX_ENGINE_IDLE_S": "60",
        "PYTHONUTF8": "1",
    }
    if repo is not None:
        env["CTX_REPO"] = str(Path(repo).resolve()).replace("\\", "/")
    return {
        "command": interpreter(),
        "args": ["-u", "-m", "pipeline.mcp_locate"],
        "env": env,
    }


def merge_mcp_json(
    path: Path,
    *,
    name: str = "context-engine",
    repo: Path | str | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
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
    servers[name] = server_entry(repo, host=host, port=port)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


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

    return Path(pipeline.__file__).resolve().parent / "templates" / "context-agent.mdc"


def write_cursor_rule() -> str | None:
    """Write MCP-only retrieval rule to project .cursor/rules (gitignored locally)."""
    src = _context_agent_rule_template()
    if not src.is_file():
        return None
    dest = Path.cwd() / ".cursor" / "rules" / "context-agent.mdc"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
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
    name: str = "context-engine",
) -> None:
    """Cursor merges user + project MCP; a user CE block without CTX_REPO breaks locate."""
    if not project.is_file() or not user.is_file():
        return
    try:
        data = json.loads(user.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return
    if not isinstance(data, dict):
        return
    servers = data.get("mcpServers")
    if not isinstance(servers, dict) or name not in servers:
        return
    servers.pop(name, None)
    user.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
