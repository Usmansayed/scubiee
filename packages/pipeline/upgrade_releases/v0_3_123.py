"""Release 0.3.123 — leftover prewarm stamp must not restart an opening engine."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.123",
    notes=(
        "A stale warm_phase.json or embed_prewarm.busy file from a killed "
        "engine no longer force-restarts the next process. The busy stamp "
        "records the writer pid. Indexing or warming skips the restart. "
        "A new engine clears both files as it starts listening."
    ),
)
def v0_3_123() -> None:
    return None
