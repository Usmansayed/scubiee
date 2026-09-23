"""Release 0.3.110 — AST hydrate finishes, and expand no longer crashes on a miss."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.110",
    notes=(
        "A cold AST bundle now bakes to completion. MCP bridge and locate "
        "children bake in a separate process so the tool thread is not stalled, "
        "on every OS. expand_context no longer crashes when hydrate returns "
        "nothing, and pack_context can proceed once that bake lands."
    ),
)
def v0_3_110() -> None:
    return None
