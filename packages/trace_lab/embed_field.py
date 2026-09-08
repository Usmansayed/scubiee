"""Node/query embedding field for trace-lab (CodeRank / FAISS-ready).

Uses the product Embedder when available and caches vectors under the
fixture so re-runs are instant. Falls back to hashed n-grams only if the
real model cannot load — callers can require real embeds via ``require_real=True``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from conductor.dense_index import DenseIndex, text_key
from trace_lab.types import TraceNode
from trace_lab.vector_index import embed_text as hash_embed


def node_doc(n: TraceNode) -> str:
    """Document text for embedding (code retrieval format, no query prefix)."""
    body = (n.lex_text or n.text or "").strip()
    # Cap body so we stay inside CodeRank's useful window.
    if len(body) > 1200:
        body = body[:1200]
    return f"{n.file}\n{n.symbol}\n{body}"


class EmbedField:
    """Per-corpus embedding matrix + query cosine search."""

    def __init__(
        self,
        nodes: dict[str, TraceNode],
        *,
        cache_path: Path | None = None,
        require_real: bool = False,
        quiet: bool = True,
    ):
        self.ids = list(nodes.keys())
        self.nodes = nodes
        self.backend = "hash"
        self.dim = 256
        docs = [node_doc(nodes[i]) for i in self.ids]
        mat: np.ndarray
        try:
            from pipeline.embedder import Embedder

            cache = cache_path
            if cache is not None:
                cache.parent.mkdir(parents=True, exist_ok=True)
            # Honor accel batch (DML 16 / CUDA 32 / CPU); do not hardcode 8.
            emb = Embedder(cache_path=cache, quiet=quiet)
            mat = np.asarray(emb.embed_many(docs, is_query=False), dtype=np.float32)
            emb.flush_cache()
            self._embedder = emb
            self.backend = f"real:{emb.backend}"
            self.dim = int(mat.shape[1])
        except Exception as exc:  # noqa: BLE001
            if require_real:
                raise RuntimeError(f"real embeddings required: {exc}") from exc
            self._embedder = None
            mat = np.stack([hash_embed(d, dim=256) for d in docs], axis=0)
            self.backend = "hash-fallback"
            self.dim = 256

        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        self.matrix = mat / np.maximum(norms, 1e-12)
        self.dense = DenseIndex(self.matrix)
        self._by_id = {nid: i for i, nid in enumerate(self.ids)}

    def embed_query(self, query: str) -> np.ndarray:
        if self._embedder is not None:
            try:
                v = np.asarray(self._embedder.embed_one(query, is_query=True), dtype=np.float32)
                n = float(np.linalg.norm(v)) or 1.0
                return v / n
            except Exception:
                pass
        v = hash_embed(query, dim=self.dim)
        return v

    def affinities(self, query: str) -> dict[str, float]:
        q = self.embed_query(query)
        raw = self.dense.score_all(q)
        return {self.ids[i]: float(raw[i]) for i in range(len(self.ids))}

    def vec(self, nid: str) -> np.ndarray:
        return self.matrix[self._by_id[nid]]

    def pair_cos(self, a: str, b: str) -> float:
        return float(self.vec(a) @ self.vec(b))

    def hub_prior(self, graph_degree: dict[str, int], *, top: int = 5) -> np.ndarray:
        """Mean embedding of highest-degree nodes — a contrastive 'hub' attractor."""
        ranked = sorted(self.ids, key=lambda i: graph_degree.get(i, 0), reverse=True)
        pick = [i for i in ranked[: max(top, 1)] if i in self._by_id]
        if not pick:
            return np.zeros(self.dim, dtype=np.float32)
        m = np.stack([self.vec(i) for i in pick], axis=0).mean(axis=0)
        n = float(np.linalg.norm(m)) or 1.0
        return (m / n).astype(np.float32)
