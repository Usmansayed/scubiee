"""Release 0.3.126 — unchanged chunks are not counted as deletions."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.126",
    notes=(
        "A dirty sync drops vectors only for chunks that disappeared or whose "
        "text changed. Unchanged chunks keep their ids. Files that still exist "
        "are synced before a backlog of deletions, so a new file is not starved."
    ),
)
def v0_3_126() -> None:
    return None
