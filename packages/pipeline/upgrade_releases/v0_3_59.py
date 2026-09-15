"""Release 0.3.59 — reap orphan MCP on Cursor close; engine CPU/RAM job actually attaches."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.59",
    notes="Kill leftover MCP workers when Cursor closes; 30% CPU + 800MB job on engine; no per-worker AST preload",
)
class Release_0_3_59:
    pass
