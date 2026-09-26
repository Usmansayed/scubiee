"""Release 0.3.130 — a saved file is indexed ahead of a bulk dirty backlog."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.130",
    notes=(
        "A file marked by a save is synced into the chunk list before a large "
        "disk-poll backlog. Map searches that list, so the new file is no longer "
        "left behind a 50-file slice."
    ),
)
def v0_3_130() -> None:
    return None
