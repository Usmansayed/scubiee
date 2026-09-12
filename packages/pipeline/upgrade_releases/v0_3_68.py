"""Release 0.3.68 — stop MCP reconnect storm: live pythonw+mcp_bridge pins; engine must not rewrite mcp.json."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.68",
    notes=(
        "Treat pipeline.mcp_bridge as a live MCP pin so heal does not rewrite "
        "mcp.json on every engine start (Cursor reconnect/blink storm); remove "
        "pin restore from start_daemon; watchdog discovers boot-script PIDs; "
        "windowsHide on Windows MCP entry; drop debug-blink hooks; skip stale "
        "engine.start_request leftovers when no MCP clients remain"
    ),
)
class Release_0_3_68:
    pass
