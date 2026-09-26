"""Release 0.3.122 — dirty files drain by size on the 1s debounce."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.122",
    notes=(
        "POST /v1/sync only wakes the keeper. Indexed edits are marked during "
        "a locate streak and become due after the 1s debounce. Sets of "
        "301–10000 chunks advance one 50-file batch every 2s while a client "
        "is connected. New files are scanned every 30s outside a locate streak."
    ),
)
def v0_3_122() -> None:
    return None
