"""Semantic comparators for tracer R&D — query/seed/edge/path/trace-state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from trace_lab.embed_field import EmbedField
from trace_lab.semantic_index import SemanticIndex, from_embed_field
from trace_lab.types import TraceNode

W_QUERY = 0.6
W_SEED = 0.4
W_EDGE_QUERY = 0.5
W_EDGE_DST = 0.5
# Cycle 2 blend when trace centroid is active
W_EDGE_NODE = 0.55
W_EDGE_TRACE = 0.45


def edge_text(src_symbol: str, rel: str, dst_symbol: str) -> str:
    return f"{src_symbol} --{rel}--> {dst_symbol}"


@dataclass
class SemanticComparator:
    """Caches query/seed vectors and node affinities for a single case."""

    index: SemanticIndex
    nodes: dict[str, TraceNode]
    query: str
    seed_id: str
    w_query: float = W_QUERY
    w_seed: float = W_SEED
    use_edge_text: bool = False  # True = embed edge strings (slow); False = node/trace only
    _q_aff: dict[str, float] = field(default_factory=dict)
    _s_aff: dict[str, float] = field(default_factory=dict)
    _edge_cache: dict[tuple[str, str, str], float] = field(default_factory=dict)
    _q_vec: np.ndarray | None = field(default=None, repr=False)
    _trace_vec: np.ndarray | None = field(default=None, repr=False)
    _hub_prior: np.ndarray | None = field(default=None, repr=False)

    @classmethod
    def from_field(
        cls,
        field_or_index: EmbedField | SemanticIndex,
        nodes: dict[str, TraceNode],
        *,
        query: str,
        seed_id: str,
        w_query: float = W_QUERY,
        w_seed: float = W_SEED,
        use_edge_text: bool = False,
        graph_degree: dict[str, int] | None = None,
    ) -> SemanticComparator:
        index = (
            field_or_index
            if isinstance(field_or_index, SemanticIndex)
            else from_embed_field(field_or_index)
        )
        cmp = cls(
            index=index,
            nodes=nodes,
            query=query,
            seed_id=seed_id,
            w_query=w_query,
            w_seed=w_seed,
            use_edge_text=use_edge_text,
        )
        cmp._q_aff = index.query_affinities(query)
        cmp._s_aff = index.seed_affinities(seed_id)
        cmp._q_vec = index.field.embed_query(query)
        # Seed as initial trace state
        if seed_id in index.field._by_id:  # noqa: SLF001
            cmp._trace_vec = index.field.vec(seed_id).copy()
        if graph_degree:
            cmp._hub_prior = index.field.hub_prior(graph_degree, top=5)
        return cmp

    def node_sim(self, nid: str) -> float:
        q = float(self._q_aff.get(nid, 0.0))
        s = float(self._s_aff.get(nid, 1.0 if nid == self.seed_id else 0.0))
        return self.w_query * q + self.w_seed * s

    def trace_sim(self, nid: str) -> float:
        """Similarity to evolving investigation centroid (Cycle 2)."""
        if self._trace_vec is None or nid not in self.index.field._by_id:  # noqa: SLF001
            return self.node_sim(nid)
        v = self.index.field.vec(nid)
        raw = float(np.dot(self._trace_vec, v))
        return max(0.0, min(1.0, raw))

    def hub_penalty(self, nid: str) -> float:
        """Return multiplier in (0,1]: lower for hub-like generics with weak task affinity."""
        if self._hub_prior is None or nid not in self.index.field._by_id:  # noqa: SLF001
            return 1.0
        v = self.index.field.vec(nid)
        hub_sim = float(np.dot(self._hub_prior, v))
        hub_sim = max(0.0, min(1.0, hub_sim))
        task = self.node_sim(nid)
        # High hub pull + low task affinity → demote
        residual = task - 0.55 * hub_sim
        if residual >= 0:
            return 1.0
        return max(0.35, 1.0 + residual)  # residual negative → shrink

    def refresh_trace(
        self,
        scores: dict[str, float],
        *,
        top_k: int = 6,
        min_score: float = 0.35,
    ) -> None:
        """Weighted centroid of current high-heat nodes (trace-state vector)."""
        ranked = sorted(
            ((nid, sc) for nid, sc in scores.items() if sc >= min_score),
            key=lambda kv: -kv[1],
        )[:top_k]
        if not ranked:
            return
        vecs: list[np.ndarray] = []
        weights: list[float] = []
        for nid, sc in ranked:
            if nid not in self.index.field._by_id:  # noqa: SLF001
                continue
            vecs.append(self.index.field.vec(nid))
            weights.append(max(0.05, float(sc)))
        if not vecs:
            return
        w = np.asarray(weights, dtype=np.float32)
        w = w / float(w.sum())
        m = np.zeros_like(vecs[0])
        for wi, vi in zip(w, vecs, strict=True):
            m = m + wi * vi
        n = float(np.linalg.norm(m)) or 1.0
        self._trace_vec = (m / n).astype(np.float32)
        self._edge_cache.clear()

    def edge_sim(self, src_id: str, rel: str, dst_id: str) -> float:
        key = (src_id, rel, dst_id)
        if key in self._edge_cache:
            return self._edge_cache[key]
        dst_sem = self.node_sim(dst_id)
        tr = self.trace_sim(dst_id)
        if self.use_edge_text:
            src = self.nodes.get(src_id)
            dst = self.nodes.get(dst_id)
            src_sym = src.symbol if src else src_id
            dst_sym = dst.symbol if dst else dst_id
            text = edge_text(src_sym, rel, dst_sym)
            qv = self._q_vec
            if qv is None:
                edge_q = 0.0
            else:
                ev = self.index.field.embed_query(text)
                edge_q = max(0.0, min(1.0, float(np.dot(qv, ev))))
            out = 0.35 * edge_q + 0.35 * dst_sem + 0.30 * tr
        else:
            # Fast path: node + trace comparators only (Cycle 2 default)
            out = W_EDGE_NODE * dst_sem + W_EDGE_TRACE * tr
        out *= self.hub_penalty(dst_id)
        self._edge_cache[key] = out
        return out

    def path_sim(self, path: tuple[str, ...]) -> float:
        """Mean node_sem along path excluding seed (first element if seed)."""
        if not path:
            return 0.0
        ids = list(path)
        if ids and ids[0] == self.seed_id:
            ids = ids[1:]
        if not ids:
            return 1.0
        return sum(self.node_sim(n) for n in ids) / len(ids)

    def information_gain(self, nid: str, admitted: set[str]) -> float:
        """Rough novelty: high if dissimilar to already-admitted high set."""
        if not admitted or nid not in self.index.field._by_id:  # noqa: SLF001
            return self.node_sim(nid)
        v = self.index.field.vec(nid)
        sims = []
        for a in list(admitted)[:24]:
            if a not in self.index.field._by_id:  # noqa: SLF001
                continue
            sims.append(float(np.dot(v, self.index.field.vec(a))))
        if not sims:
            return self.node_sim(nid)
        max_sim = max(sims)
        novelty = 1.0 - max(0.0, min(1.0, max_sim))
        return 0.5 * self.node_sim(nid) + 0.5 * novelty

    def meta(self) -> dict[str, Any]:
        return {
            **self.index.meta(),
            "w_query": self.w_query,
            "w_seed": self.w_seed,
            "seed_id": self.seed_id,
            "use_edge_text": self.use_edge_text,
            "has_trace_vec": self._trace_vec is not None,
            "has_hub_prior": self._hub_prior is not None,
        }
