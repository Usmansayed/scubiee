"""semantic_tracer_v1 — composite membership + comparator-guided expansion.

Cycle 1 R&D arm. Does not invent edges; embeddings only rank legal hops.
"""

from __future__ import annotations

from pathlib import Path

from trace_lab.ast_graph import AstTraceGraph
from trace_lab.composite_v1 import (
    _membership_edges,
    _want_jedi,
    apply_rank_composite,
    _load_composite_edges,
    _save_composite_edges,
)
from trace_lab.embed_field import EmbedField
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
from trace_lab.semantic_compare import SemanticComparator
from trace_lab.semantic_index import SemanticIndex, from_embed_field
from trace_lab.system_trace import _embed_query, _user_query
from trace_lab.types import GoldCase, Heatmap, TraceNode


def run_semantic_tracer_v1(
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
    del lex  # Cycle 1: dense comparators only; BM25 teleport is Cycle 2
    seed = case.seed.id
    if seed not in nodes:
        raise KeyError(f"seed {seed} not in corpus")

    user_q = _user_query(case)
    embed_q = _embed_query(case)
    spec = parse_trace_spec(user_q)
    seed_file = nodes[seed].file

    if call_edges is None:
        call_edges = build_enriched_call_graph(
            root, nodes, graph, lsp, extra=extra_graph, with_jedi=_want_jedi()
        )
        call_edges = compose_pdg(call_edges, edges_from_graphify(extra_graph))
    if dfg_edges is None:
        dfg_edges = build_dfg_edges(root, nodes, call_edges)

    edged = _membership_edges(list(call_edges), nodes, spec, seed_file)
    frontier = build_frontier(edged)

    cmp = SemanticComparator.from_field(field, nodes, query=embed_q, seed_id=seed)
    scores, why, paths, _reach = semantic_best_first_expand(
        seed, nodes, frontier, spec, cmp, floor=0.18, hop_decay=0.965
    )

    dfg_pairs = {
        (e.source, e.target)
        for e in dfg_edges
        if e.relation == "PASSES_DATA_TO" and e.weight >= 0.85
    }
    scores, why, paths = apply_rank_composite(
        scores, why, paths, nodes, spec, dfg_pairs=dfg_pairs
    )

    return to_heatmap(
        "semantic_tracer_v1",
        scores,
        why,
        paths,
        extra={
            "mode": spec.mode,
            "engine": "semantic_tracer_v1",
            "n_edges": len(edged),
            "dfg_boost_pairs": len(dfg_pairs),
            **cmp.meta(),
        },
    )


def bind_semantic_tracer_v1(
    root: Path,
    lsp: LspIndex,
    field: EmbedField | SemanticIndex,
    extra_graph: AstTraceGraph | None = None,
):
    """Bind with shared composite edge disk/memory cache (same as composite_v1)."""
    root = Path(root)
    index = field if isinstance(field, SemanticIndex) else from_embed_field(field)
    cache: dict[str, tuple[list[TypedEdge], list[TypedEdge]]] = {}

    def _run(case, nodes, graph, lex):
        key = str(root)
        if key not in cache:
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
                    _save_composite_edges(
                        root, fingerprint=fp, jedi=jedi, call_e=call_e, dfg_e=dfg_e
                    )
            cache[key] = (call_e, dfg_e)
        call_e, dfg_e = cache[key]
        return run_semantic_tracer_v1(
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
