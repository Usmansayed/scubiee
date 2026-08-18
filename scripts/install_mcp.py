"""Register context-engine as a Cursor MCP server (thin adapter → CE daemon)."""

from __future__ import annotations

import json

from pipeline.mcp_install import server_entry, write_cursor_mcp


def main() -> int:
    entry = server_entry()
    print(f"python={entry['command']}", flush=True)
    print(f"args={entry['args']}", flush=True)
    print(f"CTX_ENGINE_URL={entry['env']['CTX_ENGINE_URL']}", flush=True)
    wrote = write_cursor_mcp()
    print(json.dumps(wrote, indent=2))
    print(
        "MCP config written. Prefer: pip install context-engine && ctx setup\n"
        "Reload MCP in Cursor: Settings → MCP → refresh.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
