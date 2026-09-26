"""Release 0.3.124 — named dirty files sync without a full-corpus rewrite."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.124",
    notes=(
        "A named dirty set skips the repo-wide freshness walk. It parses and "
        "embeds only those files, appends their vectors, and patches the graph "
        "and capability cards for those paths. A touch of 300 files or fewer "
        "uses the background memory budget."
    ),
)
def v0_3_124() -> None:
    return None
