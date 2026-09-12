"""Release 0.3.69 — agent-warm: MCP connect does not spawn engine/watchdog."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.69",
    notes=(
        "MCP stdio connect is a thin attach (leave hooks only). Engine, "
        "watchdog, and FastEmbed start on the agent's first gate/status/map "
        "call. Set CTX_MCP_AUTO_WARM=1 to restore connect-time auto warm. "
        "Stops WMI/engine spawn storms on Cursor MCP reconnect."
    ),
)
class Release_0_3_69:
    pass
