"""Release 0.3.94 — Cursor-open settle: soft→dense prewarm within seconds."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.94",
    notes=(
        "Cursor-open: after soft_search_ready, keepalive polls every 2s and "
        "kicks async FastEmbed prewarm until embedder_loaded (was 15s only — "
        "SETTLE_MAP_SLOW ~3s first map). soft_now attach + MCP heartbeat also "
        "kick /v1/embed/prewarm. Lane A settle requires embedder_loaded before "
        "map_first ≤1s SLA. Host-sim default CTX_MCP_CLIENT=cursor."
    ),
)
class Release_0_3_94:
    pass
