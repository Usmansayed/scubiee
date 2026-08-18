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
    """DenseIndex API backed by a FaissCollection (TurboQuant + FAISS)."""

    def __init__(self, col: FaissCollection, n_chunks: int):
        mat = col.compressed.to_float32()
        if mat.size == 0:
            mat = np.zeros((n_chunks, col.meta.dim), dtype=np.float32)
        super().__init__(mat)
        self.col = col

    def search(self, query_vec: np.ndarray, top_k: int = 50):
        # Conductor arrays are positional 0..n-1. FAISS IndexIDMap2 returns
        # durable chunk ids, which grow gaps after incremental delete/upsert.
        hits = self.col.search(query_vec, top_k=top_k)
        if not hits:
            return super().search(query_vec, top_k=top_k)
        id_to_row = {int(vid): i for i, vid in enumerate(self.col.ids)}
        mapped: list[tuple[int, float]] = []
        for vid, score, *_rest in hits:
            row = id_to_row.get(int(vid))
            if row is not None:
                mapped.append((row, float(score)))
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
                hint=str(data.get("hint") or "Run: ctx engine ensure ."),
            ) from exc
        return None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    if data.get("ok") is False and data.get("error"):
        raise SearchEngineError(
            str(data["error"]),
            hint=str(data.get("hint") or "Run: ctx engine ensure ."),
        )
    out: list[SearchResult] = []
    for h in data.get("hits") or []:
        out.append(
            SearchResult(
                rank=int(h["rank"]),
                file=str(h["file"]),
                score=float(h["score"]),
                chunk_id=int(h["chunk_id"]),
                preview=str(h.get("preview") or ""),
                source=str(h.get("source") or "d_rerank"),
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
            f"Context Engine unreachable at {url.rstrip('/')}",
            hint="Run: ctx engine ensure .   or   ctx search --local",
        )

    from pipeline.engine import load_engine

    eng = load_engine(root, base_dir=base_dir, vdb=vdb)
    return eng.search(query, top_k=top_k)
