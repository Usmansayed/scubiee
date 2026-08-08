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
        hits = self.col.search(query_vec, top_k=top_k)
        if hits:
            return [(vid, score) for vid, score, _ in hits]
        return super().search(query_vec, top_k=top_k)


def _search_via_server(
    query: str,
    *,
    top_k: int,
    url: str,
) -> list[SearchResult] | None:
    payload = json.dumps({"query": query, "top_k": top_k}).encode("utf-8")
    req = urllib.request.Request(
        url.rstrip("/") + "/search",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
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
    """Search. Prefers warm HTTP server, else in-process warm engine cache."""
    url = server_url or os.environ.get("CTX_SEARCH_URL", "http://127.0.0.1:8765")
    if use_server:
        hits = _search_via_server(query, top_k=top_k, url=url)
        if hits is not None:
            return hits

    from pipeline.engine import load_engine

    eng = load_engine(root, base_dir=base_dir, vdb=vdb)
    return eng.search(query, top_k=top_k)
