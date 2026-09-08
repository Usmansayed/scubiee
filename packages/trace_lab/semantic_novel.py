"""Novel semantic-search tracer strategies (distinct from island rescore / soft teleport).

1) semantic_waypoint — ANN proposes targets; heat shortest structural paths seed→target
2) semantic_meet — grow forward from seed + backward from semantic targets; heat meetings
3) semantic_dual — second embed seed; structural expand from both; merge max heat

All still require structural edges for membership on paths. Vectors propose / prioritize.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from trace_lab.ast_graph import AstTraceGraph
from trace_lab.composite_v1 import (
    _load_composite_edges,
    _membership_edges,
    _save_composite_edges,
    _want_jedi,
    apply_rank_composite,
)
from trace_lab.embed_field import EmbedField
from trace_lab.engine.best_first import best_first_expand
from trace_lab.engine.frontier import build_frontier
from trace_lab.engine.heatmap import to_heatmap
from trace_lab.engine.semantic_best_first import semantic_best_first_expand
from trace_lab.facts import TypedEdge
from trace_lab.facts.call_graph import build_enriched_call_graph
from trace_lab.facts.dfg import build_dfg_edges
from trace_lab.facts.graphify_adapter import edges_from_graphify
from trace_lab.facts.pdg import compose_pdg
from trace_lab.lsp_index import LspIndex
from trace_lab.policy.intent import parse_trace_spec
from trace_lab.policy.slice_mask import demote_sinks_without_query
from trace_lab.semantic_compare import SemanticComparator
from trace_lab.semantic_index import SemanticIndex, from_embed_field
from trace_lab.system_trace import _user_query
from trace_lab.types import GoldCase, Heatmap, TraceNode


def _channels(
    uid: str,
    graph: AstTraceGraph,
    lsp: LspIndex,
    *,
    forward: bool = True,
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def add(v: str) -> None:
        if v != uid and v not in seen:
            seen.add(v)
            out.append(v)

    if forward:
        for vid, rel, _w in graph.neighbors(uid, directed=True):
            if rel in {"calls", "uses", "contains", "dispatches", "overrides"}:
                add(vid)
        for vid in lsp.dispatch.get(uid, []):
            add(vid)
        for vid in lsp.overrides.get(uid, []):
            add(vid)
    else:
        for vid, rel, _w in graph.neighbors(uid, directed=True):
            # reverse: who points to uid — scan is expensive; use used_by + reverse walk
            pass
        for vid in lsp.used_by.get(uid, []):
            add(vid)
        # also callers via undirected: neighbors where we are target — approximate via used_by only
    return out


def _build_rev(
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lsp: LspIndex,
) -> dict[str, list[str]]:
    rev: dict[str, list[str]] = {nid: [] for nid in nodes}
    for uid in nodes:
        for vid, rel, _w in graph.neighbors(uid, directed=True):
            if rel in {"calls", "uses", "contains", "dispatches", "overrides"} and vid in rev:
                rev[vid].append(uid)
        for vid in lsp.dispatch.get(uid, []):
            if vid in rev:
                rev[vid].append(uid)
    for uid, callers in lsp.used_by.items():
        if uid in rev:
            for c in callers:
                if c in rev:
                    rev[uid].append(c)
    # dedupe
    for k in rev:
        rev[k] = list(dict.fromkeys(rev[k]))
    return rev


def _bfs_path(
    start: str,
    goal: str,
    neighbors_fn,
    *,
    max_depth: int = 8,
) -> list[str] | None:
    if start == goal:
        return [start]
    parent: dict[str, str | None] = {start: None}
    q: deque[tuple[str, int]] = deque([(start, 0)])
    while q:
        u, d = q.popleft()
        if d >= max_depth:
            continue
        for v in neighbors_fn(u):
            if v in parent:
                continue
            parent[v] = u
            if v == goal:
                path = [v]
                while path[-1] != start:
                    path.append(parent[path[-1]] or start)
                path.reverse()
                return path
            q.append((v, d + 1))
    return None


def _pick_waypoints(
    cmp: SemanticComparator,
    nodes: dict[str, TraceNode],
    *,
    seed_id: str,
    query: str,
    top_k: int = 8,
    min_sim: float = 0.42,
) -> list[tuple[str, float]]:
    scored: list[tuple[str, float]] = []
    for nid in nodes:
        if nid == seed_id:
            continue
        n = nodes[nid]
        if n.kind == "class":
            continue
        if demote_sinks_without_query(n, query):
            continue
        s = cmp.node_sim(nid)
        if s >= min_sim:
            scored.append((nid, s))
    scored.sort(key=lambda kv: -kv[1])
    return scored[:top_k]


def _edge_bundle(
    root: Path,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lsp: LspIndex,
    extra_graph: AstTraceGraph | None,
    cache: dict,
) -> tuple[list[TypedEdge], list[TypedEdge]]:
    key = str(root)
    if key in cache:
        return cache[key]
    jedi = _want_jedi()
    try:
        from trace_lab.corpus import corpus_fingerprint

        fp = corpus_fingerprint(root)
    except Exception:  # noqa: BLE001
        fp = ""
    loaded = _load_composite_edges(root, fingerprint=fp, jedi=jedi) if fp else None
    if loaded is not None:
        call_e, dfg_e = loaded
    else:
        call_e = build_enriched_call_graph(
            root, nodes, graph, lsp, extra=extra_graph, with_jedi=jedi
        )
        call_e = compose_pdg(call_e, edges_from_graphify(extra_graph))
        dfg_e = build_dfg_edges(root, nodes, call_e)
        if fp:
            _save_composite_edges(root, fingerprint=fp, jedi=jedi, call_e=call_e, dfg_e=dfg_e)
    cache[key] = (call_e, dfg_e)
    return call_e, dfg_e


def run_semantic_waypoint(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex,
    *,
    root: Path,
    lsp: LspIndex,
    field: EmbedField | SemanticIndex,
    extra_graph: AstTraceGraph | None = None,
    call_edges: list[TypedEdge] | None = None,
    dfg_edges: list[TypedEdge] | None = None,
    top_k: int = 8,
    min_sim: float = 0.40,
) -> Heatmap:
    """Semantic search proposes waypoints; heat structural paths from seed."""
    del lex
    seed = case.seed.id
    user_q = _user_query(case)
    spec = parse_trace_spec(user_q)
    if call_edges is None or dfg_edges is None:
        raise ValueError("call_edges/dfg_edges required")

    cmp = SemanticComparator.from_field(field, nodes, query=user_q, seed_id=seed)
    waypoints = _pick_waypoints(cmp, nodes, seed_id=seed, query=user_q, top_k=top_k, min_sim=min_sim)

    def neigh(u: str) -> list[str]:
        return _channels(u, graph, lsp, forward=True)

    scores = {seed: 1.0}
    why = {seed: "seed|waypoint"}
    paths: dict[str, tuple[str, ...]] = {seed: (seed,)}

    for wid, wsem in waypoints:
        path = _bfs_path(seed, wid, neigh, max_depth=spec.hop_cap)
        if not path:
            continue
        for i, nid in enumerate(path):
            # closer to waypoint + higher waypoint sem → hotter
            hop = max(0, len(path) - 1 - i)
            sc = max(0.46, wsem * (0.92**hop))
            if sc > scores.get(nid, 0):
                scores[nid] = sc
                why[nid] = f"waypoint_path->{nodes[wid].symbol}|sem={wsem:.2f}"
                paths[nid] = tuple(path[: i + 1])

    # Also keep membership best-first spine so we don't under-expand
    edged = _membership_edges(list(call_edges), nodes, spec, nodes[seed].file)
    frontier = build_frontier(edged)
    s2, w2, p2, _ = best_first_expand(seed, nodes, frontier, spec, floor=0.18, hop_decay=0.965)
    for nid, sc in s2.items():
        if sc > scores.get(nid, 0):
            scores[nid] = sc
            why[nid] = w2.get(nid, "struct")
            paths[nid] = p2.get(nid, (nid,))

    dfg_pairs = {
        (e.source, e.target)
        for e in dfg_edges
        if e.relation == "PASSES_DATA_TO" and e.weight >= 0.85
    }
    scores, why, paths = apply_rank_composite(
        scores, why, paths, nodes, spec, dfg_pairs=dfg_pairs
    )
    return to_heatmap(
        "semantic_waypoint",
        scores,
        why,
        paths,
        extra={"engine": "semantic_waypoint", "n_waypoints": len(waypoints), **cmp.meta()},
    )


def run_semantic_meet(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex,
    *,
    root: Path,
    lsp: LspIndex,
    field: EmbedField | SemanticIndex,
    extra_graph: AstTraceGraph | None = None,
    call_edges: list[TypedEdge] | None = None,
    dfg_edges: list[TypedEdge] | None = None,
    top_k: int = 6,
    min_sim: float = 0.42,
) -> Heatmap:
    """Meet-in-the-middle: forward from seed, backward from semantic targets."""
    del lex, root, extra_graph
    seed = case.seed.id
    user_q = _user_query(case)
    spec = parse_trace_spec(user_q)
    if call_edges is None or dfg_edges is None:
        raise ValueError("call_edges/dfg_edges required")

    cmp = SemanticComparator.from_field(field, nodes, query=user_q, seed_id=seed)
    waypoints = _pick_waypoints(cmp, nodes, seed_id=seed, query=user_q, top_k=top_k, min_sim=min_sim)
    rev = _build_rev(nodes, graph, lsp)

    # Forward BFS layers
    fwd_dist: dict[str, int] = {seed: 0}
    q: deque[str] = deque([seed])
    while q:
        u = q.popleft()
        if fwd_dist[u] >= spec.hop_cap:
            continue
        for v in _channels(u, graph, lsp, forward=True):
            if v not in fwd_dist:
                fwd_dist[v] = fwd_dist[u] + 1
                q.append(v)

    scores = {seed: 1.0}
    why = {seed: "seed|meet"}
    paths: dict[str, tuple[str, ...]] = {seed: (seed,)}

    for wid, wsem in waypoints:
        back_dist: dict[str, int] = {wid: 0}
        bq: deque[str] = deque([wid])
        while bq:
            u = bq.popleft()
            if back_dist[u] >= spec.hop_cap:
                continue
            for v in rev.get(u, []):
                if v not in back_dist:
                    back_dist[v] = back_dist[u] + 1
                    bq.append(v)
        # Meeting points
        for nid in set(fwd_dist) & set(back_dist):
            total = fwd_dist[nid] + back_dist[nid]
            sc = max(0.46, wsem * (0.90**total))
            if sc > scores.get(nid, 0):
                scores[nid] = sc
                why[nid] = f"meet_fwd+back|{nodes[wid].symbol}|sem={wsem:.2f}"
                paths[nid] = (seed, nid, wid) if nid not in {seed, wid} else (seed, wid)
        # heat waypoint itself
        if wid in fwd_dist or wid == seed:
            scores[wid] = max(scores.get(wid, 0), max(0.5, wsem))
            why[wid] = f"meet_target|sem={wsem:.2f}"
            paths[wid] = (seed, wid)

    edged = _membership_edges(list(call_edges), nodes, spec, nodes[seed].file)
    frontier = build_frontier(edged)
    s2, w2, p2, _ = semantic_best_first_expand(
        seed, nodes, frontier, spec, cmp, floor=0.18, hop_decay=0.965, refresh_every=3
    )
    for nid, sc in s2.items():
        if sc > scores.get(nid, 0):
            scores[nid] = sc
            why[nid] = w2.get(nid, "sem_bf")
            paths[nid] = p2.get(nid, (nid,))

    dfg_pairs = {
        (e.source, e.target)
        for e in dfg_edges
        if e.relation == "PASSES_DATA_TO" and e.weight >= 0.85
    }
    scores, why, paths = apply_rank_composite(
        scores, why, paths, nodes, spec, dfg_pairs=dfg_pairs
    )
    return to_heatmap(
        "semantic_meet",
        scores,
        why,
        paths,
        extra={"engine": "semantic_meet", "n_waypoints": len(waypoints), **cmp.meta()},
    )


def run_semantic_dual(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex,
    *,
    root: Path,
    lsp: LspIndex,
    field: EmbedField | SemanticIndex,
    extra_graph: AstTraceGraph | None = None,
    call_edges: list[TypedEdge] | None = None,
    dfg_edges: list[TypedEdge] | None = None,
) -> Heatmap:
    """Second semantic seed outside the seed file; merge two structural expands."""
    del lex, root, extra_graph
    seed = case.seed.id
    user_q = _user_query(case)
    spec = parse_trace_spec(user_q)
    if call_edges is None or dfg_edges is None:
        raise ValueError("call_edges/dfg_edges required")

    cmp = SemanticComparator.from_field(field, nodes, query=user_q, seed_id=seed)
    seed_file = nodes[seed].file
    best_id = ""
    best_sc = -1.0
    for nid, n in nodes.items():
        if nid == seed or n.file == seed_file or n.kind == "class":
            continue
        if demote_sinks_without_query(n, user_q):
            continue
        s = cmp.node_sim(nid)
        if s > best_sc:
            best_sc = s
            best_id = nid

    edged = _membership_edges(list(call_edges), nodes, spec, seed_file)
    frontier = build_frontier(edged)
    s1, w1, p1, _ = best_first_expand(seed, nodes, frontier, spec, floor=0.18, hop_decay=0.965)
    scores = dict(s1)
    why = dict(w1)
    paths = dict(p1)
    if best_id and best_id in nodes and best_sc >= 0.50:
        edged2 = _membership_edges(list(call_edges), nodes, spec, nodes[best_id].file)
        frontier2 = build_frontier(edged2)
        s2, w2, p2, _ = best_first_expand(
            best_id, nodes, frontier2, spec, floor=0.18, hop_decay=0.965
        )
        primary_island = set(s1)
        for nid, sc in s2.items():
            # Only merge nodes that also touch the primary structural island
            # (or the dual seed itself if linked to primary).
            if nid not in primary_island and nid != best_id:
                # allow if 1-hop linked to primary
                linked = any(
                    nid in _channels(p, graph, lsp, forward=True)
                    or p in _channels(nid, graph, lsp, forward=True)
                    for p in list(primary_island)[:80]
                )
                if not linked:
                    continue
            sc2 = sc * max(0.50, min(0.85, best_sc))
            if sc2 > scores.get(nid, 0):
                scores[nid] = sc2
                why[nid] = f"dual_seed|{nodes[best_id].symbol}|{w2.get(nid, '')}"
                paths[nid] = p2.get(nid, (nid,))
        if best_id in primary_island or any(
            best_id in _channels(p, graph, lsp, forward=True) for p in list(primary_island)[:80]
        ):
            scores[best_id] = max(scores.get(best_id, 0), max(0.48, best_sc * 0.9))
            why[best_id] = f"dual_seed_anchor|sem={best_sc:.2f}"

    dfg_pairs = {
        (e.source, e.target)
        for e in dfg_edges
        if e.relation == "PASSES_DATA_TO" and e.weight >= 0.85
    }
    scores, why, paths = apply_rank_composite(
        scores, why, paths, nodes, spec, dfg_pairs=dfg_pairs
    )
    return to_heatmap(
        "semantic_dual",
        scores,
        why,
        paths,
        extra={
            "engine": "semantic_dual",
            "second_seed": best_id,
            "second_sem": round(best_sc, 4),
            **cmp.meta(),
        },
    )


def _bind_novel(run_fn, strategy: str):
    def bind(
        root: Path,
        lsp: LspIndex,
        field: EmbedField | SemanticIndex,
        extra_graph: AstTraceGraph | None = None,
    ):
        root = Path(root)
        index = field if isinstance(field, SemanticIndex) else from_embed_field(field)
        cache: dict = {}

        def _run(case, nodes, graph, lex):
            call_e, dfg_e = _edge_bundle(root, nodes, graph, lsp, extra_graph, cache)
            return run_fn(
                case,
                nodes,
                graph,
                lex,
                root=root,
                lsp=lsp,
                field=index,
                extra_graph=extra_graph,
                call_edges=call_e,
                dfg_edges=dfg_e,
            )

        return _run

    return bind


bind_semantic_waypoint = _bind_novel(run_semantic_waypoint, "semantic_waypoint")
bind_semantic_meet = _bind_novel(run_semantic_meet, "semantic_meet")
bind_semantic_dual = _bind_novel(run_semantic_dual, "semantic_dual")


def bind_semantic_ensemble(
    root: Path,
    lsp: LspIndex,
    field: EmbedField | SemanticIndex,
    extra_graph: AstTraceGraph | None = None,
):
    """Max-fuse composite_v1 + comparator fuse + poly_embed (OOD ensemble)."""
    root = Path(root)
    from trace_lab.composite_v1 import bind_composite_v1
    from trace_lab.poly_embed import bind_poly_embed
    from trace_lab.semantic_tracer_fuse import bind_semantic_tracer_fuse
    from trace_lab.types import HeatCell

    struct = bind_composite_v1(root, lsp, extra_graph)
    fuse = bind_semantic_tracer_fuse(root, lsp, field, extra_graph)
    poly = bind_poly_embed(lsp, field if not isinstance(field, SemanticIndex) else field.field)

    def _run(case, nodes, graph, lex):
        maps = [
            struct(case, nodes, graph, lex),
            fuse(case, nodes, graph, lex),
            poly(case, nodes, graph, lex),
        ]
        by: dict[str, HeatCell] = {}
        for hm in maps:
            for c in hm.cells:
                prev = by.get(c.node_id)
                if prev is None or c.score > prev.score:
                    by[c.node_id] = HeatCell(
                        node_id=c.node_id,
                        score=c.score,
                        why=f"ensemble|{hm.strategy}|{c.why}",
                        path=c.path,
                    )
        cells = sorted(by.values(), key=lambda x: -x.score)
        return Heatmap(
            strategy="semantic_ensemble",
            cells=cells,
            extra={"engine": "semantic_ensemble", "arms": [m.strategy for m in maps]},
        )

    return _run
