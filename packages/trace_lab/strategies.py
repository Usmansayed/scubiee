"""Pluggable tracing strategies. Add a function here to try a new idea."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from trace_lab.ast_graph import AstTraceGraph, build_ast_graph
from trace_lab.graphify_layer import build_graphify_graph
from trace_lab.lsp_index import build_lsp_index
from trace_lab.novel import NOVEL_TRACERS
from trace_lab.polytrace import bind_polytrace
from trace_lab.propagate import PropagatePolicy, propagate
from trace_lab.retrieve import LexicalIndex, expand_query, normalize, query_similarity
from trace_lab.types import GoldCase, HeatCell, Heatmap, TraceNode

Tracer = Callable[[GoldCase, dict[str, TraceNode], AstTraceGraph, LexicalIndex], Heatmap]


def _seed_id(case: GoldCase, nodes: dict[str, TraceNode]) -> str:
    sid = case.seed.id
    if sid in nodes:
        return sid
    raise KeyError(f"seed {sid} not in corpus")


def _top_heatmap(strategy: str, scores: dict[str, float], why: str, *, k: int = 16) -> Heatmap:
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    cells = [
        HeatCell(node_id=nid, score=round(sc, 4), why=why, path=(nid,))
        for nid, sc in ranked[:k]
        if sc > 0
    ]
    return Heatmap(strategy=strategy, cells=cells)


def bm25_body(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex: LexicalIndex,
) -> Heatmap:
    del graph
    raw = lex.bm25_scores(case.query)
    scores = normalize(raw)
    seed = _seed_id(case, nodes)
    scores[seed] = 1.0
    return _top_heatmap("bm25_body", scores, "bm25 body")


def bm25_expanded(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex: LexicalIndex,
) -> Heatmap:
    del graph
    raw = lex.bm25_scores(expand_query(case.query))
    scores = normalize(raw)
    seed = _seed_id(case, nodes)
    scores[seed] = 1.0
    return _top_heatmap("bm25_expanded", scores, "bm25 + synonyms")


def tfidf(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex: LexicalIndex,
) -> Heatmap:
    del graph
    raw = lex.tfidf_scores(case.query)
    scores = normalize(raw)
    seed = _seed_id(case, nodes)
    scores[seed] = 1.0
    return _top_heatmap("tfidf", scores, "tfidf cosine")


def ast_undirected_bfs(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex: LexicalIndex,
) -> Heatmap:
    del lex
    seed = _seed_id(case, nodes)
    pol = PropagatePolicy(
        directed=False,
        query_mix=0.0,
        infra_penalty=1.0,
        hub_penalty=1.0,
        hop_decay=0.92,
        floor=0.08,
        max_hops=6,
        strategy_name="ast_undirected_bfs",
    )
    return propagate(graph, {seed: 1.0}, case.query, policy=pol, why0={seed: "seed"})


def ast_propagate(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex: LexicalIndex,
) -> Heatmap:
    del lex
    seed = _seed_id(case, nodes)
    return propagate(
        graph,
        {seed: 1.0},
        case.query,
        policy=PropagatePolicy(strategy_name="ast_propagate"),
        why0={seed: "seed"},
    )


def hybrid(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex: LexicalIndex,
) -> Heatmap:
    """Seed + graph-confirmed BM25 weak seeds + relevance-aware AST walk."""
    seed = _seed_id(case, nodes)
    seeds = {seed: 1.0}
    why = {seed: "seed"}
    bm = normalize(lex.bm25_scores(expand_query(case.query)))
    reachable = _confirm_reach(graph, seed, case.query, max_hops=4)
    for nid, sc in bm.items():
        if nid == seed or sc < 0.35:
            continue
        if nid not in reachable:
            continue
        # Body overlap (e.g. log("verified")) must not promote a neighbor
        # the query did not actually name.
        if query_similarity(case.query, nodes[nid]) <= 0:
            continue
        seeds[nid] = max(seeds.get(nid, 0.0), 0.55 * sc)
        why[nid] = "bm25 confirmed by graph"
    return propagate(
        graph,
        seeds,
        case.query,
        policy=PropagatePolicy(strategy_name="hybrid"),
        why0=why,
    )


def graphify_propagate(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex: LexicalIndex,
    *,
    ggraph: AstTraceGraph,
) -> Heatmap:
    del graph, lex
    seed = _seed_id(case, nodes)
    return propagate(
        ggraph,
        {seed: 1.0},
        case.query,
        policy=PropagatePolicy(strategy_name="graphify_propagate"),
        why0={seed: "seed"},
    )


def _confirm_reach(
    graph: AstTraceGraph, seed: str, query: str, *, max_hops: int
) -> set[str]:
    """Directed callees from the seed; infra nodes are sinks, not bridges."""
    from trace_lab.propagate import is_infra

    seen = {seed}
    frontier = [seed]
    for _ in range(max_hops):
        nxt: list[str] = []
        for uid in frontier:
            for vid, _rel, _w in graph.neighbors(uid, directed=True):
                if vid in seen:
                    continue
                seen.add(vid)
                vnode = graph.nodes.get(vid)
                if vnode is not None and is_infra(vnode, query):
                    continue
                nxt.append(vid)
        frontier = nxt
        if not frontier:
            break
    return seen


def default_tracers() -> dict[str, Tracer]:
    return {
        "bm25_body": bm25_body,
        "bm25_expanded": bm25_expanded,
        "tfidf": tfidf,
        "ast_undirected_bfs": ast_undirected_bfs,
        "ast_propagate": ast_propagate,
        "hybrid": hybrid,
        **NOVEL_TRACERS,
    }


def bind_graphify(ggraph: AstTraceGraph) -> Tracer:
    def _run(case, nodes, graph, lex):
        return graphify_propagate(case, nodes, graph, lex, ggraph=ggraph)

    return _run


def compile_bundle(
    root: Path, *, cache_root: Path | None = None, with_graphify: bool = True,
    with_embed_power: bool = False,
    require_real_embeds: bool = False,
) -> tuple[dict[str, TraceNode], AstTraceGraph, LexicalIndex, dict[str, Tracer]]:
    from trace_lab.corpus import extract_nodes

    nodes = extract_nodes(root)
    graph = build_ast_graph(root, nodes)
    lex = LexicalIndex(nodes, include_path=False)
    tracers = default_tracers()
    ggraph = None
    if with_graphify:
        ggraph = build_graphify_graph(root, nodes, cache_root=cache_root)
        tracers["graphify_propagate"] = bind_graphify(ggraph)
    lsp = build_lsp_index(root, nodes, graph)
    tracers["polytrace"] = bind_polytrace(lsp, extra_graph=ggraph)
    from trace_lab.ultimate_trace import bind_ultimate_trace

    tracers["ultimate_trace"] = bind_ultimate_trace(lsp, extra_graph=ggraph)
    from trace_lab.arms import register_system_arms

    register_system_arms(root, lsp, ggraph, tracers)
    if with_embed_power:
        from trace_lab.embed_field import EmbedField
        from trace_lab.embed_power import bind_embed_power, bind_embed_power_oracle
        from trace_lab.poly_embed import bind_poly_embed

        field = EmbedField(
            nodes,
            cache_path=root / ".embed_cache" / "coderank.jsonl",
            require_real=require_real_embeds,
            quiet=True,
        )
        tracers["embed_power"] = bind_embed_power(lsp, field)
        tracers["embed_power_oracle"] = bind_embed_power_oracle(lsp, field)
        tracers["poly_embed"] = bind_poly_embed(lsp, field)
        from trace_lab.composite_semantic import bind_composite_semantic
        from trace_lab.semantic_trace import bind_semantic_trace

        tracers["semantic_trace"] = bind_semantic_trace(lsp, field)
        tracers["composite_semantic_add"] = bind_composite_semantic(
            root, lsp, field, mode="add", extra_graph=ggraph
        )
        tracers["composite_semantic_gate"] = bind_composite_semantic(
            root, lsp, field, mode="gate", extra_graph=ggraph
        )
        from trace_lab.semantic_tracer_v1 import bind_semantic_tracer_v1

        tracers["semantic_tracer_v1"] = bind_semantic_tracer_v1(
            root, lsp, field, extra_graph=ggraph
        )
        from trace_lab.semantic_tracer_fuse import bind_semantic_tracer_fuse

        tracers["semantic_tracer_fuse"] = bind_semantic_tracer_fuse(
            root, lsp, field, extra_graph=ggraph
        )
        # Ablation: strict teleport (historically hurts F1 — research only)
        tracers["semantic_tracer_fuse_teleport"] = bind_semantic_tracer_fuse(
            root,
            lsp,
            field,
            extra_graph=ggraph,
            with_teleport=True,
            strategy="semantic_tracer_fuse_teleport",
        )
        from trace_lab.semantic_novel import (
            bind_semantic_dual,
            bind_semantic_ensemble,
            bind_semantic_meet,
            bind_semantic_waypoint,
        )

        tracers["semantic_waypoint"] = bind_semantic_waypoint(root, lsp, field, ggraph)
        tracers["semantic_meet"] = bind_semantic_meet(root, lsp, field, ggraph)
        tracers["semantic_dual"] = bind_semantic_dual(root, lsp, field, ggraph)
        tracers["semantic_ensemble"] = bind_semantic_ensemble(root, lsp, field, ggraph)
        from trace_lab.semantic_hybrid import register_hybrid_arms

        register_hybrid_arms(tracers, root, lsp, field, extra_graph=ggraph)
        # Top-5 semantic venture arms (research). Always register with embed power;
        # production default remains composite_v1.
        from trace_lab.semantic_venture import bind_venture_arms

        bind_venture_arms(tracers, root, lsp, field, extra_graph=ggraph)
    return nodes, graph, lex, tracers
