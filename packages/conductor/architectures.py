"""Research-backed fusion architectures over Graphify + BM25 + dense.

A  minrank_expand   — min-rank + basename/symbol expand boost
B  ppr_dual_seed    — HippoRAG-style personalized PageRank on dual seeds
C  gear_expand      — hybrid pool → graph expand → re-RRF (GEAR-like)
D  hybrid_rerank    — fusion pool + lexical cross-encoder stand-in rerank
E  multiprobe       — query split into lexical probes + paraphrase; fuse
F  f95              — A + stem bridge + role alias + siblings + negation
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import networkx as nx
import numpy as np

from conductor.bm25_index import tokenize
from conductor.conductor import Conductor, ConductorConfig, Hit
from conductor import f95 as f95mod
from conductor.fusion_math import (
    adaptive_weights_from_peakiness,
    channel_peakiness,
    fuse_combmnz,
    fuse_combsum,
    fuse_condorcet,
    logisr_score,
    rrf_score,
)
from conductor.query_router import (
    lexical_graph_confidence,
    path_likeness,
    query_state,
    route_mode,
)
from conductor.rrf import weighted_rrf

_CAMEL = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\W|$)|\d+")


def _path_tokens(path: str) -> set[str]:
    return f95mod.path_tokens(path)


def _query_key_tokens(query: str) -> set[str]:
    return f95mod.query_key_tokens(query)


def _ident_tokens(query: str) -> set[str]:
    # Snake_case / camelCase identifiers named in the query, so an explicit
    # symbol name in the question can bias chunk selection toward its definition.
    return {
        t.lower()
        for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{5,}", query or "")
        if "_" in t or any(c.isupper() for c in t[1:])
    }


def _znorm(vals: dict[str, float]) -> dict[str, float]:
    """Z-score a channel over the pool so channels mix on a common scale.

    Absent signal (score 0) maps to 0 rather than a negative z, so a channel that
    simply did not fire cannot push a candidate below one it never scored.
    """
    xs = [v for v in vals.values() if v > 0]
    if len(xs) < 2:
        return dict.fromkeys(vals, 0.0)
    mu = sum(xs) / len(xs)
    sd = (sum((x - mu) ** 2 for x in xs) / len(xs)) ** 0.5 or 1.0
    return {k: ((v - mu) / sd if v > 0 else 0.0) for k, v in vals.items()}


class MultiArchConductor(Conductor):
    """Conductor with five retrieve_* architectures."""

    def _channel_maps(self, query: str, query_vec: np.ndarray):
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
        return g_aff, b_all, d_all, hybrid_chunk, seed_files

    def _best_chunk(
        self, f: str, g_aff, b_all, d_all, query: str = ""
    ) -> int:
        # Pick the chunk inside a file. When the query names an identifier,
        # prefer the chunk whose body defines it over a nearby helper.
        cids = self._file_chunks.get(f, [])
        if not cids:
            return -1
        idents = _ident_tokens(query)
        qtoks = set(tokenize(query)) if query else set()
        # Long underscore tokens are strong intent (function / route names).
        strong = {t for t in (idents | qtoks) if "_" in t and len(t) >= 8}
        best_i, best_s = cids[0], -1e18
        docs = getattr(self.bm25, "docs", None)
        for i in cids:
            s = float(g_aff[i]) + float(b_all[i]) + 40.0 * float(d_all[i])
            if docs is not None and 0 <= i < len(docs):
                doc_set = set(docs[i])
                if strong and any(t in doc_set for t in strong):
                    s += 80.0
                elif idents and any(t in doc_set for t in idents):
                    s += 25.0
            if s > best_s:
                best_s, best_i = s, i
        return best_i

    def _hits_from_files(
        self,
        ordered: list[str],
        g_aff,
        b_all,
        d_all,
        top_k: int,
        source: str,
        scores: dict[str, float] | None = None,
        query: str = "",
    ) -> list[Hit]:
        out: list[Hit] = []
        for rank, f in enumerate(ordered):
            i = self._best_chunk(f, g_aff, b_all, d_all, query=query)
            if i < 0:
                continue
            sc = scores.get(f, 1.0 / (rank + 1)) if scores else 1.0 / (rank + 1)
            out.append(
                Hit(
                    chunk_id=i,
                    score=float(sc),
                    file=f,
                    source=source,
                    graph=float(g_aff[i]),
                    bm25=float(b_all[i]),
                    dense=float(d_all[i]),
                )
            )
            if len(out) >= top_k:
                break
        return out

    def _minrank_files(self, g_files: list[str], h_files: list[str], seed_files: list[str]) -> list[str]:
        cfg = self.config
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
        return sorted(best_rank.keys(), key=lambda f: (best_rank[f], f))

    # ----- A: minrank + path/symbol expand -----
    def retrieve_A_minrank_expand(self, query: str, query_vec: np.ndarray, top_k: int = 10) -> list[Hit]:
        g_aff, b_all, d_all, hybrid_chunk, seed_files = self._channel_maps(query, query_vec)
        g_files = self._file_rank_from_scores(g_aff)
        h_files = self._file_rank_from_scores(hybrid_chunk)
        ordered = self._minrank_files(g_files, h_files, seed_files)

        qtoks = _query_key_tokens(query)
        # Boost files whose basename/path tokens overlap query keys
        scored: list[tuple[float, str]] = []
        for rank, f in enumerate(ordered):
            base = 1.0 / (60 + rank + 1)
            overlap = len(qtoks & _path_tokens(f))
            # basename exact-ish
            bn = Path(f).stem.lower()
            if bn in qtoks or any(bn.startswith(t) or t in bn for t in qtoks if len(t) >= 4):
                overlap += 3
            scored.append((-(base * (1.0 + 0.35 * overlap)), f))
        scored.sort()
        ordered2 = [f for _, f in scored]
        return self._hits_from_files(ordered2, g_aff, b_all, d_all, top_k, "A_minrank_expand")

    # ----- B: PPR dual-seed (HippoRAG-style) -----
    def retrieve_B_ppr(self, query: str, query_vec: np.ndarray, top_k: int = 10) -> list[Hit]:
        g_aff, b_all, d_all, hybrid_chunk, seed_files = self._channel_maps(query, query_vec)
        G = self.graph.G
        # Personalization: Graphify seeds + nodes in top hybrid files
        personalization: dict[str, float] = defaultdict(float)
        from graphify.serve import _pick_seeds, _query_terms, _score_query

        terms = _query_terms(query)
        qs = _score_query(G, terms, collect_per_term_seeds=True)
        seeds = _pick_seeds(qs.ranked, G=G, best_seed_by_term=qs.best_seed_by_term)
        score_map = {nid: float(sc) for sc, nid in qs.ranked}
        for nid in seeds[:20]:
            personalization[nid] += max(score_map.get(nid, 1.0), 1.0)

        h_files = self._file_rank_from_scores(hybrid_chunk)[:15]
        for f in h_files:
            for s in self.graph._by_file.get(f.replace("\\", "/"), [])[:3]:
                # map chunk back — use file nodes from graph
                pass
        # file → any graph node
        file_nodes: dict[str, list[str]] = defaultdict(list)
        for nid, d in G.nodes(data=True):
            src = str(d.get("source_file") or "").replace("\\", "/")
            if src:
                file_nodes[src].append(nid)
        for rank, f in enumerate(h_files, 1):
            weight = 1.0 / rank
            for nid in file_nodes.get(f, [])[:8]:
                personalization[nid] += 25.0 * weight

        if not personalization:
            return self.retrieve_A_minrank_expand(query, query_vec, top_k)

        # Normalize personalization
        total = sum(personalization.values())
        pers = {k: v / total for k, v in personalization.items()}
        try:
            pr = nx.pagerank(G, alpha=0.85, personalization=pers, max_iter=50, tol=1e-4)
        except Exception:
            return self.retrieve_A_minrank_expand(query, query_vec, top_k)

        # Aggregate PageRank mass to files, amplify by BM25/dense
        file_mass: dict[str, float] = defaultdict(float)
        for nid, mass in pr.items():
            src = str(G.nodes[nid].get("source_file") or "").replace("\\", "/")
            if not src:
                continue
            file_mass[src] += mass

        # Amplify with channel norms at file level
        b_files = self._file_rank_from_scores(b_all)
        d_files = self._file_rank_from_scores(d_all)
        rb = {f: r for r, f in enumerate(b_files, 1)}
        rd = {f: r for r, f in enumerate(d_files, 1)}
        scored = []
        for f, mass in file_mass.items():
            amp = 1.0
            if f in rb:
                amp += 0.5 / (1 + rb[f])
            if f in rd:
                amp += 0.35 / (1 + rd[f])
            scored.append((-(mass * amp), f))
        scored.sort()
        ordered = [f for _, f in scored]
        return self._hits_from_files(ordered, g_aff, b_all, d_all, top_k, "B_ppr")

    # ----- C: GEAR-like hybrid → expand → re-fuse -----
    def retrieve_C_gear(self, query: str, query_vec: np.ndarray, top_k: int = 10) -> list[Hit]:
        cfg = self.config
        g_aff, b_all, d_all, hybrid_chunk, seed_files = self._channel_maps(query, query_vec)
        # Stage 1: hybrid file ranking
        h_files = self._file_rank_from_scores(hybrid_chunk)[:40]
        g_files = self._file_rank_from_scores(g_aff)[:40]
        # Stage 2: expand from hybrid top + graphify seeds
        expanded = list(h_files[:20])
        seen = set(expanded)
        for f in self.graph.neighbor_files(h_files[:12] + seed_files, cap=32):
            if f not in seen:
                expanded.append(f)
                seen.add(f)
        # Stage 3: re-RRF over graph ranks ∩ expanded set + hybrid ranks
        eg = [f for f in g_files if f in seen] + [f for f in expanded if f not in set(g_files)]
        eh = [f for f in h_files if f in seen] + [f for f in expanded if f not in set(h_files)]
        # Also basename boost inside expanded
        qtoks = _query_key_tokens(query)
        fused = weighted_rrf(
            {"graph": list(range(len(eg))), "hybrid": list(range(len(eh)))},
            {"graph": 1.0, "hybrid": 1.0},
            k=cfg.rrf_k,
        )
        # Map indices back — easier: score files directly
        rg = {f: r for r, f in enumerate(eg, 1)}
        rh = {f: r for r, f in enumerate(eh, 1)}
        scores: dict[str, float] = {}
        for f in seen:
            s = 0.0
            if f in rg:
                s += 1.0 / (cfg.rrf_k + rg[f])
            if f in rh:
                s += 1.0 / (cfg.rrf_k + rh[f])
            ov = len(qtoks & _path_tokens(f))
            s *= 1.0 + 0.25 * ov
            scores[f] = s
        ordered = sorted(scores.keys(), key=lambda f: (-scores[f], f))
        return self._hits_from_files(ordered, g_aff, b_all, d_all, top_k, "C_gear", scores)

    # ----- D: fusion + lexical rerank (cross-encoder stand-in) -----
    def _d_rerank_score(self, query: str, h: Hit) -> float:
        qtoks = _query_key_tokens(query)
        qset = set(tokenize(query))
        ftoks = _path_tokens(h.file)
        path_ov = len(qtoks & ftoks) + len(qset & ftoks)
        bn = Path(h.file).stem.lower()
        exact = 2.0 if bn in qtoks else 0.0
        return exact + 0.8 * path_ov + 0.15 * h.bm25 + 8.0 * h.dense + 0.02 * h.graph

    def _hits_from_pool_d_score(
        self, query: str, pool: list[Hit], top_k: int, source: str
    ) -> list[Hit]:
        ranked = sorted(pool, key=lambda h: -self._d_rerank_score(query, h))
        out: list[Hit] = []
        for h in ranked[:top_k]:
            out.append(
                Hit(
                    chunk_id=h.chunk_id,
                    score=self._d_rerank_score(query, h),
                    file=h.file,
                    source=source,
                    graph=h.graph,
                    bm25=h.bm25,
                    dense=h.dense,
                )
            )
        return out

    def _graph_floor_merge(
        self,
        query: str,
        query_vec: np.ndarray,
        base_hits: list[Hit],
        top_k: int,
        source: str,
        *,
        floor_n: int = 2,
        insert: str = "prepend",
        floor_files: list[str] | None = None,
    ) -> list[Hit]:
        """Merge Graphify floor files into the list.

        insert:
          prepend — force floor files to the front (aggressive; taxes MRR/diverse)
          ensure  — keep D top-3; fill next slots with floor files first
        floor_files: optional explicit floor list (else Graphify top floor_n)
        """
        if floor_files is not None:
            g_files = [f.replace("\\", "/") for f in floor_files]
        else:
            g_hits = self.retrieve_graphify(query, top_k=max(floor_n, 10))
            g_files = []
            seen_g: set[str] = set()
            for h in g_hits:
                f = h.file.replace("\\", "/")
                if f not in seen_g:
                    g_files.append(f)
                    seen_g.add(f)
                if len(g_files) >= floor_n:
                    break

        g_aff, b_all, d_all, _, _ = self._channel_maps(query, query_vec)
        by_file: dict[str, Hit] = {}
        for h in base_hits:
            by_file[h.file.replace("\\", "/")] = h

        for f in g_files:
            if f not in by_file:
                cid = self._best_chunk(f, g_aff, b_all, d_all, query=query)
                if cid < 0:
                    continue
                by_file[f] = Hit(
                    chunk_id=cid,
                    score=0.0,
                    file=f,
                    source=source,
                    graph=float(g_aff[cid]),
                    bm25=float(b_all[cid]),
                    dense=float(d_all[cid]),
                )

        ordered = [h.file.replace("\\", "/") for h in base_hits]
        # drop floors not in by_file
        g_files = [f for f in g_files if f in by_file]

        if insert == "ensure":
            # Preserve D top-3; fill remaining top-5 slots with missing G floor files first
            ordered_files: list[str] = []
            seen: set[str] = set()
            for f in ordered:
                if f not in seen and f in by_file:
                    ordered_files.append(f)
                    seen.add(f)
            head = ordered_files[:3]
            head_set = set(head)
            fill: list[str] = []
            for f in g_files:
                if f not in head_set and f not in fill:
                    fill.append(f)
            for f in ordered_files[3:]:
                if f not in head_set and f not in fill:
                    fill.append(f)
            final_files = head + fill
        else:
            for f in reversed(g_files):
                if f in ordered:
                    ordered.remove(f)
                ordered.insert(0, f)
            final_files = []
            seen = set()
            for f in ordered:
                if f not in seen and f in by_file:
                    final_files.append(f)
                    seen.add(f)
            for i, f in enumerate(list(g_files)):
                if f not in final_files:
                    continue
                pos = final_files.index(f)
                if pos >= 5:
                    final_files.pop(pos)
                    final_files.insert(min(i, 4), f)

        out: list[Hit] = []
        for f in final_files[:top_k]:
            h = by_file[f]
            out.append(
                Hit(
                    chunk_id=h.chunk_id,
                    score=self._d_rerank_score(query, h),
                    file=f,
                    source=source,
                    graph=h.graph,
                    bm25=h.bm25,
                    dense=h.dense,
                )
            )
        return out

    def retrieve_D_rerank(self, query: str, query_vec: np.ndarray, top_k: int = 10) -> list[Hit]:
        pool = self.retrieve_A_minrank_expand(query, query_vec, top_k=40)
        return self._hits_from_pool_d_score(query, pool, top_k, "D_rerank")

    def retrieve_V2_adaptive(
        self,
        query: str,
        query_vec: np.ndarray,
        top_k: int = 10,
        *,
        dense_n: int = 40,
        lex_n: int = 15,
    ) -> list[Hit]:
        """Dense-led pool with query-adaptive channel weights.

        Min-rank fusion lets a channel that scored a file zero outvote one that
        ranked it first, which on natural-language queries drops rank-1 dense hits
        out of the pool entirely. Here the dense top-N is guaranteed a seat, and
        lexical influence scales with path_likeness instead of being fixed, so
        identifier queries still get their lexical boost while prose does not.
        """
        g_aff, b_all, d_all, _hybrid, _seeds = self._channel_maps(query, query_vec)
        d_files = self._file_rank_from_scores(d_all)[:dense_n]
        b_files = self._file_rank_from_scores(b_all)[:lex_n]
        g_files = self._file_rank_from_scores(g_aff)[:lex_n]

        pool: list[str] = []
        seen: set[str] = set()
        for lst in (d_files, b_files, g_files):
            for f in lst:
                f = f.replace("\\", "/")
                if f not in seen:
                    seen.add(f)
                    pool.append(f)
        if not pool:
            return self.retrieve_D_rerank(query, query_vec, top_k=top_k)

        # Chunk choice uses the same objective as the ranking, so a file is never
        # scored on a chunk selected by a different formula.
        best: dict[str, int] = {}
        for f in pool:
            cids = self._file_chunks.get(f, [])
            if cids:
                best[f] = max(
                    cids, key=lambda i: float(d_all[i]) + 0.02 * float(b_all[i])
                )
        pool = [f for f in pool if f in best]
        if not pool:
            return self.retrieve_D_rerank(query, query_vec, top_k=top_k)

        p = path_likeness(query)
        w_bm25 = 0.15 + 0.55 * p
        w_graph = 0.05 + 0.35 * p
        w_path = 0.10 + 0.70 * p

        zd = _znorm({f: float(d_all[best[f]]) for f in pool})
        zb = _znorm({f: float(b_all[best[f]]) for f in pool})
        zg = _znorm({f: float(g_aff[best[f]]) for f in pool})

        qtoks = _query_key_tokens(query)
        qset = set(tokenize(query))
        scores: dict[str, float] = {}
        for f in pool:
            ftoks = _path_tokens(f)
            overlap = len(qtoks & ftoks) + len(qset & ftoks)
            exact = 2.0 if Path(f).stem.lower() in qtoks else 0.0
            scores[f] = (
                zd[f]
                + w_bm25 * zb[f]
                + w_graph * zg[f]
                + w_path * (exact + 0.5 * overlap)
            )

        ordered = sorted(pool, key=lambda f: -scores[f])
        out: list[Hit] = []
        for f in ordered[:top_k]:
            i = best[f]
            out.append(
                Hit(
                    chunk_id=i,
                    score=float(scores[f]),
                    file=f,
                    source=f"V2_adaptive:p{p:.2f}",
                    graph=float(g_aff[i]),
                    bm25=float(b_all[i]),
                    dense=float(d_all[i]),
                )
            )
        return out

    def retrieve_V3_evidence(
        self,
        query: str,
        query_vec: np.ndarray,
        top_k: int = 10,
        *,
        dense_n: int = 40,
        lex_n: int = 20,
        floor: float = 0.25,
    ) -> list[Hit]:
        """Fuse channels by how decisively each one points, measured per query.

        Which channel holds the signal moves from query to query: prose questions
        are usually dense's to win, but a graph hub or an exact term can carry one
        outright. Any fixed weighting -- including one keyed off the query's
        surface form -- suppresses the right answer whenever it guesses wrong.
        So each channel's weight comes from how far its own leader stands above
        its own distribution over the pool, and the pool unions every channel so
        no candidate is dropped before that judgement is made.
        """
        g_aff, b_all, d_all, _hybrid, seed_files = self._channel_maps(query, query_vec)
        d_files = self._file_rank_from_scores(d_all)[:dense_n]
        b_files = self._file_rank_from_scores(b_all)[:lex_n]
        g_files = self._file_rank_from_scores(g_aff)[:lex_n]
        try:
            nbrs = list(
                self.graph.neighbor_files(
                    seed_files + g_files[:5] + d_files[:5],
                    cap=self.config.expand_file_cap,
                )
            )
        except Exception:  # noqa: BLE001
            nbrs = []

        pool: list[str] = []
        seen: set[str] = set()
        for lst in (d_files, b_files, g_files, nbrs):
            for f in lst:
                f = f.replace("\\", "/")
                if f not in seen and self._file_chunks.get(f):
                    seen.add(f)
                    pool.append(f)
        if not pool:
            return self.retrieve_D_rerank(query, query_vec, top_k=top_k)

        chan = {"dense": d_all, "bm25": b_all, "graph": g_aff}
        file_scores: dict[str, dict[str, float]] = {}
        for f in pool:
            cids = self._file_chunks[f]
            file_scores[f] = {
                name: max(float(arr[i]) for i in cids) for name, arr in chan.items()
            }

        z = {
            name: _znorm({f: file_scores[f][name] for f in pool}) for name in chan
        }
        # A channel earns weight by standing its leader clear of its own spread.
        conf: dict[str, float] = {}
        for name in chan:
            nonzero = [f for f in pool if file_scores[f][name] > 0]
            conf[name] = max(z[name].values()) if len(nonzero) >= 2 else 0.0
        top_conf = max(conf.values()) or 1.0
        w = {name: floor + (1.0 - floor) * (c / top_conf) for name, c in conf.items()}

        p = path_likeness(query)
        w_path = 0.15 + 0.55 * p
        qtoks = _query_key_tokens(query)
        qset = set(tokenize(query))

        scores: dict[str, float] = {}
        for f in pool:
            ftoks = _path_tokens(f)
            overlap = len(qtoks & ftoks) + len(qset & ftoks)
            exact = 2.0 if Path(f).stem.lower() in qtoks else 0.0
            scores[f] = sum(w[n] * z[n][f] for n in chan) + w_path * (
                exact + 0.5 * overlap
            )

        # Chunk choice follows the same weights, so the span shown is the span ranked.
        maxes = {n: (max(float(v) for v in arr) or 1.0) for n, arr in chan.items()}
        best: dict[str, int] = {}
        for f in pool:
            best[f] = max(
                self._file_chunks[f],
                key=lambda i: sum(w[n] * float(chan[n][i]) / maxes[n] for n in chan),
            )

        tag = "+".join(n[0] for n in sorted(w, key=lambda n: -w[n]))
        out: list[Hit] = []
        for f in sorted(pool, key=lambda f: -scores[f])[:top_k]:
            i = best[f]
            out.append(
                Hit(
                    chunk_id=i,
                    score=float(scores[f]),
                    file=f,
                    source=f"V3_evidence:{tag}",
                    graph=float(g_aff[i]),
                    bm25=float(b_all[i]),
                    dense=float(d_all[i]),
                )
            )
        return out

    def retrieve_D_channel_best(
        self,
        query: str,
        query_vec: np.ndarray,
        top_k: int = 10,
        *,
        per_channel: int = 4,
    ) -> list[Hit]:
        """Union channel leaders, then D-score.

        Soft (low path_likeness) queries widen the dense shortlist so gold that
        sits just outside the top-4 is still eligible. Hub stems with no path
        overlap are lightly demoted so graphify/serve.py cannot monopolize NL hits.
        """
        g_aff, b_all, d_all, _, _ = self._channel_maps(query, query_vec)
        plike = path_likeness(query)
        if plike <= 0.35:
            d_n, b_n, g_n = 20, 8, 6
        elif plike <= 0.50:
            d_n, b_n, g_n = 10, 6, 5
        else:
            d_n = b_n = g_n = per_channel

        g_files = self._file_rank_from_scores(g_aff)[:g_n]
        b_files = self._file_rank_from_scores(b_all)[:b_n]
        d_files = self._file_rank_from_scores(d_all)[:d_n]

        channels: dict[str, set[str]] = defaultdict(set)
        for f in g_files:
            channels[f.replace("\\", "/")].add("graph")
        for f in b_files:
            channels[f.replace("\\", "/")].add("bm25")
        for f in d_files:
            channels[f.replace("\\", "/")].add("dense")

        hub_stems = frozenset({"serve", "llm"})
        qtoks = _query_key_tokens(query)

        pool: list[Hit] = []
        for f, chans in channels.items():
            cid = self._best_chunk(f, g_aff, b_all, d_all, query=query)
            if cid < 0:
                continue
            tag = "+".join(sorted(chans))
            pool.append(
                Hit(
                    chunk_id=cid,
                    score=0.0,
                    file=f,
                    source=f"D_channel_best:{tag}",
                    graph=float(g_aff[cid]) if 0 <= cid < len(g_aff) else 0.0,
                    bm25=float(b_all[cid]) if 0 <= cid < len(b_all) else 0.0,
                    dense=float(d_all[cid]) if 0 <= cid < len(d_all) else 0.0,
                )
            )

        strong_idents = {
            t for t in (set(tokenize(query)) | _ident_tokens(query)) if "_" in t and len(t) >= 8
        }
        docs = getattr(self.bm25, "docs", None)

        def _score(h: Hit) -> float:
            # Soft NL queries: raw BM25 magnitudes (often 5–10) with the default
            # 0.15 weight outvote dense leaders (~0.2). Scale lexical channels by
            # path_likeness so paraphrase ranking stays dense-led.
            qtoks_l = qtoks
            ftoks = _path_tokens(h.file)
            path_ov = len(qtoks_l & ftoks)
            bn = Path(h.file).stem.lower()
            exact = 2.0 if bn in qtoks_l else 0.0
            if plike <= 0.35:
                s = exact + 0.35 * path_ov + 10.0 * h.dense + 0.02 * h.bm25 + 0.005 * h.graph
            elif plike <= 0.50:
                s = exact + 0.5 * path_ov + 9.0 * h.dense + 0.06 * h.bm25 + 0.01 * h.graph
            else:
                s = self._d_rerank_score(query, h)
            # Identifier in chunk body (route/fn name) beats path-token coincidence
            # like query "BM25" → bm25_index.py.
            if (
                strong_idents
                and docs is not None
                and 0 <= h.chunk_id < len(docs)
                and any(t in set(docs[h.chunk_id]) for t in strong_idents)
            ):
                s += 8.0
            if bn in hub_stems and bn not in qtoks_l and path_ov == 0:
                s *= 0.4
            return s

        ranked = sorted(pool, key=lambda h: -_score(h))
        out: list[Hit] = []
        for h in ranked[:top_k]:
            out.append(
                Hit(
                    chunk_id=h.chunk_id,
                    score=_score(h),
                    file=h.file,
                    source=h.source,
                    graph=h.graph,
                    bm25=h.bm25,
                    dense=h.dense,
                )
            )
        return out

    def retrieve_D_floor(self, query: str, query_vec: np.ndarray, top_k: int = 10) -> list[Hit]:
        """D_rerank + Graphify top-2 floor (cannot leave final top-5)."""
        base = self.retrieve_D_rerank(query, query_vec, top_k=40)
        return self._graph_floor_merge(query, query_vec, base, top_k, "D_floor")

    def retrieve_D_hippo(self, query: str, query_vec: np.ndarray, top_k: int = 10) -> list[Hit]:
        """HippoRAG-style: hybrid seeds → graph affinity expand → D path rerank."""
        g_aff0, b_all, d_all, hybrid_chunk, _ = self._channel_maps(query, query_vec)
        h_files = self._file_rank_from_scores(hybrid_chunk)[:15]
        # Dual-seed graph walk from hybrid file hits
        extra = [(f, 1.0 / (rank + 1)) for rank, f in enumerate(h_files)]
        g_aff, seed_files, _ = self.graph.affinity_scores(
            query, self._n, extra_seed_files=extra
        )
        g_files = self._file_rank_from_scores(g_aff)
        a_pool = self.retrieve_A_minrank_expand(query, query_vec, top_k=40)
        # Build hit pool: A ∪ dual-seed graph files
        by_file: dict[str, Hit] = {}
        for h in a_pool:
            by_file[h.file.replace("\\", "/")] = h
        for f in g_files[:40]:
            f = f.replace("\\", "/")
            if f in by_file:
                # refresh graph score from dual-seed affinity
                cid = by_file[f].chunk_id
                by_file[f] = Hit(
                    chunk_id=cid,
                    score=by_file[f].score,
                    file=f,
                    source="D_hippo",
                    graph=float(g_aff[cid]) if 0 <= cid < len(g_aff) else by_file[f].graph,
                    bm25=by_file[f].bm25,
                    dense=by_file[f].dense,
                )
                continue
            cid = self._best_chunk(f, g_aff, b_all, d_all, query=query)
            if cid < 0:
                continue
            by_file[f] = Hit(
                chunk_id=cid,
                score=0.0,
                file=f,
                source="D_hippo",
                graph=float(g_aff[cid]),
                bm25=float(b_all[cid]),
                dense=float(d_all[cid]),
            )
        return self._hits_from_pool_d_score(query, list(by_file.values()), top_k, "D_hippo")

    def retrieve_X_soft(self, query: str, query_vec: np.ndarray, top_k: int = 10) -> list[Hit]:
        """State-conditioned: soft → D_hippo+floor; else D_rerank+floor."""
        p = path_likeness(query)
        if p <= 0.35:
            base = self.retrieve_D_hippo(query, query_vec, top_k=40)
            return self._graph_floor_merge(query, query_vec, base, top_k, "X_soft:hippo")
        base = self.retrieve_D_rerank(query, query_vec, top_k=40)
        return self._graph_floor_merge(query, query_vec, base, top_k, "X_soft:D")

    def _unique_file_list(self, hits: list[Hit], cap: int = 10) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for h in hits:
            f = h.file.replace("\\", "/")
            if f not in seen:
                out.append(f)
                seen.add(f)
            if len(out) >= cap:
                break
        return out

    def _should_soft_ensure_floor(self, query: str, g_files: list[str], d_files: list[str], state: str) -> bool:
        """Floor only on SOFT when a lexically grounded Graphify hit is missing from D top-5.

        SYMBOL/BLEND never floor (protects diverse technical paraphrases).
        """
        if state != "SOFT" or not g_files:
            return False
        d_top5 = set(d_files[:5])
        missing = [f for f in g_files[:5] if f not in d_top5]
        if not missing:
            return False
        return any(lexical_graph_confidence(query, f) >= 1.0 for f in missing)

    def _grounded_floor_files(self, query: str, g_files: list[str], d_files: list[str]) -> list[str]:
        """G candidates to ensure: missing from D top-5 and lexically grounded."""
        d_top5 = set(d_files[:5])
        out: list[str] = []
        for f in g_files:
            if f in d_top5:
                continue
            if lexical_graph_confidence(query, f) >= 1.0:
                out.append(f)
        return out


    def retrieve_R_gated_floor(self, query: str, query_vec: np.ndarray, top_k: int = 10) -> list[Hit]:
        """D_rerank + state-gated Graphify top-2 ensure-into-top5 (no prepend).

        SYMBOL → pure D (protects diverse/symbol suites).
        SOFT → ensure G top-2 into top-5 tail if D dropped them.
        BLEND → same but only when missing G hits are lexically grounded.
        """
        state = query_state(query)
        base = self.retrieve_D_rerank(query, query_vec, top_k=40)
        g_hits = self.retrieve_graphify(query, top_k=8)
        g_files = self._unique_file_list(g_hits, 5)
        d_files = self._unique_file_list(base, 10)
        if self._should_soft_ensure_floor(query, g_files, d_files, state):
            grounded = self._grounded_floor_files(query, g_files[:5], d_files)
            if not grounded:
                pass
            else:
                return self._graph_floor_merge(
                    query,
                    query_vec,
                    base,
                    top_k,
                    f"R_gated_floor:{state}",
                    floor_n=len(grounded),
                    insert="ensure",
                    floor_files=grounded,
                )
        return [
            Hit(
                chunk_id=h.chunk_id,
                score=h.score,
                file=h.file,
                source=f"R_gated_floor:{state}",
                graph=h.graph,
                bm25=h.bm25,
                dense=h.dense,
            )
            for h in base[:top_k]
        ]

    def retrieve_R_complex(self, query: str, query_vec: np.ndarray, top_k: int = 10) -> list[Hit]:
        """Full router: SYMBOL→D; SOFT→HippoRAG dual-seed; gated ensure-floor.

        Stages (Cormack / HippoRAG / GEAR):
          0. query_state(path_likeness)
          1. SOFT uses hybrid→graph dual-seed (D_hippo); else D
          2. gated ensure-floor (lexically grounded G hits into top-5 without clobbering D top-3)
        """
        state = query_state(query)
        if state == "SOFT":
            base = self.retrieve_D_hippo(query, query_vec, top_k=40)
            tag = "R_complex:SOFT+hippo"
        else:
            base = self.retrieve_D_rerank(query, query_vec, top_k=40)
            tag = f"R_complex:{state}"

        g_hits = self.retrieve_graphify(query, top_k=8)
        g_files = self._unique_file_list(g_hits, 5)
        d_files = self._unique_file_list(base, 10)
        if self._should_soft_ensure_floor(query, g_files, d_files, state):
            grounded = self._grounded_floor_files(query, g_files[:5], d_files)
            if grounded:
                return self._graph_floor_merge(
                    query,
                    query_vec,
                    base,
                    top_k,
                    tag + "+floor",
                    floor_n=len(grounded),
                    insert="ensure",
                    floor_files=grounded,
                )
        return [
            Hit(
                chunk_id=h.chunk_id,
                score=h.score,
                file=h.file,
                source=tag,
                graph=h.graph,
                bm25=h.bm25,
                dense=h.dense,
            )
            for h in base[:top_k]
        ]

    # ----- R_plan: GRASP-lite + BM25-lead + soft flat second-pass -----
    def _score_margin_flat(self, hits: list[Hit], *, ratio: float = 1.22) -> bool:
        """True when top-1 is not clearly ahead of top-2 (low confidence)."""
        if not hits:
            return True
        if len(hits) < 2:
            return False
        s0 = float(hits[0].score)
        s1 = float(hits[1].score)
        if s0 <= 1e-9:
            return True
        return (s0 / (abs(s1) + 1e-9)) < ratio

    def _keyword_probe_queries(self, query: str) -> list[str]:
        """Surface probes from the query only — no repo-specific vocabulary."""
        from conductor.query_router import _FUNC

        keys = [t for t in _query_key_tokens(query) if len(t) >= 4]
        words = [t for t in tokenize(query) if t not in _FUNC and len(t) >= 4]
        probes: list[str] = []
        if keys:
            probes.append(" ".join(keys[:8]))
        for w in words[:8]:
            if w not in probes:
                probes.append(w)
        for i in range(min(len(words) - 1, 6)):
            bigram = f"{words[i]} {words[i + 1]}"
            if bigram not in probes:
                probes.append(bigram)
        return probes[:12]

    def _bm25_probe_hits(
        self, query: str, query_vec: np.ndarray, *, pool_cap: int = 30
    ) -> list[Hit]:
        """BM25-led candidate files from keyword/bigram probes → Hit pool."""
        g_aff, b_all, d_all, _, _ = self._channel_maps(query, query_vec)
        file_best: dict[str, float] = {}
        for probe in self._keyword_probe_queries(query):
            for cid, sc in self.bm25.search(probe, top_k=24):
                f = self._file_of(int(cid)).replace("\\", "/")
                file_best[f] = max(file_best.get(f, -1.0), float(sc))
        # Also plain BM25 on full query
        for cid, sc in self.bm25.search(query, top_k=40):
            f = self._file_of(int(cid)).replace("\\", "/")
            file_best[f] = max(file_best.get(f, -1.0), float(sc))
        ordered = sorted(file_best.keys(), key=lambda f: (-file_best[f], f))[:pool_cap]
        out: list[Hit] = []
        for f in ordered:
            cid = self._best_chunk(f, g_aff, b_all, d_all, query=query)
            if cid < 0:
                continue
            out.append(
                Hit(
                    chunk_id=cid,
                    score=0.0,
                    file=f,
                    source="bm25_probe",
                    graph=float(g_aff[cid]),
                    bm25=float(b_all[cid]),
                    dense=float(d_all[cid]),
                )
            )
        return out

    def retrieve_D_bm25_lead(self, query: str, query_vec: np.ndarray, top_k: int = 10) -> list[Hit]:
        """SYMBOL/API path: BM25-weighted hybrid + light graph, then D rerank."""
        cfg = self.config
        g_aff, b_all, d_all, _, seed_files = self._channel_maps(query, query_vec)
        hybrid = np.zeros(self._n, dtype=np.float64)
        rb = {
            int(i): r
            for r, (i, _) in enumerate(self.bm25.search(query, top_k=cfg.candidate_pool), 1)
        }
        rd = {
            int(i): r
            for r, (i, _) in enumerate(self.dense.search(query_vec, top_k=cfg.candidate_pool), 1)
        }
        # BM25-led RRF (exact/API queries)
        for cid in set(rb) | set(rd):
            hybrid[cid] = (2.0 / (cfg.rrf_k + rb.get(cid, 10_000))) + (
                0.35 / (cfg.rrf_k + rd.get(cid, 10_000))
            )
        g_files = self._file_rank_from_scores(g_aff)
        h_files = self._file_rank_from_scores(hybrid)
        ordered = self._minrank_files(g_files, h_files, seed_files)
        pool = self._hits_from_files(ordered, g_aff, b_all, d_all, 40, "D_bm25_lead")
        return self._hits_from_pool_d_score(query, pool, top_k, "D_bm25_lead")

    def retrieve_R_plan(self, query: str, query_vec: np.ndarray, top_k: int = 10) -> list[Hit]:
        """Production planner: BM25-lead for SYMBOL; SOFT Hippo + flat second-pass.

        1. SYMBOL + high path_likeness → BM25-lead D (skip heavy dual-seed)
        2. Else R_complex (SOFT→Hippo, else D)
        3. If SOFT and top margin flat → keyword/bigram BM25 probe → merge → D rerank
        """
        state = query_state(query)
        plike = path_likeness(query)

        if state == "SYMBOL" and plike >= 0.55:
            return self.retrieve_D_bm25_lead(query, query_vec, top_k=top_k)

        base = self.retrieve_R_complex(query, query_vec, top_k=max(top_k, 8))
        tag = (base[0].source if base else "R_plan") + "+plan"

        if state != "SOFT" or not self._score_margin_flat(base):
            return [
                Hit(
                    chunk_id=h.chunk_id,
                    score=h.score,
                    file=h.file,
                    source=tag if state != "SOFT" else h.source,
                    graph=h.graph,
                    bm25=h.bm25,
                    dense=h.dense,
                )
                for h in base[:top_k]
            ]

        # Second pass: surface keyword probes (no repo lexicon)
        probe_hits = self._bm25_probe_hits(query, query_vec, pool_cap=35)
        by_file: dict[str, Hit] = {}
        for h in base:
            by_file[h.file.replace("\\", "/")] = h
        for h in probe_hits:
            f = h.file.replace("\\", "/")
            if f not in by_file:
                by_file[f] = h
        merged = self._hits_from_pool_d_score(
            query, list(by_file.values()), top_k, "R_plan:SOFT+probe"
        )
        return merged

    # ----- D2: R&D — union C expand pool + A pool, then D-style rerank -----
    def retrieve_D2_pool_from_c(self, query: str, query_vec: np.ndarray, top_k: int = 10) -> list[Hit]:
        """Candidate recall from C_gear + A, precision from D lexical rerank."""
        a_pool = self.retrieve_A_minrank_expand(query, query_vec, top_k=40)
        c_pool = self.retrieve_C_gear(query, query_vec, top_k=40)
        by_file: dict[str, Hit] = {}
        for h in a_pool + c_pool:
            prev = by_file.get(h.file)
            if prev is None or (h.bm25 + 40 * h.dense + h.graph) > (prev.bm25 + 40 * prev.dense + prev.graph):
                by_file[h.file] = h
        pool = list(by_file.values())
        qtoks = _query_key_tokens(query)
        qset = set(tokenize(query))

        def rerank_score(h: Hit) -> float:
            ftoks = _path_tokens(h.file)
            path_ov = len(qtoks & ftoks) + len(qset & ftoks)
            bn = Path(h.file).stem.lower()
            exact = 2.0 if bn in qtoks else 0.0
            return exact + 0.8 * path_ov + 0.15 * h.bm25 + 8.0 * h.dense + 0.02 * h.graph

        ranked = sorted(pool, key=lambda h: -rerank_score(h))
        return [
            Hit(
                chunk_id=h.chunk_id,
                score=rerank_score(h),
                file=h.file,
                source="D2_pool_from_c",
                graph=h.graph,
                bm25=h.bm25,
                dense=h.dense,
            )
            for h in ranked[:top_k]
        ]

    # ----- M2: CombMNZ recall ∪ A pool, pure D path score (no MNZ in final score) -----
    def retrieve_M2_mnz_dpath(self, query: str, query_vec: np.ndarray, top_k: int = 10) -> list[Hit]:
        """Borrow CombMNZ only for candidate recall; precision = identical D path score.

        Pool = A_minrank_expand ∪ CombMNZ. Final order = pure D lexical/path formula
        (no CombMNZ mass, no MNZ-order RRF — those hurt diverse-domain precision).
        """
        a_pool = self.retrieve_A_minrank_expand(query, query_vec, top_k=40)
        mnz_pool = self.retrieve_M_combmnz(query, query_vec, top_k=40)

        by_file: dict[str, Hit] = {}
        for h in a_pool + mnz_pool:
            prev = by_file.get(h.file)
            if prev is None or (h.bm25 + 40.0 * h.dense + h.graph) > (
                prev.bm25 + 40.0 * prev.dense + prev.graph
            ):
                by_file[h.file] = h
        pool = list(by_file.values())

        qtoks = _query_key_tokens(query)
        qset = set(tokenize(query))

        def d_path_score(h: Hit) -> float:
            ftoks = _path_tokens(h.file)
            path_ov = len(qtoks & ftoks) + len(qset & ftoks)
            bn = Path(h.file).stem.lower()
            exact = 2.0 if bn in qtoks else 0.0
            return exact + 0.8 * path_ov + 0.15 * h.bm25 + 8.0 * h.dense + 0.02 * h.graph

        ranked = sorted(pool, key=lambda h: -d_path_score(h))
        return [
            Hit(
                chunk_id=h.chunk_id,
                score=d_path_score(h),
                file=h.file,
                source="M2_mnz_dpath",
                graph=h.graph,
                bm25=h.bm25,
                dense=h.dense,
            )
            for h in ranked[:top_k]
        ]

    # ----- R: query-conditioned D↔C router -----
    def retrieve_R_route_dc(self, query: str, query_vec: np.ndarray, top_k: int = 10) -> list[Hit]:
        """Route path/identifier queries to D, NL/paraphrase to C; soft-blend the middle.

        Evidence: suite winners split — D/A on symbol+terse, C on paraphrase/confusable/multihop.
        """
        mode = route_mode(query)
        if mode == "D":
            hits = self.retrieve_D_rerank(query, query_vec, top_k=top_k)
            return [
                Hit(h.chunk_id, h.score, h.file, "R_route_dc:D", h.graph, h.bm25, h.dense) for h in hits
            ]
        if mode == "C":
            hits = self.retrieve_C_gear(query, query_vec, top_k=top_k)
            return [
                Hit(h.chunk_id, h.score, h.file, "R_route_dc:C", h.graph, h.bm25, h.dense) for h in hits
            ]

        # Soft middle: RRF blend — D keeps a floor weight so diverse domains don't collapse to C
        p = path_likeness(query)
        w_d = 0.55 + 0.45 * p  # ∈ [0.55, 1.0]
        w_c = 1.0 - w_d
        d_hits = self.retrieve_D_rerank(query, query_vec, top_k=40)
        c_hits = self.retrieve_C_gear(query, query_vec, top_k=40)
        file_rrf: dict[str, float] = defaultdict(float)
        by_file: dict[str, Hit] = {}
        cfg = self.config
        for r, h in enumerate(d_hits, 1):
            file_rrf[h.file] += w_d / (cfg.rrf_k + r)
            by_file[h.file] = h
        for r, h in enumerate(c_hits, 1):
            file_rrf[h.file] += w_c / (cfg.rrf_k + r)
            prev = by_file.get(h.file)
            if prev is None or (h.bm25 + 40 * h.dense + h.graph) > (
                prev.bm25 + 40 * prev.dense + prev.graph
            ):
                by_file[h.file] = h
        ordered = sorted(file_rrf.keys(), key=lambda f: (-file_rrf[f], f))
        out: list[Hit] = []
        for f in ordered:
            h = by_file[f]
            out.append(
                Hit(
                    chunk_id=h.chunk_id,
                    score=float(file_rrf[f]),
                    file=h.file,
                    source=f"R_route_dc:blend(d={w_d:.2f})",
                    graph=h.graph,
                    bm25=h.bm25,
                    dense=h.dense,
                )
            )
            if len(out) >= top_k:
                break
        return out

    # ----- E: multiprobe -----
    def retrieve_E_multiprobe(self, query: str, query_vec: np.ndarray, top_k: int = 10) -> list[Hit]:
        cfg = self.config
        probes = [query]
        # lexical probe: identifiers and .py fragments only
        keys = sorted(_query_key_tokens(query), key=len, reverse=True)[:8]
        if keys:
            probes.append(" ".join(keys))
        # path-ish probe
        py = re.findall(r"[A-Za-z0-9_./\-]+\.py", query)
        if py:
            probes.append(" ".join(py))
        # basename stems
        stems = [Path(p).stem for p in py] + [k for k in keys if "_" in k or k.endswith("py")]
        if stems:
            probes.append(" ".join(dict.fromkeys(stems)))

        # unique probes
        seen_p: set[str] = set()
        uniq = []
        for p in probes:
            p = p.strip()
            if p and p not in seen_p:
                uniq.append(p)
                seen_p.add(p)

        file_rrf: dict[str, float] = defaultdict(float)
        # Need embeddings per probe — reuse main vec for full query; for lexical probes use BM25+graph only
        g0, b0, d0, h0, seeds0 = self._channel_maps(query, query_vec)
        for pi, probe in enumerate(uniq):
            if pi == 0:
                g_aff, b_all, d_all, hybrid_chunk, seed_files = g0, b0, d0, h0, seeds0
            else:
                g_aff, seed_files, _ = self.graph.affinity_scores(probe, self._n)
                b_all = self.bm25.score_all(probe)
                # no dense for lexical-only probes (or use same vec lightly)
                hybrid_chunk = b_all.copy()
            g_files = self._file_rank_from_scores(g_aff)[:30]
            h_files = self._file_rank_from_scores(hybrid_chunk)[:30]
            w = 1.0 if pi == 0 else 0.75
            for r, f in enumerate(g_files, 1):
                file_rrf[f] += w / (cfg.rrf_k + r)
            for r, f in enumerate(h_files, 1):
                file_rrf[f] += w / (cfg.rrf_k + r)

        ordered = sorted(file_rrf.keys(), key=lambda f: (-file_rrf[f], f))
        return self._hits_from_files(ordered, g0, b0, d0, top_k, "E_multiprobe", file_rrf)

    # ----- F: F95 vocabulary bridges on top of A -----
    def retrieve_F_f95(self, query: str, query_vec: np.ndarray, top_k: int = 10) -> list[Hit]:
        g_aff, b_all, d_all, hybrid_chunk, seed_files = self._channel_maps(query, query_vec)
        g_files = self._file_rank_from_scores(g_aff)
        h_files = self._file_rank_from_scores(hybrid_chunk)
        ordered = self._minrank_files(g_files, h_files, seed_files)

        # Package-sibling inject: any seed/top hit pulls in same-dir files (recorder next to harness)
        seed_for_sib = list(
            dict.fromkeys(
                [f.replace("\\", "/") for f in seed_files[:8]]
                + g_files[:8]
                + h_files[:8]
                + ordered[:12]
            )
        )
        all_files = list(self._file_chunks.keys())
        siblings = f95mod.sibling_files(seed_for_sib, all_files)
        seen = set(ordered)
        for f in siblings:
            if f not in seen:
                ordered.append(f)
                seen.add(f)

        qtoks = f95mod.expand_stems(f95mod.query_key_tokens(query))
        # Path-hint inject: distilled→distillation must pull build.py into the pool
        for f in f95mod.path_hint_files(qtoks, all_files):
            if f not in seen:
                ordered.append(f)
                seen.add(f)

        phrases = f95mod.negated_phrases(query)

        scored: list[tuple[float, str]] = []
        for rank, f in enumerate(ordered):
            base = 1.0 / (60 + rank + 1)
            pt = f95mod.path_tokens(f)
            overlap = len(qtoks & pt)
            bn = Path(f).stem.lower()
            if bn in qtoks or any(bn.startswith(t) or t in bn for t in qtoks if len(t) >= 4):
                overlap += 3
            # Extra weight for rare path hints (distillation)
            rare = qtoks & f95mod._PATH_INJECT_HINTS & pt
            if rare:
                overlap += 4 * len(rare)
            score = base * (1.0 + 0.35 * overlap)
            rb = f95mod.role_boost(qtoks, f)
            if rb:
                score *= 1.0 + rb
            score *= f95mod.negation_multiplier(f, phrases)
            score *= f95mod.hub_multiplier(f, qtoks, phrases)
            scored.append((-score, f))
        scored.sort()
        ordered2 = [f for _, f in scored]
        return self._hits_from_files(ordered2, g_aff, b_all, d_all, top_k, "F_f95")

    def _file_channel_rankings(self, query: str, query_vec: np.ndarray):
        """Graph / BM25 / dense / hybrid file rankings + raw channel scores for peakiness."""
        g_aff, b_all, d_all, hybrid_chunk, seed_files = self._channel_maps(query, query_vec)
        rankings = {
            "graph": self._file_rank_from_scores(g_aff),
            "bm25": self._file_rank_from_scores(b_all),
            "dense": self._file_rank_from_scores(d_all),
            "hybrid": self._file_rank_from_scores(hybrid_chunk),
        }
        return g_aff, b_all, d_all, hybrid_chunk, seed_files, rankings

    # ----- M_combmnz: Fox & Shaw CombMNZ on RRF-mapped ranks -----
    def retrieve_M_combmnz(self, query: str, query_vec: np.ndarray, top_k: int = 10) -> list[Hit]:
        g_aff, b_all, d_all, _, _, rankings = self._file_channel_rankings(query, query_vec)
        # Use graph + bm25 + dense (3 independent channels); hybrid is derived
        ch = {"graph": rankings["graph"], "bm25": rankings["bm25"], "dense": rankings["dense"]}
        fused = fuse_combmnz(ch, score_fn=rrf_score, hit_depth=30, pool_cap=80)
        scores = {f: s for f, s in fused}
        ordered = [f for f, _ in fused]
        return self._hits_from_files(ordered, g_aff, b_all, d_all, top_k, "M_combmnz", scores)

    # ----- M_logisr: CombSUM with log-ISR rank map -----
    def retrieve_M_logisr(self, query: str, query_vec: np.ndarray, top_k: int = 10) -> list[Hit]:
        g_aff, b_all, d_all, _, _, rankings = self._file_channel_rankings(query, query_vec)
        ch = {"graph": rankings["graph"], "bm25": rankings["bm25"], "dense": rankings["dense"]}
        fused = fuse_combsum(ch, score_fn=logisr_score, pool_cap=80)
        scores = {f: s for f, s in fused}
        ordered = [f for f, _ in fused]
        return self._hits_from_files(ordered, g_aff, b_all, d_all, top_k, "M_logisr", scores)

    # ----- M_condorcet: pairwise majority over channel rankings -----
    def retrieve_M_condorcet(self, query: str, query_vec: np.ndarray, top_k: int = 10) -> list[Hit]:
        g_aff, b_all, d_all, _, _, rankings = self._file_channel_rankings(query, query_vec)
        ch = {"graph": rankings["graph"], "bm25": rankings["bm25"], "dense": rankings["dense"]}
        fused = fuse_condorcet(ch, pool_cap=40)
        scores = {f: s for f, s in fused}
        ordered = [f for f, _ in fused]
        return self._hits_from_files(ordered, g_aff, b_all, d_all, top_k, "M_condorcet", scores)

    # ----- M_adapt_rrf: RRF weights from per-query channel peakiness -----
    def retrieve_M_adapt_rrf(self, query: str, query_vec: np.ndarray, top_k: int = 10) -> list[Hit]:
        g_aff, b_all, d_all, hybrid_chunk, _, rankings = self._file_channel_rankings(query, query_vec)
        # Peakiness from positive score mass of each channel
        peak = {
            "graph": channel_peakiness(
                sorted((float(x) for x in g_aff if float(x) > 0), reverse=True)[:200] or [0.0]
            ),
            "bm25": channel_peakiness(
                sorted((float(x) for x in b_all if float(x) > 0), reverse=True)[:200] or [0.0]
            ),
            "dense": channel_peakiness(sorted((float(x) for x in d_all), reverse=True)[:200]),
        }
        # Also boost graph when query looks identifier-heavy
        qtoks = _query_key_tokens(query)
        id_like = sum(1 for t in qtoks if "_" in t or t.endswith("py"))
        if id_like >= 2:
            peak["graph"] = min(1.0, peak["graph"] + 0.25)
        weights = adaptive_weights_from_peakiness(peak)
        ch = {"graph": rankings["graph"], "bm25": rankings["bm25"], "dense": rankings["dense"]}
        fused = fuse_combsum(ch, score_fn=rrf_score, weights=weights, pool_cap=80)
        scores = {f: s for f, s in fused}
        ordered = [f for f, _ in fused]
        return self._hits_from_files(ordered, g_aff, b_all, d_all, top_k, "M_adapt_rrf", scores)

    # ----- M_mnz_rerank: CombMNZ pool → D-style lexical rerank -----
    def retrieve_M_mnz_rerank(self, query: str, query_vec: np.ndarray, top_k: int = 10) -> list[Hit]:
        pool = self.retrieve_M_combmnz(query, query_vec, top_k=40)
        qtoks = _query_key_tokens(query)
        qset = set(tokenize(query))

        def rerank_score(h: Hit) -> float:
            ftoks = _path_tokens(h.file)
            path_ov = len(qtoks & ftoks) + len(qset & ftoks)
            bn = Path(h.file).stem.lower()
            exact = 2.0 if bn in qtoks else 0.0
            # agreement bonus already in CombMNZ score (h.score)
            return exact + 0.8 * path_ov + 0.15 * h.bm25 + 8.0 * h.dense + 0.5 * h.score

        ranked = sorted(pool, key=lambda h: -rerank_score(h))
        return [
            Hit(
                chunk_id=h.chunk_id,
                score=rerank_score(h),
                file=h.file,
                source="M_mnz_rerank",
                graph=h.graph,
                bm25=h.bm25,
                dense=h.dense,
            )
            for h in ranked[:top_k]
        ]

    ARCHITECTURES = {
        "A_minrank_expand": "retrieve_A_minrank_expand",
        "B_ppr": "retrieve_B_ppr",
        "C_gear": "retrieve_C_gear",
        "D_rerank": "retrieve_D_rerank",
        "V2_adaptive": "retrieve_V2_adaptive",
        "V3_evidence": "retrieve_V3_evidence",
        "D_channel_best": "retrieve_D_channel_best",
        "D_floor": "retrieve_D_floor",
        "D_hippo": "retrieve_D_hippo",
        "X_soft": "retrieve_X_soft",
        "R_gated_floor": "retrieve_R_gated_floor",
        "R_complex": "retrieve_R_complex",
        "R_plan": "retrieve_R_plan",
        "D_bm25_lead": "retrieve_D_bm25_lead",
        "D2_pool_from_c": "retrieve_D2_pool_from_c",
        "E_multiprobe": "retrieve_E_multiprobe",
        "F_f95": "retrieve_F_f95",
        "M_combmnz": "retrieve_M_combmnz",
        "M_logisr": "retrieve_M_logisr",
        "M_condorcet": "retrieve_M_condorcet",
        "M_adapt_rrf": "retrieve_M_adapt_rrf",
        "M_mnz_rerank": "retrieve_M_mnz_rerank",
        "M2_mnz_dpath": "retrieve_M2_mnz_dpath",
        "R_route_dc": "retrieve_R_route_dc",
        "baseline_graphify": "retrieve_graphify",
        "baseline_hybrid": "retrieve_hybrid",
        "baseline_minrank": "retrieve_conductor",
    }

    def retrieve_arch(self, name: str, query: str, query_vec: np.ndarray, top_k: int = 10) -> list[Hit]:
        method = getattr(self, self.ARCHITECTURES[name])
        # baseline_graphify is (query, top_k) only — no dense vec
        if name == "baseline_graphify":
            return method(query, top_k=top_k)
        return method(query, query_vec, top_k=top_k)
