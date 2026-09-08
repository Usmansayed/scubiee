"""Ultimate Tracer v1 — query-conditioned hybrid on polytrace channels.

Research: SCUBIEE_SEMANTIC_TRACER_RESEARCH.md §34.
Builds on polytrace (LSP+AST+Graphify+faction firewall) and adds:
  - query-conditioned edge weights
  - Code-IDF / generic hub penalty
  - path reinforcement
  - light Personalized PageRank rescoring
  - one-shot BM25 semantic teleport (structurally validated)
  - information-gain / frontier stopping
"""

from __future__ import annotations

import heapq
import math
from collections import defaultdict
from dataclasses import dataclass

from conductor.bm25_index import tokenize
from trace_lab.ast_graph import AstTraceGraph
from trace_lab.lsp_index import LspIndex
from trace_lab.polytrace import (
    FORWARD,
    _HOP,
    _allow,
    _channels,
    _lex_confirm,
    _raw_overlap,
    _skip_node,
    is_foreign,
)
from trace_lab.retrieve import normalize, query_intent, query_similarity
from trace_lab.types import GoldCase, HeatCell, Heatmap, TraceNode

_GENERIC_NAMES = frozenset(
    {
        "log",
        "logger",
        "info",
        "debug",
        "warn",
        "error",
        "print",
        "metrics",
        "metric",
        "analytics",
        "helper",
        "helpers",
        "utils",
        "util",
        "common",
        "noop",
        "pass_",
    }
)

# Base edge weights (research §15 starting point — tunable).
_EDGE_BASE = {
    "uses": 1.00,
    "calls": 0.92,
    "dispatches": 0.88,
    "contains": 0.55,
    "overrides": 0.75,
    "method": 0.90,
}

# Intent multiplies edge families.
_INTENT_EDGE_BOOST: dict[str, dict[str, float]] = {
    "flow": {"calls": 1.05, "uses": 1.10, "dispatches": 1.05, "contains": 0.85},
    "entry": {"calls": 1.08, "uses": 1.00, "dispatches": 1.10, "contains": 0.90},
    "config": {"uses": 1.15, "overrides": 1.10, "calls": 0.85, "contains": 0.80},
    "site": {"calls": 0.70, "uses": 0.70},
    "refs": {},
}


@dataclass
class UltimateConfig:
    floor: float = 0.10
    hop_decay: float = 0.97
    multi_path: float = 0.28
    generic_penalty: float = 0.70
    hub_degree: int = 18
    hub_penalty: float = 0.85
    teleport_top: int = 6
    teleport_bm25_min: float = 0.40
    teleport_admit: float = 0.42
    ppr_damping: float = 0.85
    ppr_iters: int = 5
    gain_window: int = 8
    gain_min: float = 0.015
    frontier_stop: float = 0.10
    max_nodes: int = 64
    enable_ppr: bool = True  # best verify_prod F1 ~0.73 with PPR on
    enable_teleport: bool = True
    enable_early_stop: bool = False  # v1 bakeoff: hop_cap primary; gain stop optional


def _edge_weight(intent: str, rel: str, base: float) -> float:
    """Scale the channel weight; do not replace it (keeps polytrace geometry)."""
    boost = _INTENT_EDGE_BOOST.get(intent, {}).get(rel, 1.0)
    # Mild family prior relative to polytrace channel weights.
    prior = {"uses": 1.05, "calls": 1.0, "dispatches": 1.0, "contains": 0.92, "overrides": 1.0}.get(
        rel, 1.0
    )
    return float(base) * float(boost) * float(prior)


def _genericness(node: TraceNode, degree: int, *, hub_degree: int) -> float:
    """1.0 = specific; lower = more generic (penalty multiplier)."""
    short = node.symbol.split(".")[-1].lower()
    pen = 1.0
    if short in _GENERIC_NAMES:
        pen *= 0.35
    path = "/" + node.file.replace("\\", "/").lower()
    if any(m in path for m in ("/logger.py", "/analytics/", "/metrics", "/helpers/", "/utils/")):
        pen *= 0.45
    if degree >= hub_degree:
        # Code-IDF style: hubs are common connections.
        idf = 1.0 / math.log2(2 + degree)
        pen *= max(0.25, idf)
    return max(0.15, min(1.0, pen))


def _structural_neighbor(
    uid: str,
    vid: str,
    graph: AstTraceGraph,
    lsp: LspIndex,
    extra: AstTraceGraph | None,
) -> bool:
    for dst, _rel, _w in _channels(uid, graph, lsp, extra):
        if dst == vid:
            return True
    for dst, _rel, _w in graph.neighbors(vid, directed=True):
        if dst == uid:
            return True
    return False


