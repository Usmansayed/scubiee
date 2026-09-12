"""Release 0.3.66 — demand-driven engine + silent taskkill + MCP ensure coalesce."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.66",
    notes=(
        "Silent taskkill helper; sticky desired_run without clients now idles; "
        "watchdog skips force_restart without demand; MCP ensure TTL coalesce"
    ),
)
class Release_0_3_66:
    pass
