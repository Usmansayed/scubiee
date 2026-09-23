"""Release 0.3.106 — pack ranking prefers substantial callees."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.106",
    notes=(
        "Strict and broad pack stay on composite_v1. Tiny bodies and private "
        "helpers are demoted before the top-k cutoff, so larger callees such as "
        "run_map_context and run_collect_hot lead the heatmap. Broad pack no "
        "longer switches to polytrace or clears the repo cache."
    ),
)
def v0_3_106() -> None:
    return None