def _light_ppr(
    scores: dict[str, float],
    adj: dict[str, list[tuple[str, float]]],
    *,
    damping: float,
    iters: int,
) -> dict[str, float]:
    if not scores:
        return scores
    nodes = list(scores)
    nset = set(nodes)
    # Personalization = normalized current heat
    total = sum(max(0.0, scores[n]) for n in nodes) or 1.0
    pers = {n: max(0.0, scores[n]) / total for n in nodes}
    rank = dict(pers)
    for _ in range(iters):
        nxt = {n: (1.0 - damping) * pers[n] for n in nodes}
        for u in nodes:
            outs = [(v, w) for v, w in adj.get(u, []) if v in nset]
            if not outs:
                for n in nodes:
                    nxt[n] += damping * rank[u] / len(nodes)
                continue
            tw = sum(w for _v, w in outs) or 1.0
            for v, w in outs:
                nxt[v] += damping * rank[u] * (w / tw)
        rank = nxt
    # Blend with original scores so PPR can't erase seed certainty.
    out: dict[str, float] = {}
    for n in nodes:
        out[n] = 0.65 * scores[n] + 0.35 * rank.get(n, 0.0)
    # Renormalize so seed stays ~1
    seed = max(scores, key=lambda k: scores[k])
    if out.get(seed, 0) > 0:
        scale = scores[seed] / out[seed]
        out = {k: min(1.0, v * scale) for k, v in out.items()}
    return out


