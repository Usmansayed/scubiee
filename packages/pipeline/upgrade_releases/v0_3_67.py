"""Release 0.3.67 — Windows MCP entry uses pythonw (no console shim / conhost blink)."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.67",
    notes=(
        "On Windows, Cursor MCP launches pythonw -m pipeline.mcp_bridge "
        "(not scubiee-mcp-bridge.EXE console shim) and workers via "
        "CTX_MCP_BRIDGE_SPAWN_JSON pythonw -m pipeline.mcp_locate — stops conhost "
        "allocation on every MCP reconnect"
    ),
)
class Release_0_3_67:
    pass
