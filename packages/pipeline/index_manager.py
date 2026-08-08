"""IndexManager — thin façade over probe / full index / incremental sync.

Always asks ResourceManager before heavy work (via indexer/incremental gates).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pipeline.indexer import IndexDeferred


class IndexManager:
    """Owns building and updating the on-disk index (not serving queries)."""

    def probe(self, repo: Path | str) -> dict[str, Any]:
        from pipeline.root_probe import root_probe

        return root_probe(Path(repo).resolve()).to_dict()

    def full_index(self, repo: Path | str, **kwargs: Any) -> dict[str, Any]:
        from pipeline.indexer import index_repo

        root = Path(repo).resolve()
        try:
            stats = index_repo(root, **kwargs)
        except IndexDeferred as exc:
            return {
                "ok": False,
                "deferred": True,
                "error": str(exc.reason),
                "pressure": exc.pressure,
                "root": str(root),
            }
        return {
            "ok": True,
            "deferred": False,
            "root": stats.root,
            "added": stats.added,
            "modified": stats.modified,
            "removed": stats.removed,
            "chunks": stats.chunks,
            "embedded": stats.embedded,
            "unchanged": stats.unchanged,
            "store_dir": stats.store_dir,
            "vector_stats": stats.vector_stats,
        }

    def sync(self, repo: Path | str) -> dict[str, Any]:
        from pipeline.incremental import incremental_sync

        result = incremental_sync(Path(repo).resolve())
        out = result.to_dict()
        out["ok"] = result.error is None
        out["refreshed"] = bool(result.refreshed)
        return out


_IM: IndexManager | None = None


def get_index_manager() -> IndexManager:
    global _IM
    if _IM is None:
        _IM = IndexManager()
    return _IM
