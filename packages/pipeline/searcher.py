"""Search using FAISS collection dense + BM25 + Graphify → Conductor D_rerank."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from conductor.dense_index import DenseIndex
from pipeline.vectordb import FaissCollection, VectorDatabase


@dataclass
class SearchResult:
    rank: int
    file: str
    score: float
    chunk_id: int
    preview: str
    source: str = "d_rerank"
    start_line: int | None = None
    end_line: int | None = None


class FaissDenseAdapter(DenseIndex):
    """DenseIndex API backed by a FaissCollection (TurboQuant + FAISS).

    The conductor addresses every channel by **chunk position** — the index of
    the record in ``chunks.jsonl``, which is also the index into ``files``,
    ``texts``, the BM25 docs and the graph spans. The vector store addresses
    rows by **durable chunk id** and keeps tombstones, so its row order drifts
    away from the chunk list after any incremental upsert or delete.

    Passing ``chunk_ids`` re-indexes the vector matrix into chunk position
    space: row ``i`` holds the vector for ``chunk_ids[i]``, and a chunk with no
    live vector gets a zero row. Without that, dense scores are attributed to
    whatever chunk happens to sit at the same offset in the other space, and
    ``d_all[i]`` raises ``IndexError`` for every chunk past the end of the
    vector matrix — which is exactly where newly synced chunks land.
    """

    def __init__(
        self,
        col: FaissCollection,
        n_chunks: int,
        chunk_ids: list[int] | None = None,
    ):
        dim = int(col.meta.dim)
        mat = np.asarray(col.compressed.to_float32(), dtype=np.float32)
        if mat.ndim != 2:
            mat = np.zeros((0, dim), dtype=np.float32)
        self._chunk_row: dict[int, int] | None = None
        self._missing = 0
        if chunk_ids is None:
            rows = mat if mat.size else np.zeros((n_chunks, dim), dtype=np.float32)
        else:
            dead = {int(x) for x in (col.meta.dead_ids or [])}
            vector_row = {
                int(vid): row
                for row, vid in enumerate(col.ids)
                if int(vid) not in dead and row < mat.shape[0]
            }
            rows = np.zeros((len(chunk_ids), dim), dtype=np.float32)
            for pos, cid in enumerate(chunk_ids):
                row = vector_row.get(int(cid))
                if row is None:
                    self._missing += 1
                    continue
                rows[pos] = mat[row]
            self._chunk_row = {int(cid): pos for pos, cid in enumerate(chunk_ids)}
        super().__init__(rows)
        self.col = col

    @property
    def missing_vectors(self) -> int:
        """Chunks in the corpus that have no live vector (dense can't rank them)."""
        return self._missing

    def search(self, query_vec: np.ndarray, top_k: int = 50):
        hits = self.col.search(query_vec, top_k=top_k)
        if not hits:
            return super().search(query_vec, top_k=top_k)
        row_of = self._chunk_row
        if row_of is None:
            # No chunk id list supplied — fall back to vector-store row order.
            row_of = {int(vid): i for i, vid in enumerate(self.col.ids)}
        mapped: list[tuple[int, float]] = []
        for vid, score, *_rest in hits:
            pos = row_of.get(int(vid))
            if pos is not None:
                mapped.append((pos, float(score)))
        return mapped or super().search(query_vec, top_k=top_k)


class SearchEngineError(RuntimeError):
    """Raised when daemon search was requested but the engine is unavailable."""

    def __init__(self, message: str, *, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


def _search_via_server(
    query: str,
    *,
    top_k: int,
    url: str,
    root: Path,
) -> list[SearchResult] | None:
    payload = json.dumps(
        {"query": query, "top_k": top_k, "path": str(root)}
    ).encode("utf-8")
    req = urllib.request.Request(
        url.rstrip("/") + "/v1/search",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            data = json.loads(exc.read().decode("utf-8") or "{}")
        except json.JSONDecodeError:
            data = {}
        if exc.code in {400, 409} and data.get("error"):
            raise SearchEngineError(
                str(data.get("error") or exc),
                hint=str(data.get("hint") or "Run: scubiee engine ensure ."),
            ) from exc
        return None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    if data.get("ok") is False and data.get("error"):
        raise SearchEngineError(
            str(data["error"]),
            hint=str(data.get("hint") or "Run: scubiee engine ensure ."),
        )
    out: list[SearchResult] = []
    for h in data.get("hits") or []:
        out.append(
            SearchResult(
                rank=int(h["rank"]),
                file=str(h["file"]),
                score=float(h["score"]),
                chunk_id=int(h["chunk_id"]),
                preview=str(h.get("preview") or h.get("why") or ""),
                source=str(h.get("source") or "d_rerank"),
                start_line=int(h["start_line"]) if h.get("start_line") else None,
                end_line=int(h["end_line"]) if h.get("end_line") else None,
            )
        )
    return out


def search_repo(
    root: Path,
    query: str,
    *,
    top_k: int = 8,
    base_dir: Path | None = None,
    vdb: VectorDatabase | None = None,
    use_server: bool = True,
    server_url: str | None = None,
) -> list[SearchResult]:
    """Search an explicitly selected repo, optionally through a configured server."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"not a directory: {root}")
    # A default localhost probe can route a caller for repository A to an
    # unrelated daemon currently serving repository B.  Only cross-process
    # search when the caller explicitly supplies a URL or configures one.
    url = server_url or os.environ.get("CTX_SEARCH_URL") or os.environ.get("CTX_ENGINE_URL")
    if use_server and url:
        hits = _search_via_server(query, top_k=top_k, url=url, root=root)
        if hits is not None:
            return hits
        raise SearchEngineError(
            f"Scubiee unreachable at {url.rstrip('/')}",
            hint="Run: scubiee engine ensure .   or   scubiee search --local",
        )

    from pipeline.engine import load_engine

    eng = load_engine(root, base_dir=base_dir, vdb=vdb)
    return eng.search(query, top_k=top_k)
