"""Register context-engine MCP pointed at frontend-mcp (or any repo)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

CE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = CE_ROOT / "testdata" / "frontend-mcp"


def _venv_python() -> Path:
    win = CE_ROOT / ".venv" / "Scripts" / "python.exe"
    unix = CE_ROOT / ".venv" / "bin" / "python"
    if win.is_file():
        return win.resolve()
    if unix.is_file():
        return unix.resolve()
    return Path(sys.executable).resolve()


def server_entry(repo: Path, name: str = "context-engine") -> dict:
    import os

    py = str(_venv_python()).replace("\\", "/")
    repo_s = str(repo.resolve()).replace("\\", "/")
    engine_url = os.environ.get("CTX_ENGINE_URL", "http://127.0.0.1:8765")
    return {
        "command": py,
        "args": ["-u", "-m", "pipeline", "mcp", repo_s],
        "env": {
            "CTX_REPO": repo_s,
            "CTX_ENGINE_URL": engine_url,
            "CTX_BACKGROUND_SYNC": "1",
            "CTX_ALLOW_BG_FULL": "0",
            "CTX_AUTO_INDEX": "1",
            "CTX_SYNC_INTERVAL_MS": "300000",
            "CTX_REGISTRATION_MODE": "automatic",
            "PYTHONUTF8": "1",
        },
    }


def merge_mcp_json(path: Path, entry: dict, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {"mcpServers": {}}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"invalid JSON in {path}: {exc}") from exc
    data.setdefault("mcpServers", {})[name] = entry
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path} -> mcpServers.{name}", flush=True)


def main() -> int:
    repo = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_REPO).resolve()
    name = sys.argv[2] if len(sys.argv) > 2 else "context-engine"
    entry = server_entry(repo, name)
    print(f"CTX_REPO={repo}", flush=True)
    merge_mcp_json(CE_ROOT / ".cursor" / "mcp.json", entry, name)
    merge_mcp_json(Path.home() / ".cursor" / "mcp.json", entry, name)
    print("Reload MCP in Cursor after indexing finishes.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
