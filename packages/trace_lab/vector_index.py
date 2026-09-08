"""Deterministic hashed n-gram dense index for trace-lab (no embedding model).

This is real vector search over TraceNodes: each node and query become a
fixed-dim L2-normalized vector; retrieval is cosine. It does not need a
trained encoder, so the sim stays offline and reproducible. Product code
can swap this for FAISS + a real embedding model with the same API.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter

import numpy as np

from conductor.bm25_index import tokenize
from conductor.bm25_index import tokenize
from conductor.dense_index import DenseIndex
from trace_lab.types import TraceNode

_WORD = re.compile(r"[a-z0-9_]+", re.I)


def _char_ngrams(text: str, n: int = 3) -> list[str]:
    s = re.sub(r"\s+", " ", text.lower()).strip()
    if len(s) < n:
        return [s] if s else []
    return [s[i : i + n] for i in range(len(s) - n + 1)]


def _features(text: str) -> Counter[str]:
    feats: Counter[str] = Counter()
    for t in tokenize(text):
        feats[f"t:{t}"] += 2
    for w in _WORD.findall(text.lower()):
        feats[f"w:{w}"] += 1
        for ng in _char_ngrams(w, 3):
            feats[f"c:{ng}"] += 1
    for ng in _char_ngrams(text, 3)[:400]:
        feats[f"s:{ng}"] += 1
    return feats


def _hash_bucket(feat: str, dim: int) -> int:
    h = hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(h, "little") % dim


def embed_text(text: str, *, dim: int = 256) -> np.ndarray:
    """Signed hashed bag-of-features → L2 unit vector."""
    vec = np.zeros(dim, dtype=np.float32)
    for feat, cnt in _features(text).items():
        i = _hash_bucket(feat, dim)
        sign = 1.0 if (hashlib.blake2b(feat.encode(), digest_size=1).digest()[0] & 1) == 0 else -1.0
        vec[i] += sign * float(cnt)
    n = float(np.linalg.norm(vec))
    if n > 0:
        vec /= n
    return vec


class VectorIndex:
    """Dense cosine over symbol nodes (path + symbol + body)."""

    def __init__(self, nodes: dict[str, TraceNode], *, dim: int = 256):
        self.ids = list(nodes.keys())
        self.nodes = nodes
        self.dim = dim
        texts = [
            f"{n.file} {n.symbol} {n.lex_text or n.text}" for n in nodes.values()
        ]
        mat = np.stack([embed_text(t, dim=dim) for t in texts], axis=0)
        self.dense = DenseIndex(mat)

    def scores(self, query: str) -> dict[str, float]:
        q = embed_text(query, dim=self.dim)
        raw = self.dense.score_all(q)
        return {self.ids[i]: float(raw[i]) for i in range(len(self.ids))}

    def top_k(self, query: str, k: int = 8) -> list[tuple[str, float]]:
        ranked = sorted(self.scores(query).items(), key=lambda kv: -kv[1])
        return ranked[:k]


def hybrid_map_scores(
    query: str,
    lex,
    vec: VectorIndex,
    *,
    bm25_weight: float = 0.45,
) -> dict[str, float]:
    """Blend BM25 + dense cosine the way product `map` does."""
    from trace_lab.retrieve import expand_query, normalize

    expanded = expand_query(query)
    bm = normalize(lex.bm25_scores(expanded))
    dn = normalize(vec.scores(expanded))
    ids = set(bm) | set(dn)
    out: dict[str, float] = {}
    for nid in ids:
        out[nid] = bm25_weight * bm.get(nid, 0.0) + (1.0 - bm25_weight) * dn.get(nid, 0.0)
    return out


_HUB_MARKERS = (
    "/logger.py",
    "/http/client.py",
    "/analytics/",
)


def pick_seed(
    query: str,
    nodes: dict[str, TraceNode],
    scores: dict[str, float],
    *,
    prefer_kinds: set[str] | None = None,
    intent: str | None = None,
) -> str | None:
    """Choose a seed TraceNode from map scores (skip bare classes / hubs)."""
    from trace_lab.retrieve import query_intent

    prefer_kinds = prefer_kinds or {"function", "method", "const"}
    intent = intent or query_intent(query)
    if intent == "refs":
        prefer_kinds = {"const", "function", "method"}
    ql = query.lower()
    qtoks = set(tokenize(query.lower()))
    allow_logger = bool(qtoks & {"log", "logger", "logging", "printing", "print"})
    allow_http = bool(qtoks & {"http", "pay", "payment", "bill", "billing", "cents", "get"})

    def hub_penalty(nid: str) -> float:
        n = nodes.get(nid)
        if n is None:
            return 0.0
        p = "/" + n.file.replace("\\", "/")
        if any(m in p for m in _HUB_MARKERS):
            if "logger" in p and not allow_logger:
                return 0.55
            if "/http/" in p and not allow_http:
                return 0.45
            if "/analytics/" in p:
                return 0.5
        return 0.0

    def topic_boost(nid: str) -> float:
        n = nodes.get(nid)
        if n is None:
            return 0.0
        p = n.file.replace("\\", "/").lower()
        boost = 0.0
        if any(t in qtoks for t in ("login", "logged", "credential", "bearer", "auth", "jwt", "claims")):
            if "/middleware/auth" in p or "/jwt" in p or "/login" in p:
                boost += 0.35
        if any(t in ql for t in ("bill", "payment", "cents", "pay api", "outbound payment")):
            if "/billing/" in p:
                boost += 0.4
        if any(t in qtoks for t in ("welcome", "emit", "event", "handler", "fire")):
            if "/events/" in p or "/handlers/" in p:
                boost += 0.4
        if any(t in qtoks for t in ("queue", "worker", "job", "digest")):
            if "/jobs/" in p:
                boost += 0.4
        if "cors" in qtoks and "/cors" in p:
            boost += 0.5
        if any(t in qtoks for t in ("health", "probe")) and "/health" in p:
            boost += 0.5
        if "session" in qtoks and "/session" in p:
            boost += 0.45
        if any(t in qtoks for t in ("store", "fetch", "memory")) and "/stores/" in p:
            boost += 0.4
        if any(t in ql for t in ("ttl", "timeout", "expiry", "kicked", "hour")):
            if "TOKEN_TTL" in n.symbol or "/security" in p or "/jwt" in p:
                boost += 0.35
        return boost

    adjusted: list[tuple[str, float]] = []
    for nid, sc in scores.items():
        if sc <= 0:
            continue
        adj = sc - hub_penalty(nid) + topic_boost(nid)
        adjusted.append((nid, adj))
    ranked = sorted(adjusted, key=lambda kv: -kv[1])

    for nid, sc in ranked:
        n = nodes.get(nid)
        if n is None or n.kind not in prefer_kinds:
            continue
        short = n.symbol.split(".")[-1].lower()
        if short in qtoks or short.lower() in ql:
            return nid
    for nid, sc in ranked:
        n = nodes.get(nid)
        if n is None or n.kind not in prefer_kinds:
            continue
        return nid
    for nid, sc in ranked:
        if nid in nodes:
            return nid
    return None
