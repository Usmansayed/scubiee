"""Release 0.3.83 — reliable open + honest warm_elapsed."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.83",
    notes=(
        "/v1/open always intentional (no false large_repo pause after hub restart). "
        "Freeze warm_elapsed_ms at attach→ready so status no longer looks like a "
        "100s warm-up while the clock keeps ticking."
    ),
)
class Release_0_3_83:
    pass
