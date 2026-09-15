"""Release 0.3.78 — total Scubiee RAM budget ≤800 MB serve / ≤1 GB index."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.78",
    notes=(
        "Total process-tree RAM: serve ≤800 MB, index/init ≤1 GB. "
        "register_client loads FastEmbed only when CTX_SCUBIEE_ROLE=engine "
        "(bridge/locate no longer duplicate ORT). "
        "AST preload in mcp_locate off by default (CTX_MCP_TRACE_PRELOAD=1 opt-in). "
        "status.memory exposes tree_rss + total_budget_mb."
    ),
)
class Release_0_3_78:
    pass
