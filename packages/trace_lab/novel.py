"""Invented tracing methods — demand-driven, contrastive, intent-sliced, fused.

None of these are a re-skin of ast_propagate. They come from resolver
semantics, contrastive PPR, Weiser-style slices, Steiner/path consensus,
spreading activation, and CombMNZ agreement.
"""

from __future__ import annotations

import heapq
import math
from collections import deque

import numpy as np

from conductor.fusion_math import fuse_combmnz
from trace_lab.ast_graph import AstTraceGraph
from trace_lab.propagate import is_infra
from trace_lab.retrieve import (
    expand_query,
    normalize,
    query_intent,
    query_similarity,
)
from trace_lab.types import GoldCase, HeatCell, Heatmap, TraceNode

FORWARD = frozenset({"calls", "uses", "contains"})
_EFFECT_FLOOR = 0.08

Intent = str  # flow | config | site | entry


def _seed_id(case: GoldCase, nodes: dict[str, TraceNode]) -> str:
    sid = case.seed.id
    if sid not in nodes:
        raise KeyError(f"seed {sid} not in corpus")
    return sid


def _cells(strategy: str, scores: dict[str, float], why: dict[str, str], paths: dict[str, tuple[str, ...]] | None = None) -> Heatmap:
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    cells = [
        HeatCell(
            node_id=nid,
            score=round(sc, 4),
            why=why.get(nid, strategy),
            path=(paths or {}).get(nid, (nid,)),
        )
        for nid, sc in ranked
        if sc > 0
    ]
    return Heatmap(strategy=strategy, cells=cells)


def _allow_edge(
    intent: Intent,
    rel: str,
    src: TraceNode,
    dst: TraceNode,
    query: str,
) -> bool:
    del src
    if rel not in FORWARD:
        return False
    if is_infra(dst, query):
        return False
    if intent in {"flow", "entry"}:
        return True
    if intent == "config":
        if rel == "uses" or dst.kind == "const":
            return True
        return query_similarity(query, dst) > 0
    if intent == "site":
        return query_similarity(query, dst) > 0
    return True


def obligation_trace(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex,
) -> Heatmap:
    """Demand-driven name resolver: seed names are obligations, effects are opt-in."""
    del lex
    seed = _seed_id(case, nodes)
    intent = query_intent(case.query)
    scores = {seed: 1.0}
    why = {seed: f"seed/{intent}"}
    paths: dict[str, tuple[str, ...]] = {seed: (seed,)}
    hops = {seed: 0}
    heap: list[tuple[float, int, str]] = [(-1.0, 0, seed)]
    seen: set[str] = set()
    while heap:
        neg, hop, uid = heapq.heappop(heap)
        if uid in seen:
            continue
        seen.add(uid)
        if hop >= (2 if intent in {"config", "site"} else 5):
            continue
        src = graph.nodes.get(uid)
        if src is None:
            continue
        for vid, rel, weight in graph.neighbors(uid, directed=True):
            dst = graph.nodes.get(vid)
            if dst is None or vid == uid:
                continue
            if not _allow_edge(intent, rel, src, dst, case.query):
                continue
            incoming = scores[uid] * weight * (0.92**hop)
            if incoming < _EFFECT_FLOOR:
                continue
            if incoming <= scores.get(vid, 0.0) + 1e-9:
                continue
            scores[vid] = incoming
            hops[vid] = hop + 1
            why[vid] = f"obligation {rel} {src.symbol}->{dst.symbol}"
            paths[vid] = (paths.get(uid, (uid,)) + (vid,))[-8:]
            heapq.heappush(heap, (-incoming, hop + 1, vid))
    return _cells("obligation", scores, why, paths)


def intent_slice(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex,
) -> Heatmap:
    """Obligation walk plus a single backward hop for callers (flow/entry)."""
    base = obligation_trace(case, nodes, graph, lex)
    scores = {c.node_id: c.score for c in base.cells}
    why = {c.node_id: c.why for c in base.cells}
    paths = {c.node_id: c.path for c in base.cells}
    seed = _seed_id(case, nodes)
    intent = query_intent(case.query)
    if intent in {"flow", "entry"}:
        src = graph.nodes[seed]
        for vid, rel, weight in graph.neighbors(seed, directed=True):
            if rel not in {"called_by", "imported_by"}:
                continue
            dst = graph.nodes.get(vid)
            if dst is None or is_infra(dst, case.query):
                continue
            incoming = 0.55 * weight
            if incoming > scores.get(vid, 0.0):
                scores[vid] = incoming
                why[vid] = f"slice {rel} {src.symbol}"
                paths[vid] = (seed, vid)
    return _cells("intent_slice", scores, why, paths)


