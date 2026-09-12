"""Release 0.3.65 — MCP bridge child spawn must not flash console windows."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.65",
    notes=(
        "CREATE_NO_WINDOW on MCP bridge worker Popen so crash/respawn loops "
        "cannot blink terminals every few ms; wipe leftover console Run-key path"
    ),
)
class Release_0_3_65:
    pass
