"""Context Engine indexing + search pipeline.

Merkle sync → Graphify RepoIR → enrich chunks → embed →
TurboQuant compress → FAISS vector DB → Conductor D_rerank search.
"""

from pipeline.indexer import IndexStats, index_repo
from pipeline.searcher import SearchResult, search_repo
from pipeline.store import PipelineStore
from pipeline.engine import load_engine

__all__ = [
    "IndexStats",
    "PipelineStore",
    "SearchResult",
    "index_repo",
    "load_engine",
    "search_repo",
]
