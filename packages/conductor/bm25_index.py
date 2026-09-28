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
        self._dead_idx = None
        self._publish_snapshot()

    def _publish_snapshot(self) -> None:
        # One attribute swap so a concurrent score_all never mixes a new postings
        # table (ids past the old N) with an old length-norm array.
        self._snap = (self._postings, self._denom, self.idf, getattr(self, "_dead_idx", None))

    def _current(self) -> tuple:
        snap = getattr(self, "_snap", None)
        if snap is None:  # pickled by an older build
            if not hasattr(self, "_postings"):
                self._rebuild_accel()
            else:
                self._publish_snapshot()
            snap = self._snap
        return snap

    def append_docs(self, texts: list[str]) -> int:
        """Add docs at positions N.. without a full rebuild (hot publish).

        Postings, lengths and avgdl are exact. IDF is refreshed for the new
        docs' terms; other terms keep weights computed for the previous N until
        the next full rebuild (N moves by a handful of chunks per save).
        Returns the new N.
        """
        if not texts:
            return self.N
        postings, denom, idf, dead = self._current()
        start = int(denom.shape[0])
        new_docs = [tokenize(t) for t in texts]
        new_tf = [Counter(d) for d in new_docs]
        new_len = [len(d) for d in new_docs]
        n_new = start + len(new_docs)
        doc_len = list(self.doc_len[:start]) + new_len
        avgdl = sum(doc_len) / max(n_new, 1)
        new_denom = np.asarray(
            self.k1 * (1.0 - self.b + self.b * np.asarray(doc_len, dtype=np.float64) / max(avgdl, 1e-9)),
            dtype=np.float64,
        )
        buckets: dict[str, list[int]] = defaultdict(list)
        freqs: dict[str, list[float]] = defaultdict(list)
        for j, tf in enumerate(new_tf):
            for t, f in tf.items():
                buckets[t].append(start + j)
                freqs[t].append(float(f))
        new_postings = dict(postings)
        new_idf = dict(idf)
        for t, ids in buckets.items():
            old = postings.get(t)
            add_ids = np.asarray(ids, dtype=np.int32)
            add_f = np.asarray(freqs[t], dtype=np.float64)
            if old is None:
                new_postings[t] = (add_ids, add_f)
            else:
                new_postings[t] = (np.concatenate([old[0], add_ids]), np.concatenate([old[1], add_f]))
            df = int(new_postings[t][0].size)
            new_idf[t] = math.log(1.0 + (n_new - df + 0.5) / (df + 0.5))
        self.docs.extend(new_docs)
        self._tf.extend(new_tf)
        self.doc_len = doc_len
        self.avgdl = avgdl
        self.idf = new_idf
        self._postings = new_postings
        self._denom = new_denom
        self.N = n_new
        self._dead_idx = dead
        self._publish_snapshot()
        return n_new

    def mark_dead(self, positions: list[int]) -> None:
        """Tombstoned chunks (edited away / deleted) score 0 until the next rebuild."""
        pos = [int(p) for p in positions if 0 <= int(p) < self.N]
        if not pos:
            return
        postings, denom, idf, dead = self._current()
        merged = set(int(i) for i in (dead.tolist() if dead is not None else [])) | set(pos)
        self._dead_idx = np.asarray(sorted(merged), dtype=np.int64)
        self._publish_snapshot()

    def score_all(self, query: str) -> np.ndarray:
        """Return BM25 score for every doc (float64 length N)."""
        postings, denom, idf_map, dead = self._current()
        q_terms = tokenize(query)
        n = int(denom.shape[0])
        scores = np.zeros(n, dtype=np.float64)
        if not q_terms or n == 0:
            return scores
        k1p1 = self.k1 + 1.0
        for t in q_terms:
            packed = postings.get(t)
            if packed is None:
                continue
            docs, f = packed
            idf = idf_map.get(t, 0.0)
            if idf == 0.0:
                continue
            scores[docs] += idf * (f * k1p1) / (f + denom[docs])
        if dead is not None and dead.size:
            scores[dead] = 0.0
        return scores

    def search(self, query: str, top_k: int = 50) -> list[tuple[int, float]]:
        return top_hits_from_scores(self.score_all(query), top_k, drop_nonpositive=True)
