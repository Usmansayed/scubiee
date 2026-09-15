"""Release 0.3.74 — kill remaining Windows console blink hot paths."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.74",
    notes=(
        "R4 blink: daemon_python fastembed probes, netstat port sweeps, "
        "powershell delete-waiter, pip/uv uninstall, and hardware probes now "
        "use hidden_run/hidden_popen (CREATE_NO_WINDOW+SW_HIDE). Removed "
        "DETACHED_PROCESS from schedule-delete (it flashes consoles). Bridge "
        "rejects stale python.exe worker pins. hidden_run always sets SW_HIDE."
    ),
)
class Release_0_3_74:
    pass
