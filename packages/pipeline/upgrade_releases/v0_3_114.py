"""Release 0.3.114 — warm-up actually finishes the AST/graph hydrate."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.114",
    notes=(
        "prewarm_locate_worker now waits for the background AST/graph bundle "
        "hydrate to finish (within the existing warm deadline budget) instead "
        "of firing it and returning immediately. Closes the cold-start gap "
        "where the first real map/pack_context paid the graph-load cost that "
        "should have happened during warm-up. The hydrate still runs on a "
        "background thread (never inline on the request path, which would "
        "GIL-starve search); warm-up simply joins it before reporting ready. "
        "If the deadline is exhausted first, warm-up returns anyway — this "
        "only removes the gap, never makes cold start worse."
    ),
)
def v0_3_114() -> None:
    return None
