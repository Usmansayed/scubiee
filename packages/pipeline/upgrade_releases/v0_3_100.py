"""Release 0.3.100 — 1.5 GB RSS pin + 35% CPU; governor must not smash the pin."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.100",
    notes=(
        "Install pins CTX_ENGINE_CPU_CAP_PCT=35 and CTX_SCUBIEE_TOTAL_RSS_MB=1536. "
        "Memory governor no longer overwrites CTX_CE_RSS_CAP_MB down to 380/520/800 "
        "when the tree pin is set — that smash unloaded DirectML while Cursor was open."
    ),
)
def v0_3_100() -> None:
    return None
