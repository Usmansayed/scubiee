"""Release 0.3.129 — MCP stderr no longer logs every engine HTTP call."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.129",
    notes=(
        "FastMCP's INFO logging no longer lets httpx print every engine request "
        "on the MCP stderr stream. Cursor was showing those lines as errors and "
        "closing the session while status was still running."
    ),
)
def v0_3_129() -> None:
    return None
