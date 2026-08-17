"""Register context-engine as a Cursor MCP server (thin adapter → CE daemon)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _venv_python() -> Path:
    win = ROOT / ".venv" / "Scripts" / "python.exe"
    unix = ROOT / ".venv" / "bin" / "python"
    if win.is_file():
        return win.resolve()
    if unix.is_file():
        return unix.resolve()
    return Path(sys.executable).resolve()


def server_entry(repo: Path | None = None) -> dict:
    py = _venv_python()
    repo_path = (repo or ROOT).resolve()
    repo_s = str(repo_path).replace("\\", "/")
    py_s = str(py).replace("\\", "/")
    engine_url = os.environ.get("CTX_ENGINE_URL", "http://127.0.0.1:8765")
    return {
        "command": py_s,
        # mcp_locate is the session-native toolkit (map/recall/focus/expand/
        # workspace) that .cursor/rules/context-agent.mdc tells agents to call.
        "args": ["-u", "-m", "pipeline.mcp_locate"],
        "env": {
            "PYTHONPATH": str(ROOT / "packages").replace("\\", "/"),
            "CTX_REPO": repo_s,
            "CTX_ENGINE_URL": engine_url,
            "CTX_RETRIEVE": "D_channel_best",
            "CTX_TOKEN_MODE": "savings",
            # Never pull testdata/* fixture trees into this repo's index.
            "CTX_FAST_ROOTS": "packages,scripts,tests,tools",
            "CTX_BACKGROUND_SYNC": "1",
            "CTX_ALLOW_BG_FULL": "0",
            "CTX_AUTO_INDEX": "1",
            "CTX_SYNC_INTERVAL_MS": "300000",
            "CTX_REGISTRATION_MODE": "automatic",
            "CTX_MCP_SURFACE": "phase",
            "PYTHONUTF8": "1",
        },
    }


def merge_mcp_json(path: Path, name: str = "context-engine", repo: Path | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {"mcpServers": {}}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"invalid JSON in {path}: {exc}") from exc
    servers = data.setdefault("mcpServers", {})
    servers[name] = server_entry(repo)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path} -> mcpServers.{name}", flush=True)


def main() -> int:
    entry = server_entry()
    print(f"python={entry['command']}", flush=True)
    print(f"args={entry['args']}", flush=True)
    print(f"CTX_ENGINE_URL={entry['env']['CTX_ENGINE_URL']}", flush=True)

    # Project-scoped only: a user-level entry pins one CTX_REPO for every
    # workspace and shadows the per-project config.
    merge_mcp_json(ROOT / ".cursor" / "mcp.json")

    print(
        "MCP config written. Prefer full install: ctx setup  (or scripts/install.ps1)\n"
        "Reload MCP in Cursor: Settings → MCP → refresh.\n"
        "The local service auto-starts when MCP connects.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
