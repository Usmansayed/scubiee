"""One integrated retriever: min-rank fusion of Graphify + BM25+dense.

Each file keeps its best rank across Graphify affinity and Claude Context–style
hybrid (BM25+dense RRF). Agreement improves rank slightly. Chunk choice inside
a file uses all three channel masses. Not three tools — one file ranking.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from conductor.bm25_index import BM25Index
from conductor.dense_index import DenseIndex
from conductor.graphify_retriever import GraphifyChunkRetriever
from conductor.rrf import weighted_rrf


@dataclass(frozen=True)
class Hit:
    chunk_id: int
    score: float
    file: str
    source: str = ""
    graph: float = 0.0
    bm25: float = 0.0
    dense: float = 0.0


@dataclass(frozen=True)
class ConductorConfig:
    rrf_k: int = 60
    bm25_weight: float = 1.0
    dense_weight: float = 0.5
    w_graph: float = 1.0
    w_bm25: float = 1.0
    w_dense: float = 0.7
    agree_bonus: float = 0.6
    candidate_pool: int = 80
    expand_file_cap: int = 16
    iterations: int = 1
    eps: float = 1e-6


@dataclass
class Conductor:
    files: list[str]
    bm25: BM25Index
    dense: DenseIndex
    graph: GraphifyChunkRetriever
    config: ConductorConfig = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.config is None:
            self.config = ConductorConfig()
        self._n = len(self.files)
        self._file_chunks: dict[str, list[int]] = {}
        for i, f in enumerate(self.files):
            self._file_chunks.setdefault(f.replace("\\", "/"), []).append(i)

    def _file_of(self, chunk_id: int) -> str:
        return self.files[chunk_id].replace("\\", "/")

    def retrieve_graphify(self, query: str, top_k: int = 5) -> list[Hit]:
        ids = self.graph.query_ranked_chunks(query, top_k=max(top_k, self.config.candidate_pool))
        return [
            Hit(chunk_id=i, score=1.0 / (rank + 1), file=self._file_of(i), source="graphify")
            for rank, i in enumerate(ids[:top_k])
        ]

    def retrieve_hybrid(self, query: str, query_vec: np.ndarray, top_k: int = 5) -> list[Hit]:
        cfg = self.config
        bm25_ids = [i for i, _ in self.bm25.search(query, top_k=cfg.candidate_pool)]
        dense_ids = [i for i, _ in self.dense.search(query_vec, top_k=cfg.candidate_pool)]
        fused = weighted_rrf(
            {"bm25": bm25_ids, "dense": dense_ids},
            {"bm25": cfg.bm25_weight, "dense": cfg.dense_weight},
            k=cfg.rrf_k,
        )
        return [
            Hit(chunk_id=i, score=s, file=self._file_of(i), source="hybrid")
            for i, s in fused[:top_k]
        ]

    def _file_rank_from_scores(self, vals: np.ndarray) -> list[str]:
        order = np.argsort(-vals)
        out: list[str] = []
        seen: set[str] = set()
        for i in order:
            if vals[int(i)] <= 0:
                break
            f = self._file_of(int(i))
            if f not in seen:
                out.append(f)
                seen.add(f)
            if len(out) >= self.config.candidate_pool:
                break
        return out

    def retrieve_conductor(self, query: str, query_vec: np.ndarray, top_k: int = 5) -> list[Hit]:
        cfg = self.config
        n = self._n

        g_aff, seed_files, _ = self.graph.affinity_scores(query, n)
        b_all = self.bm25.score_all(query)
        d_all = self.dense.score_all(query_vec).astype(np.float64)

        hybrid_chunk = np.zeros(n, dtype=np.float64)
        rb = {int(i): r for r, (i, _) in enumerate(self.bm25.search(query, top_k=cfg.candidate_pool), 1)}
        rd = {int(i): r for r, (i, _) in enumerate(self.dense.search(query_vec, top_k=cfg.candidate_pool), 1)}
        for cid in set(rb) | set(rd):
            hybrid_chunk[cid] = cfg.bm25_weight / (cfg.rrf_k + rb.get(cid, 10_000)) + cfg.dense_weight / (
                cfg.rrf_k + rd.get(cid, 10_000)
            )

        g_files = self._file_rank_from_scores(g_aff)
        h_files = self._file_rank_from_scores(hybrid_chunk)

        best_rank: dict[str, float] = {}
        for r, f in enumerate(g_files, 1):
            best_rank[f] = float(r)
        for r, f in enumerate(h_files, 1):
            prev = best_rank.get(f)
            best_rank[f] = float(r) if prev is None else min(prev, float(r))

        both = set(g_files[:25]) & set(h_files[:25])
        for f in both:
            best_rank[f] = max(1.0, best_rank[f] - cfg.agree_bonus)

        for f in self.graph.neighbor_files(seed_files + g_files[:5] + h_files[:5], cap=cfg.expand_file_cap):
            if f not in best_rank:
                best_rank[f] = 45.0

        ordered_files = sorted(best_rank.keys(), key=lambda f: (best_rank[f], f))
        g_set = set(g_files[:40])
        h_set = set(h_files[:40])

        hits_out: list[Hit] = []
        for rank, f in enumerate(ordered_files):
            cids = self._file_chunks.get(f, [])
            if not cids:
                continue
            best_i = cids[0]
            best_s = -1.0
            for i in cids:
                s = float(g_aff[i]) + float(b_all[i]) + 40.0 * float(d_all[i])
                if s > best_s:
                    best_s = s
                    best_i = i
            if f in both:
                src = "both"
            elif f in g_set:
                src = "graph"
            else:
                src = "hybrid"
            hits_out.append(
                Hit(
                    chunk_id=best_i,
                    score=1.0 / best_rank[f],
                    file=f,
                    source=src,
                    graph=float(g_aff[best_i]),
                    bm25=float(b_all[best_i]),
                    dense=float(d_all[best_i]),
                )
            )
            if len(hits_out) >= top_k:
                break
        return hits_out

    def explain(self, query: str, query_vec: np.ndarray) -> dict:
        hits = self.retrieve_conductor(query, query_vec, top_k=5)
        return {
            "mode": "integrated_minrank",
            "top_channels": [
                {
                    "file": h.file,
                    "score": round(h.score, 4),
                    "source": h.source,
                    "graph": round(h.graph, 3),
                    "bm25": round(h.bm25, 3),
                    "dense": round(h.dense, 4),
                }
                for h in hits
            ],
        }
