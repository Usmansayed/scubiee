"""Context Engine indexing + search pipeline.

Merkle sync → Graphify RepoIR → enrich chunks → embed →
TurboQuant compress → FAISS vector DB → Conductor D_rerank search.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "IndexStats",
    "PipelineStore",
    "SearchResult",
    "index_repo",
    "load_engine",
    "search_repo",
]


def __getattr__(name: str) -> Any:
    if name in ("IndexStats", "index_repo"):
        from pipeline.indexer import IndexStats, index_repo

        return IndexStats if name == "IndexStats" else index_repo
    if name in ("SearchResult", "search_repo"):
        from pipeline.searcher import SearchResult, search_repo

        return SearchResult if name == "SearchResult" else search_repo
    if name == "PipelineStore":
        from pipeline.store import PipelineStore

        return PipelineStore
    if name == "load_engine":
        from pipeline.engine import load_engine

        return load_engine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
