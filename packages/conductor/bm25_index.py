"""Okapi BM25 over tokenized chunk texts."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

import numpy as np

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


def top_hits_from_scores(
    scores: np.ndarray,
    top_k: int,
    *,
    drop_nonpositive: bool = False,
) -> list[tuple[int, float]]:
    """Rank ids the same way BM25Index.search / DenseIndex.search used to."""
    scores = np.asarray(scores)
    n = int(scores.size)
    if n == 0 or top_k <= 0:
        return []
    k = min(int(top_k), n)
    if drop_nonpositive:
        ranked = np.argsort(-scores)
        out: list[tuple[int, float]] = []
        for i in ranked[:k]:
            if scores[i] <= 0:
                break
            out.append((int(i), float(scores[i])))
        return out
    if k >= n:
        idx = np.argsort(-scores)
    else:
        part = np.argpartition(-scores, k)[:k]
        idx = part[np.argsort(-scores[part])]
    return [(int(i), float(scores[i])) for i in idx[:k]]


class BM25Index:
    def __init__(self, corpus: list[str], *, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs = [tokenize(t) for t in corpus]
        self.N = len(self.docs)
        self.doc_len = [len(d) for d in self.docs]
        self.avgdl = sum(self.doc_len) / max(self.N, 1)
        df: Counter[str] = Counter()
        for d in self.docs:
            df.update(set(d))
        self.idf = {
            t: math.log(1.0 + (self.N - freq + 0.5) / (freq + 0.5))
            for t, freq in df.items()
        }
        self._tf = [Counter(d) for d in self.docs]
        self._rebuild_accel()

    def _rebuild_accel(self) -> None:
        """Inverted postings + per-doc BM25 length norm — same Okapi scores, O(postings)."""
        denom = self.k1 * (
            1.0
            - self.b
            + self.b * np.asarray(self.doc_len, dtype=np.float64) / max(self.avgdl, 1e-9)
        )
        self._denom = np.asarray(denom, dtype=np.float64)
        buckets: dict[str, list[int]] = defaultdict(list)
        freqs: dict[str, list[float]] = defaultdict(list)
        for i, tf in enumerate(self._tf):
            for t, f in tf.items():
                buckets[t].append(i)
                freqs[t].append(float(f))
        self._postings: dict[str, tuple[np.ndarray, np.ndarray]] = {
            t: (
                np.asarray(buckets[t], dtype=np.int32),
                np.asarray(freqs[t], dtype=np.float64),
            )
            for t in buckets
        }

    def score_all(self, query: str) -> np.ndarray:
        """Return BM25 score for every doc (float64 length N)."""
        if not hasattr(self, "_postings"):
            self._rebuild_accel()
        q_terms = tokenize(query)
        scores = np.zeros(self.N, dtype=np.float64)
        if not q_terms or self.N == 0:
            return scores
        k1p1 = self.k1 + 1.0
        postings = self._postings
        denom = self._denom
        idf_map = self.idf
        for t in q_terms:
            packed = postings.get(t)
            if packed is None:
                continue
            docs, f = packed
            idf = idf_map.get(t, 0.0)
            if idf == 0.0:
                continue
            scores[docs] += idf * (f * k1p1) / (f + denom[docs])
        return scores

    def search(self, query: str, top_k: int = 50) -> list[tuple[int, float]]:
        return top_hits_from_scores(self.score_all(query), top_k, drop_nonpositive=True)
