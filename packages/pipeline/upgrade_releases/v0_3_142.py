"""Release 0.3.142 — map surface narrowed to two configs: find | focus."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.142",
    notes=(
        "Fewer tools, simpler to reason about and to explain. The shipped `map` tool "
        "now ADVERTISES only two configs — `find` and `focus` — instead of four. "
        "Usage mining showed find+focus = ~92% of real map calls; `related` was ~2% "
        "(near-dead) and `graph` ~5%, and agents reach for find/focus by default. "
        "`find` now also covers the old jobs: orient a wide/unknown area with a broad "
        "query, and pull code near a chunk you hold by putting its names in the query. "
        "The old `related`/`graph` handlers are KEPT as hidden graceful fallbacks "
        "(a client that still sends them is served via find, never hard-errored), so "
        "no legacy call breaks. The ship surface check (SHIP_CONFIGS), the MCP tool "
        "description + schema enum + server instructions, the `scubiee map --config` "
        "CLI choices, the acceptance scripts, and the connect-time rules were all "
        "updated to find|focus. The shipped rule is paired with the k_2cfg_decomp "
        "guidance: ONE target per query, known name -> focus FIRST, and DECOMPOSE a "
        "two-target task into two calls rather than one bundled query. No engine change."
    ),
)
def v0_3_142() -> None:
    return None
