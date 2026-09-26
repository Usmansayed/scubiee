"""Release 0.3.120 — collect keeps a short body budget."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.120",
    notes=(
        "collect_hot_context no longer drops a body when fewer than 200 "
        "characters of budget remain, and it no longer raises a short budget "
        "to 200 or 400. The returned text fits max_chars."
    ),
)
def v0_3_120() -> None:
    return None
