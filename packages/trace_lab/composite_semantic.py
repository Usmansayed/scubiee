"""composite_semantic — composite_v1 + Phase 0 semantic sensor (wrapper arm).

Membership comes only from composite_v1. Embeddings rescore/gate the island.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from trace_lab.ast_graph import AstTraceGraph
from trace_lab.composite_v1 import bind_composite_v1, run_composite_v1
from trace_lab.embed_field import EmbedField
from trace_lab.lsp_index import LspIndex
from trace_lab.semantic_index import SemanticIndex, from_embed_field
from trace_lab.semantic_sensor import (
    ALPHA_DEFAULT,
    TAU_DEFAULT,
    apply_additive,
    apply_gate,
    node_sem_scores,
)
from trace_lab.types import GoldCase, Heatmap, TraceNode

SemanticMode = Literal["add", "gate"]


def run_composite_semantic(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex,
    *,
    root: Path,
    lsp: LspIndex,
    field: EmbedField | SemanticIndex,
    mode: SemanticMode = "add",
    extra_graph: AstTraceGraph | None = None,
    call_edges=None,
    dfg_edges=None,
    struct_heatmap: Heatmap | None = None,
    alpha: float = ALPHA_DEFAULT,
    tau: float = TAU_DEFAULT,
) -> Heatmap:
    """Run composite_v1 then apply semantic add or gate on the same island."""
    if struct_heatmap is None:
        struct_heatmap = run_composite_v1(
            case,
            nodes,
            graph,
            lex,
            root=root,
            lsp=lsp,
            extra_graph=extra_graph,
            call_edges=call_edges,
            dfg_edges=dfg_edges,
        )

    index = field if isinstance(field, SemanticIndex) else from_embed_field(field)
    seed = case.seed.id
    ids = [c.node_id for c in struct_heatmap.cells]
    q_aff = index.query_affinities(case.query)
    s_aff = index.seed_affinities(seed)
    # Restrict maps to island (sensor does not invent nodes)
    q_island = {nid: float(q_aff.get(nid, 0.0)) for nid in ids}
    s_island = {nid: float(s_aff.get(nid, 0.0)) for nid in ids}
    sem = node_sem_scores(ids, q_aff=q_island, seed_id=seed, seed_aff=s_island)

    meta = {
        **index.meta(),
        "w_query": 0.6,
        "w_seed": 0.4,
        "struct_engine": struct_heatmap.strategy,
    }
    if mode == "gate":
        return apply_gate(
            struct_heatmap,
            sem,
            tau=tau,
            seed_id=seed,
            strategy="composite_semantic_gate",
            extra=meta,
        )
    return apply_additive(
        struct_heatmap,
        sem,
        alpha=alpha,
        strategy="composite_semantic_add",
        extra=meta,
    )


def bind_composite_semantic(
    root: Path,
    lsp: LspIndex,
    field: EmbedField | SemanticIndex,
    *,
    mode: SemanticMode = "add",
    extra_graph: AstTraceGraph | None = None,
    alpha: float = ALPHA_DEFAULT,
    tau: float = TAU_DEFAULT,
):
    """Bind a tracer that wraps the shared composite_v1 edge cache via bind_composite_v1."""
    root = Path(root)
    struct_fn = bind_composite_v1(root, lsp, extra_graph)
    index = field if isinstance(field, SemanticIndex) else from_embed_field(field)

    def _run(case, nodes, graph, lex):
        struct_hm = struct_fn(case, nodes, graph, lex)
        return run_composite_semantic(
            case,
            nodes,
            graph,
            lex,
            root=root,
            lsp=lsp,
            field=index,
            mode=mode,
            extra_graph=extra_graph,
            struct_heatmap=struct_hm,
            alpha=alpha,
            tau=tau,
        )

    return _run
