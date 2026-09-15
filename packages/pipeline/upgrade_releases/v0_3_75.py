"""Release 0.3.75 — stop ~15s heal netstat blink + schtasks Query cache."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.75",
    notes=(
        "R4 blink: heal_engine_lock skips netstat when lock/pid already live "
        "(watchdog 15s healthy tick). _live_engine_identity prefers lock/meta "
        "before port sweep. schtasks Query/Run/Create/Delete use hidden_run "
        "(SW_HIDE); sticky miss cache + WMI-first when task missing. Accel "
        "nvidia-smi / PowerShell GPU probes use hidden_run."
    ),
)
class Release_0_3_75:
    pass
