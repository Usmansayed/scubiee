"""Cursor MCP entry for an installed Context Engine package (no source tree)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def interpreter() -> str:
    return str(Path(sys.executable).resolve()).replace("\\", "/")


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
        "CTX_ENGINE_IDLE_S": "120",
        "CTX_WATCHDOG": "0",
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
    return {"project": str(project), "user": str(user)}


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
