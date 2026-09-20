"""Release 0.3.97 — break Cursor-open warm deadlock (health/ORT/idle/watchdog)."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.97",
    notes=(
        "Fix live Cursor-open warm trap: idle stop respects embed_prewarm busy stamp "
        "(no 10s self-kill mid-ORT); MCP heartbeat/touch skip HTTP storms while stamp "
        "active; attach warm backs off /health polls during prewarm; watchdog treats "
        "live mcp_bridge as demand so clients=0 no longer deadlocks skip auto load."
    ),
)
def v0_3_97() -> None:
    return None
