"""Release 0.3.77 — keep warm while Cursor MCP bridge is open."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.77",
    notes=(
        "Keep-warm: MCP bridge registers a stable kind=bridge client so worker "
        "respawn/leave no longer arms embedder demote while Cursor is open. "
        "coalesce_mcp_clients preserves bridge anchors. "
        "Locate/search HTTP admit uses intentional=True so enrolled repos do not "
        "false-pause large_repo after engine hub restart. "
        "ensure_mcp_runtime kicks background AST preload for faster first pack."
    ),
)
class Release_0_3_77:
    pass
