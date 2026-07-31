"""Dense cosine retrieval over a float32 embedding matrix."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np


def text_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_cache(path: Path) -> dict[str, list[float]]:
    cache: dict[str, list[float]] = {}
    if not path.exists():
        return cache
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        cache[row["key"]] = row["embedding"]
    return cache


class DenseIndex:
    def __init__(self, matrix: np.ndarray):
        """matrix: (N, D) L2-normalized float32."""
        self.matrix = np.asarray(matrix, dtype=np.float32)
        norms = np.linalg.norm(self.matrix, axis=1, keepdims=True)
        self.matrix = self.matrix / np.maximum(norms, 1e-12)

    @classmethod
    def from_texts_and_cache(cls, texts: list[str], cache: dict[str, list[float]]) -> "DenseIndex":
        rows: list[list[float]] = []
        miss = 0
        for t in texts:
            k = text_key(t)
            if k not in cache:
                miss += 1
                raise KeyError(f"embedding cache miss ({miss} so far): key={k[:12]}…")
            rows.append(cache[k])
        return cls(np.asarray(rows, dtype=np.float32))

    def score_all(self, query_vec: np.ndarray) -> np.ndarray:
        q = np.asarray(query_vec, dtype=np.float32).reshape(-1)
        q = q / max(float(np.linalg.norm(q)), 1e-12)
        return self.matrix @ q

    def search(self, query_vec: np.ndarray, top_k: int = 50) -> list[tuple[int, float]]:
        scores = self.score_all(query_vec)
        if top_k >= len(scores):
            idx = np.argsort(-scores)
        else:
            part = np.argpartition(-scores, top_k)[:top_k]
            idx = part[np.argsort(-scores[part])]
        return [(int(i), float(scores[i])) for i in idx[:top_k]]
