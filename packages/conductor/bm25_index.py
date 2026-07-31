"""Okapi BM25 over tokenized chunk texts."""

from __future__ import annotations

import math
import re
from collections import Counter

import numpy as np

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


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

    def score_all(self, query: str) -> np.ndarray:
        """Return BM25 score for every doc (float64 length N)."""
        q_terms = tokenize(query)
        scores = np.zeros(self.N, dtype=np.float64)
        if not q_terms or self.N == 0:
            return scores
        for i, tf in enumerate(self._tf):
            dl = self.doc_len[i]
            denom_norm = self.k1 * (1 - self.b + self.b * dl / max(self.avgdl, 1e-9))
            s = 0.0
            for t in q_terms:
                if t not in tf:
                    continue
                idf = self.idf.get(t, 0.0)
                f = tf[t]
                s += idf * (f * (self.k1 + 1)) / (f + denom_norm)
            scores[i] = s
        return scores

    def search(self, query: str, top_k: int = 50) -> list[tuple[int, float]]:
        scores = self.score_all(query)
        if self.N == 0:
            return []
        ranked = np.argsort(-scores)
        out: list[tuple[int, float]] = []
        for i in ranked[:top_k]:
            if scores[i] <= 0:
                break
            out.append((int(i), float(scores[i])))
        return out
