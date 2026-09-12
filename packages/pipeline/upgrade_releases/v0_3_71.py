"""Release 0.3.71 — watchdog never auto-loads; disconnect unload unchanged."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.71",
    notes=(
        "Watchdog default skips force_restart_daemon as well as start_daemon "
        "(CTX_WATCHDOG_AUTO_START=1 restores). MCP still connected with a dead "
        "engine PID no longer races the agent into a second spawn. Disconnect "
        "unload (leave → idle sweeper) is unchanged. Agent first gate/status/map "
        "is the only automatic load path."
    ),
)
class Release_0_3_71:
    pass