def ultimate_trace(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex,
    *,
    lsp: LspIndex,
    extra_graph: AstTraceGraph | None = None,
    config: UltimateConfig | None = None,
) -> Heatmap:
    cfg = config or UltimateConfig()
    seed = case.seed.id
    if seed not in nodes:
        raise KeyError(f"seed {seed} not in corpus")
    intent = query_intent(case.query)
    seed_file = nodes[seed].file
    why: dict[str, str] = {seed: f"seed/{intent}"}
    paths: dict[str, tuple[str, ...]] = {seed: (seed,)}
    scores: dict[str, float] = {seed: 1.0}
    path_hits: dict[str, int] = defaultdict(int)
    path_hits[seed] = 1
    adj: dict[str, list[tuple[str, float]]] = defaultdict(list)

    # Refs / config-const: keep polytrace-specialized short paths, then ultimate post.
    if intent == "refs":
        for vid in lsp.used_by.get(seed, []):
            dst = graph.nodes.get(vid) or nodes.get(vid)
            if dst is None or _skip_node(dst, seed=seed):
                continue
            if is_foreign(dst, case.query, seed_file):
                continue
            scores[vid] = max(scores.get(vid, 0.0), 0.92)
            why[vid] = f"lsp-refs {nodes[seed].symbol}"
            paths[vid] = (seed, vid)
            path_hits[vid] += 1
        return _finalize(scores, why, paths, path_hits, adj, cfg, strategy="ultimate_trace")

    if intent == "config" and nodes[seed].kind == "const":
        for vid in lsp.used_by.get(seed, []):
            dst = graph.nodes.get(vid) or nodes.get(vid)
            if dst is None or _skip_node(dst, seed=seed):
                continue
            if is_foreign(dst, case.query, seed_file):
                continue
            scores[vid] = max(scores.get(vid, 0.0), 0.92)
            why[vid] = f"config-refs {nodes[seed].symbol}"
            paths[vid] = (seed, vid)
            path_hits[vid] += 1

    hop_cap = _HOP.get(intent, 6)
    heap: list[tuple[float, int, str]] = [(-1.0, 0, seed)]
    seen: set[str] = set()
    recent_gains: list[float] = []
    expansions = 0

    while heap:
        neg, hop, uid = heapq.heappop(heap)
        best_frontier = -neg
        if best_frontier < cfg.frontier_stop and uid != seed and expansions > 3:
            if cfg.enable_early_stop:
                break
        if uid in seen:
            continue
        seen.add(uid)
        if hop >= hop_cap:
            continue
        if len(scores) >= cfg.max_nodes:
            break
        src = graph.nodes.get(uid)
        if src is None:
            continue

        gained = 0.0
        for vid, rel, weight in _channels(uid, graph, lsp, extra_graph):
            dst = graph.nodes.get(vid) or nodes.get(vid)
            if dst is None or _skip_node(dst, seed=seed):
                continue
            if not _allow(intent, rel, dst, case.query, seed_file):
                continue
            ew = _edge_weight(intent, rel, weight)
            deg = graph.degree.get(vid, 0)
            gen = _genericness(dst, deg, hub_degree=cfg.hub_degree)
            # Soften genericness toward research generic_penalty knob.
            gen = 1.0 - (1.0 - gen) * cfg.generic_penalty
            # Query-named generics keep fuller weight.
            if _raw_overlap(case.query, dst) and dst.symbol.split(".")[-1].lower() in _GENERIC_NAMES:
                gen = max(gen, 0.9)
            incoming = scores[uid] * ew * (cfg.hop_decay**hop) * gen
            if deg >= cfg.hub_degree and not _raw_overlap(case.query, dst):
                incoming *= cfg.hub_penalty
            if incoming < cfg.floor:
                continue

            adj[uid].append((vid, ew))
            # Path reinforcement: second independent path boosts.
            if vid in scores and paths.get(vid, ())[:1] != paths.get(uid, (uid,))[:1]:
                path_hits[vid] += 1
                boost = incoming * cfg.multi_path * min(3, path_hits[vid] - 1)
                scores[vid] = min(1.0, scores[vid] + boost)
                why[vid] = f"{why.get(vid, rel)}|path×{path_hits[vid]}"
                gained += boost
                continue

            if incoming <= scores.get(vid, 0.0) + 1e-9:
                continue
            prev = scores.get(vid, 0.0)
            scores[vid] = incoming
            path_hits[vid] = max(1, path_hits.get(vid, 0))
            why[vid] = f"{rel} {src.symbol}->{dst.symbol}"
            paths[vid] = (paths.get(uid, (uid,)) + (vid,))[-8:]
            gained += incoming - prev
            heapq.heappush(heap, (-incoming, hop + 1, vid))

        expansions += 1
        recent_gains.append(gained)
        if cfg.enable_early_stop and len(recent_gains) >= cfg.gain_window:
            if sum(recent_gains[-cfg.gain_window :]) < cfg.gain_min:
                break

    # Lex confirm (config only) — same as polytrace.
    _lex_confirm(case, nodes, graph, lex, lsp, scores, why, seed, seed_file, intent)

    # Semantic teleport once: BM25 islands validated by structure.
    if cfg.enable_teleport and lex is not None and intent in {"flow", "entry", "config"}:
        bm = normalize(lex.bm25_scores(case.query))
        reachable = set(scores)
        cand = sorted(bm.items(), key=lambda kv: -kv[1])[: cfg.teleport_top]
        for nid, sc in cand:
            if nid in reachable or nid == seed or sc < cfg.teleport_bm25_min:
                continue
            dst = nodes.get(nid)
            if dst is None or _skip_node(dst, seed=seed):
                continue
            if is_foreign(dst, case.query, seed_file):
                continue
            if query_similarity(case.query, dst) <= 0 and not _raw_overlap(case.query, dst):
                continue
            # Must touch the reachable set structurally.
            linked = any(
                _structural_neighbor(r, nid, graph, lsp, extra_graph) for r in list(reachable)[:80]
            )
            if not linked:
                continue
            gen = _genericness(dst, graph.degree.get(nid, 0), hub_degree=cfg.hub_degree)
            gen = 1.0 - (1.0 - gen) * cfg.generic_penalty
            admit = cfg.teleport_admit * sc * gen
            if admit < cfg.floor:
                continue
            scores[nid] = max(scores.get(nid, 0.0), admit)
            why[nid] = f"teleport+struct bm25={sc:.2f}"
            paths[nid] = (seed, nid)
            path_hits[nid] += 1
            reachable.add(nid)

    # Light PPR on discovered subgraph.
    if cfg.enable_ppr and len(scores) >= 3:
        scores = _light_ppr(
            scores, adj, damping=cfg.ppr_damping, iters=cfg.ppr_iters
        )

    # Final path-reinforcement polish.
    for nid, hits in path_hits.items():
        if hits > 1 and nid in scores:
            scores[nid] = min(1.0, scores[nid] * (1.0 + 0.04 * (hits - 1)))

    return _finalize(scores, why, paths, path_hits, adj, cfg, strategy="ultimate_trace")


def _finalize(
    scores: dict[str, float],
    why: dict[str, str],
    paths: dict[str, tuple[str, ...]],
    path_hits: dict[str, int],
    adj: dict[str, list[tuple[str, float]]],
    cfg: UltimateConfig,
    *,
    strategy: str,
) -> Heatmap:
    del adj, cfg
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    cells = [
        HeatCell(
            node_id=nid,
            score=round(sc, 4),
            why=why.get(nid, strategy),
            path=paths.get(nid, (nid,)),
        )
        for nid, sc in ranked
        if sc > 0
    ]
    return Heatmap(
        strategy=strategy,
        cells=cells,
        extra={"path_hits": dict(path_hits), "engine": "ultimate_v1"},
    )


def bind_ultimate_trace(
    lsp: LspIndex,
    extra_graph: AstTraceGraph | None = None,
    config: UltimateConfig | None = None,
):
    def ultimate(case, nodes, graph, lex):
        return ultimate_trace(
            case,
            nodes,
            graph,
            lex,
            lsp=lsp,
            extra_graph=extra_graph,
            config=config,
        )

    return ultimate
