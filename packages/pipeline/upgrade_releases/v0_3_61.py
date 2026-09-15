"""Release 0.3.61 — engine survives MCP reload; lock heal; non-blocking MCP attach."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.61",
    notes=(
        "Detach engine from MCP kill tree; heal missing engine.lock; "
        "watchdog uses port/pid liveness and skips restart while indexing; "
        "MCP attach no longer blocks Cursor loading on embedder warm"
    ),
)
class Release_0_3_61:
    pass
