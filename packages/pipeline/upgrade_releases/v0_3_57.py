"""Release 0.3.57 — first map skips AST graph; preload graph in background."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release("0.3.57", notes="Map never blocks on _load_repo; attach preloads AST graph in background")
class Release_0_3_57:
    pass
