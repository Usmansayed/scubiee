"""Release 0.3.115 — freshness and multi-seed diagnostics match the result."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.115",
    notes=(
        "Status splits search_usable from index_fresh while a sync is running. "
        "agreement_n=0 on a multi-seed pack explains that the seeds share no "
        "nodes; the heatmap is their union."
    ),
)
def v0_3_115() -> None:
    return None
