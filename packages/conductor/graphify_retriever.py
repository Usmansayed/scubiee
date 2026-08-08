"""Graphify lexical-graph retrieval mapped onto chunk IDs."""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import networkx as nx
import numpy as np

from graphify.build import build as graphify_build
from graphify.export import to_json as graphify_to_json
from graphify.serve import (
    _load_graph,
    _pick_seeds,
    _query_terms,
    _score_query,
)

_LOC = re.compile(r"L(\d+)")


@dataclass(frozen=True)
class ChunkSpan:
    index: int
    file: str
    start_line: int
    end_line: int


def normalize_file(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def parse_line(loc: str | None) -> int | None:
    if not loc:
        return None
    m = _LOC.search(str(loc))
    return int(m.group(1)) if m else None


def build_and_save_graph(extraction: dict, root: Path, out_json: Path) -> nx.Graph:
    """Build undirected Graphify graph (query-friendly) and write graph.json."""
    G = graphify_build([extraction], directed=False, dedup=True, root=root)
    # community ids optional for query scoring
    communities: dict[int, list[str]] = {}
    out_json.parent.mkdir(parents=True, exist_ok=True)
    graphify_to_json(G, communities, str(out_json), force=True)
    return _load_graph(str(out_json))


def patch_and_save_graph(
    extraction: dict,
    root: Path,
    out_json: Path,
    *,
    prune_sources: list[str] | None = None,
) -> nx.Graph:
    """Incremental graph update: merge extraction into existing graph.json.

    Re-extracted sources replace prior nodes; prune_sources drops deleted files.
    Caller must pass extraction for *changed* files only (not full corpus).
    """
    from graphify.build import build_merge

    out_json = Path(out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    chunks = [extraction] if extraction else [{}]
    G = build_merge(
        chunks,
        graph_path=out_json,
        prune_sources=prune_sources or None,
        directed=False,
        dedup=True,
        root=root,
    )
    graphify_to_json(G, {}, str(out_json), force=True)
    return _load_graph(str(out_json))


def load_or_build_graph(extraction: dict, root: Path, out_json: Path) -> nx.Graph:
    if out_json.exists():
        return _load_graph(str(out_json))
    return build_and_save_graph(extraction, root, out_json)


class GraphifyChunkRetriever:
    def __init__(self, G: nx.Graph, spans: list[ChunkSpan], *, depth: int = 2):
        self.G = G
        self.spans = spans
        self.depth = depth
        self._by_file: dict[str, list[ChunkSpan]] = {}
        for s in spans:
            self._by_file.setdefault(normalize_file(s.file), []).append(s)

    def _chunks_for_node(self, nid: str) -> list[int]:
        d = self.G.nodes[nid]
        src = normalize_file(str(d.get("source_file") or ""))
        if not src:
            return []
        line = parse_line(d.get("source_location"))
        candidates = self._by_file.get(src, [])
        if not candidates:
            # basename fallback
            base = Path(src).name
            candidates = [
                s for s in self.spans if Path(normalize_file(s.file)).name == base
            ]
        if not candidates:
            return []
        if line is None:
            return [c.index for c in candidates]
        hits = [c.index for c in candidates if c.start_line <= line <= c.end_line]
        return hits if hits else [c.index for c in candidates]

    def affinity_scores(
        self,
        question: str,
        n_chunks: int,
        *,
        extra_seed_files: list[tuple[str, float]] | None = None,
    ) -> tuple[np.ndarray, list[str], float]:
        """Map Graphify scores + dual-seed BFS onto chunks.

        ``extra_seed_files`` lets BM25/dense hits steer the same graph walk
        (HippoRAG-style dual seeding) — one structure, three inputs.
        """
        aff = np.zeros(n_chunks, dtype=np.float64)
        terms = _query_terms(question)
        qs = _score_query(self.G, terms, collect_per_term_seeds=True)
        seeds = _pick_seeds(qs.ranked, G=self.G, best_seed_by_term=qs.best_seed_by_term)
        top_seed = float(qs.ranked[0][0]) if qs.ranked else 0.0
        score_map = {nid: float(sc) for sc, nid in qs.ranked}
        seed_files: list[str] = []
        seen_f: set[str] = set()
        for nid in seeds:
            src = normalize_file(str(self.G.nodes[nid].get("source_file") or ""))
            if src and src not in seen_f:
                seed_files.append(src)
                seen_f.add(src)

        soft_weight: dict[str, float] = {}
        soft_seeds: list[str] = []
        if extra_seed_files:
            by_file: dict[str, list[str]] = {}
            for nid, d in self.G.nodes(data=True):
                src = normalize_file(str(d.get("source_file") or ""))
                if src:
                    by_file.setdefault(src, []).append(nid)
            for fpath, w in extra_seed_files:
                fpath = normalize_file(fpath)
                nodes = by_file.get(fpath, [])
                if not nodes:
                    continue
                if fpath not in seen_f:
                    seed_files.append(fpath)
                    seen_f.add(fpath)
                for nid in nodes[:8]:
                    soft_seeds.append(nid)
                    soft_weight[nid] = max(soft_weight.get(nid, 0.0), float(w))

        if not seeds and not soft_seeds:
            return aff, seed_files, top_seed

        hop: dict[str, int] = {}
        q: deque[str] = deque()
        for s in seeds:
            hop[s] = 0
            q.append(s)
        for s in soft_seeds:
            if s not in hop:
                hop[s] = 0
                q.append(s)

        while q:
            cur = q.popleft()
            depth = hop[cur]
            if depth >= self.depth:
                continue
            for nb in self.G.neighbors(cur):
                if nb not in hop:
                    hop[nb] = depth + 1
                    q.append(nb)

        max_seed = max((score_map.get(s, 0.0) for s in seeds), default=0.0)
        max_soft = max(soft_weight.values(), default=0.0)
        soft_scale = (
            (max_seed * 0.5 / max_soft)
            if max_soft > 0 and max_seed > 0
            else (80.0 / max_soft if max_soft > 0 else 1.0)
        )

        for nid, h in hop.items():
            base = score_map.get(nid, 0.0)
            if nid in soft_weight:
                base = max(base, soft_weight[nid] * soft_scale)
            if base <= 0 and max_seed > 0:
                base = max_seed * (0.35 ** h) if h > 0 else 0.0
            node_aff = base / (1.0 + h)
            if node_aff <= 0:
                continue
            for cid in self._chunks_for_node(nid):
                if 0 <= cid < n_chunks and node_aff > aff[cid]:
                    aff[cid] = node_aff
        return aff, seed_files, top_seed

    def query_ranked_chunks(self, question: str, top_k: int = 50) -> list[int]:
        n = max((s.index for s in self.spans), default=-1) + 1
        aff, _, _ = self.affinity_scores(question, n)
        if aff.sum() <= 0:
            return []
        order = np.argsort(-aff)
        out: list[int] = []
        for i in order:
            if aff[i] <= 0:
                break
            out.append(int(i))
            if len(out) >= top_k:
                break
        return out

    def seed_files(self, question: str, max_seeds: int = 12) -> list[str]:
        terms = _query_terms(question)
        qs = _score_query(self.G, terms, collect_per_term_seeds=True)
        seeds = _pick_seeds(qs.ranked, G=self.G, best_seed_by_term=qs.best_seed_by_term)
        files: list[str] = []
        seen: set[str] = set()
        for nid in seeds[:max_seeds]:
            src = normalize_file(str(self.G.nodes[nid].get("source_file") or ""))
            if src and src not in seen:
                files.append(src)
                seen.add(src)
        return files

    def neighbor_files(self, files: list[str], cap: int = 24) -> list[str]:
        """1-hop neighbors (any edge) whose source_file differs."""
        want = {normalize_file(f) for f in files}
        # Map file -> node ids
        file_nodes: dict[str, list[str]] = {}
        for nid, d in self.G.nodes(data=True):
            src = normalize_file(str(d.get("source_file") or ""))
            if src in want:
                file_nodes.setdefault(src, []).append(nid)

        out: list[str] = []
        seen: set[str] = set(want)
        for src in files:
            for nid in file_nodes.get(normalize_file(src), []):
                for nb in self.G.neighbors(nid):
                    nsrc = normalize_file(str(self.G.nodes[nb].get("source_file") or ""))
                    if nsrc and nsrc not in seen:
                        out.append(nsrc)
                        seen.add(nsrc)
                        if len(out) >= cap:
                            return out
        return out

    def chunks_for_files(self, files: list[str], top_k: int = 50) -> list[int]:
        ranked: list[int] = []
        seen: set[int] = set()
        for f in files:
            for s in self._by_file.get(normalize_file(f), []):
                if s.index not in seen:
                    ranked.append(s.index)
                    seen.add(s.index)
                if len(ranked) >= top_k:
                    return ranked
        return ranked
