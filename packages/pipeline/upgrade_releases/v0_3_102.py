"""Release 0.3.102 — keepalive yields to unique map; dual-MCP dummy-search skip."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.102",
    notes=(
        "Keepalive encode aborts if locate is in flight; 4s post-search cooldown; "
        "capped graph touch (max_visit=64). Dummy locate search skips when engine "
        "keepalive already warmed retrieve (dual Cursor MCP + host-sim clean_slate). "
        "Default CTX_EMBED_KEEPALIVE_S=8. Lane A post_idle unique map stays ≤1s."
    ),
)
def v0_3_102() -> None:
    return None