def _node_order(graph: AstTraceGraph) -> tuple[list[str], dict[str, int]]:
    ids = list(graph.nodes.keys())
    return ids, {n: i for i, n in enumerate(ids)}


def _row_stochastic(graph: AstTraceGraph, idx: dict[str, int], n: int, *, penalize_hubs: bool) -> np.ndarray:
    w = np.zeros((n, n), dtype=np.float64)
    for src, edges in graph.out.items():
        i = idx.get(src)
        if i is None:
            continue
        for e in edges:
            j = idx.get(e.target)
            if j is None:
                continue
            mass = float(e.weight)
            if penalize_hubs:
                deg = max(graph.degree.get(e.target, 1), 1)
                mass /= 1.0 + math.log1p(deg)
            w[i, j] += mass
    row = w.sum(axis=1, keepdims=True)
    dangling = row[:, 0] <= 0
    row[dangling] = 1.0
    p = w / row
    if dangling.any():
        p[dangling] = 1.0 / n
    return p


def _ppr(
    trans: np.ndarray,
    personalization: np.ndarray,
    *,
    alpha: float = 0.5,
    iters: int = 40,
) -> np.ndarray:
    p = personalization.astype(np.float64)
    s = p.sum()
    if s <= 0:
        p[:] = 1.0 / len(p)
    else:
        p = p / s
    v = p.copy()
    for _ in range(iters):
        v = (1.0 - alpha) * p + alpha * (v @ trans)
    return v


def ppr_idf(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex,
) -> Heatmap:
    """HippoRAG-style PPR: damping 0.5, degree-penalized transitions."""
    del lex
    seed = _seed_id(case, nodes)
    ids, idx = _node_order(graph)
    n = len(ids)
    if n == 0:
        return _cells("ppr_idf", {seed: 1.0}, {seed: "seed"})
    trans = _row_stochastic(graph, idx, n, penalize_hubs=True)
    pers = np.zeros(n, dtype=np.float64)
    pers[idx[seed]] = 1.0
    vec = _ppr(trans, pers, alpha=0.5)
    mx = float(vec.max()) or 1.0
    scores = {ids[i]: float(vec[i] / mx) for i in range(n) if vec[i] > 1e-6}
    scores[seed] = 1.0
    why = {nid: "ppr-idf" for nid in scores}
    why[seed] = "seed"
    return _cells("ppr_idf", scores, why)


def hub_shadow(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex,
) -> Heatmap:
    """Contrastive PPR: seed gravity minus infrastructure gravity."""
    del lex
    seed = _seed_id(case, nodes)
    ids, idx = _node_order(graph)
    n = len(ids)
    trans = _row_stochastic(graph, idx, n, penalize_hubs=True)
    pers_s = np.zeros(n, dtype=np.float64)
    pers_s[idx[seed]] = 1.0
    seed_v = _ppr(trans, pers_s, alpha=0.55)

    pers_h = np.zeros(n, dtype=np.float64)
    for nid, node in graph.nodes.items():
        if nid == seed:
            continue
        if graph.degree.get(nid, 0) < 4:
            continue
        if not is_infra(node, case.query):
            # named logger on a log query is not a shadow attractor
            continue
        pers_h[idx[nid]] = 1.0
    if pers_h.sum() <= 0:
        scores = {ids[i]: float(seed_v[i]) for i in range(n)}
    else:
        hub_v = _ppr(trans, pers_h, alpha=0.55)
        lam = 0.45
        scores = {
            ids[i]: float(max(seed_v[i] - lam * hub_v[i], 0.0))
            for i in range(n)
        }
    mx = max(scores.values()) or 1.0
    scores = {k: v / mx for k, v in scores.items() if v > 1e-5}
    scores[seed] = 1.0
    why = {nid: "hub-shadow" for nid in scores}
    why[seed] = "seed"
    return _cells("hub_shadow", scores, why)


def spread_gate(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex,
) -> Heatmap:
    """Query-gated spreading activation (accumulate, don't take max)."""
    del lex
    seed = _seed_id(case, nodes)
    intent = query_intent(case.query)
    act = {seed: 1.0}
    why = {seed: "seed"}
    paths: dict[str, tuple[str, ...]] = {seed: (seed,)}
    steps = 3 if intent in {"config", "site"} else 4
    struct_bias = 0.75 if intent in {"flow", "entry"} else 0.25
    for step in range(steps):
        snapshot = dict(act)
        decay = 0.72 ** step
        for uid, a in snapshot.items():
            src = graph.nodes.get(uid)
            if src is None:
                continue
            for vid, rel, weight in graph.neighbors(uid, directed=True):
                dst = graph.nodes.get(vid)
                if dst is None or rel not in FORWARD:
                    continue
                if is_infra(dst, case.query):
                    continue
                if intent in {"config", "site"} and not _allow_edge(intent, rel, src, dst, case.query):
                    continue
                gate = struct_bias + (1.0 - struct_bias) * query_similarity(case.query, dst)
                delta = a * weight * decay * max(gate, 0.05)
                nxt = min(1.0, act.get(vid, 0.0) + delta)
                if nxt > act.get(vid, 0.0) + 1e-6:
                    act[vid] = nxt
                    why[vid] = f"spread {rel} from {src.symbol}"
                    paths[vid] = (paths.get(uid, (uid,)) + (vid,))[-8:]
    return _cells("spread_gate", act, why, paths)


