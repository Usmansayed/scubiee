"""Release 0.3.98 — warm_autoload phase machine (GIL-safe Cursor open)."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.98",
    notes=(
        "Rewrite warm/auto-load around warm_phase side-channel: ORT prewarm holds "
        "the GIL so /health timeouts are expected — watchdog ignores fails in "
        "prewarm; MCP heartbeat/attach wait on phase file; idle stop respects "
        "prewarm; fail-closed sims poll health only when not prewarming. "
        "See docs/architecture/warm-autoload.md."
    ),
)
def v0_3_98() -> None:
    return None
