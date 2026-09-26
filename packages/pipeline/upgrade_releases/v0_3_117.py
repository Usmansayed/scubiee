"""Release 0.3.117 — status does not walk the repo for newcomers."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.117",
    notes=(
        "Full status no longer runs a newcomer filesystem walk. That probe "
        "was about 12s on this repo and blocked the status request. Status "
        "checks indexed files only and reuses that result for 15s. The keeper "
        "poll still discovers new files."
    ),
)
def v0_3_117() -> None:
    return None
