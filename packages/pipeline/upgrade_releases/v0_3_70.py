"""Release 0.3.70 — agent-direct engine warm; watchdog does not auto-start."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.70",
    notes=(
        "Watchdog no longer cold-starts the engine (CTX_WATCHDOG_AUTO_START=1 "
        "restores). First gate/status/map calls start_daemon directly. MCP "
        "disconnect unload is unchanged. Engine run binds HTTP before repo "
        "open; spawn skips Merkle-reconcile-all so cold agent warm is under "
        "10s on this Windows box."
    ),
)
class Release_0_3_70:
    pass
