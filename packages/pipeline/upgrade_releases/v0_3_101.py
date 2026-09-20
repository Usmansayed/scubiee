"""Release 0.3.101 — 40s warmup; first map ≤3s; later maps/tools ≤1s after idle."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.101",
    notes=(
        "Warmup (~40s) loads FastEmbed then runs one D_channel_best prime search "
        "so the first user map is ≤3s. Keepalive + AST hydrate keep later map/"
        "pack/expand/status ≤1s after minutes of idle while the IDE stays connected."
    ),
)
def v0_3_101() -> None:
    return None
