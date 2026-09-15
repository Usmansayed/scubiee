"""Release 0.3.56 — first-map skip; 800MB serve / 1GB bulk; 30% CPU job cap."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release("0.3.56", notes="Skip AST graph on complete map seeds; 800MB/1GB RAM; 30% CPU cap")
class Release_0_3_56:
    pass
