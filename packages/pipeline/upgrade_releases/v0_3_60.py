"""Release 0.3.60 — MCP blips and indexing must not kill the engine."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.60",
    notes="120s disconnect debounce; watchdog revives dead engine despite ghost MCP clients; indexing health lag is not a crash",
)
class Release_0_3_60:
    pass
