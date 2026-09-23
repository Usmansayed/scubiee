"""Release 0.3.108 — one install after upgrade, connect, and wipe."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.108",
    notes=(
        "upgrade and connect keep the newest Scubiee and pip-uninstall older "
        "copies so an old conda install cannot stay first on PATH. "
        "MCP pythonw commands are rewritten onto that keeper. "
        "A tie keeps the uv tool install. wipe --all also removes leftover "
        "pip copies before it removes the tool install."
    ),
)
def v0_3_108() -> None:
    return None
