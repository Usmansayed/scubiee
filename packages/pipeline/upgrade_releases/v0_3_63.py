"""Release 0.3.63 — WMI-orphan supervisor so Cursor close cannot kill the engine job."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.63",
    notes=(
        "Spawn watchdog via WMI (not MCP parent) so KILL_ON_JOB_CLOSE no longer "
        "reaps the engine on Cursor reload; prefer pythonw to stop console flashes; "
        "Cursor open → supervisor-owned warm without manual engine start"
    ),
)
class Release_0_3_63:
    pass