def _undirected_bfs(graph: AstTraceGraph, start: str, blocked: set[str]) -> dict[str, str]:
    """parent map; does not expand blocked nodes (they may be reached)."""
    parent = {start: start}
    q = deque([start])
    while q:
        u = q.popleft()
        if u in blocked and u != start:
            continue
        for v, _rel, _w in graph.neighbors(u, directed=False):
            if v in parent:
                continue
            parent[v] = u
            q.append(v)
    return parent


def _directed_path(graph: AstTraceGraph, start: str, goal: str) -> list[str] | None:
    q = deque([start])
    parent = {start: start}
    while q:
        u = q.popleft()
        if u == goal:
            break
        for v, rel, _w in graph.neighbors(u, directed=True):
            if rel not in FORWARD or v in parent:
                continue
            parent[v] = u
            q.append(v)
    if goal not in parent:
        return None
    path = [goal]
    while path[-1] != start:
        path.append(parent[path[-1]])
    path.reverse()
    return path


def bridge_heat(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex,
) -> Heatmap:
    """Heat nodes that lie on seed→lexical-island shortest paths."""
    seed = _seed_id(case, nodes)
    bm = normalize(lex.bm25_scores(expand_query(case.query)))
    blocked = {
        nid
        for nid, n in nodes.items()
        if is_infra(n, case.query)
    }
    parent = _undirected_bfs(graph, seed, blocked)
    islands: list[str] = []
    for nid, sc in sorted(bm.items(), key=lambda kv: -kv[1]):
        if nid == seed or sc < 0.28:
            continue
        if nid in blocked:
            continue
        if nid not in parent:
            continue
        islands.append(nid)
        if len(islands) >= 5:
            break
    heat: dict[str, float] = {seed: 1.0}
    why = {seed: "seed"}
    paths: dict[str, tuple[str, ...]] = {seed: (seed,)}
    if not islands:
        return obligation_trace(case, nodes, graph, lex)
    for island in islands:
        path = _directed_path(graph, seed, island)
        if not path:
            continue
        share = 1.0 / max(len(path) - 1, 1)
        for nid in path:
            heat[nid] = max(heat.get(nid, 0.0), min(1.0, 0.55 + share))
            why.setdefault(nid, f"bridge toward {nodes[island].symbol}")
            paths[nid] = tuple(path[: path.index(nid) + 1])
        heat[island] = max(heat.get(island, 0.0), 0.7)
        why[island] = "lexical island"
    heat[seed] = 1.0
    why[seed] = "seed"
    return _cells("bridge_heat", heat, why, paths)


def agree_fuse(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex,
) -> Heatmap:
    """CombMNZ of obligation + PPR-IDF + intent slice (agreement prior)."""
    arms = [
        obligation_trace(case, nodes, graph, lex),
        ppr_idf(case, nodes, graph, lex),
        spread_gate(case, nodes, graph, lex),
    ]
    rankings = {hm.strategy: hm.ranked_ids() for hm in arms}
    fused = fuse_combmnz(rankings, hit_depth=12, pool_cap=20)
    if not fused:
        seed = _seed_id(case, nodes)
        return _cells("agree_fuse", {seed: 1.0}, {seed: "seed"})
    mx = fused[0][1] or 1.0
    scores = {nid: sc / mx for nid, sc in fused}
    seed = _seed_id(case, nodes)
    scores[seed] = 1.0
    why = {nid: "agree-fuse" for nid in scores}
    why[seed] = "seed"
    # Keep why from obligation when it found the node — more useful heatmap.
    ob = {c.node_id: c.why for c in arms[0].cells}
    for nid in why:
        if nid in ob and nid != seed:
            why[nid] = f"agree/{ob[nid]}"
    return _cells("agree_fuse", scores, why)


NOVEL_TRACERS = {
    "obligation": obligation_trace,
    "intent_slice": intent_slice,
    "ppr_idf": ppr_idf,
    "hub_shadow": hub_shadow,
    "spread_gate": spread_gate,
    "bridge_heat": bridge_heat,
    "agree_fuse": agree_fuse,
}
