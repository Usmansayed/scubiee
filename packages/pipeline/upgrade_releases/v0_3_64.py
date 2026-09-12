"""Release 0.3.64 — stop console blink storm from schtasks/powershell/Run-key."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.64",
    notes=(
        "Kill console flash storm: WMI spawn via in-process COM (no powershell); "
        "schtasks always CREATE_NO_WINDOW; skip /Run when task missing; "
        "HKCU Run uses pythonw+_boot_supervisor.pyw; rate-limit ensure_supervisor"
    ),
)
class Release_0_3_64:
    pass
