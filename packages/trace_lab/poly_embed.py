"""PolyEmbed — structure proposes; embeddings keep/drop + rescore.

Thin wrapper over poly_trace + apply_embed_keep_drop (shared with hybrids).
"""

from __future__ import annotations

from trace_lab.ast_graph import AstTraceGraph
from trace_lab.embed_field import EmbedField
from trace_lab.embed_filter import apply_embed_keep_drop
from trace_lab.lsp_index import LspIndex
from trace_lab.polytrace import poly_trace
from trace_lab.types import GoldCase, Heatmap, TraceNode


def poly_embed_trace(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex,
    *,
    lsp: LspIndex,
    field: EmbedField,
    struct_heatmap: Heatmap | None = None,
) -> Heatmap:
    if struct_heatmap is None:
        struct_heatmap = poly_trace(
            case, nodes, graph, lex, lsp=lsp, extra_graph=None
        )
    return apply_embed_keep_drop(
        case,
        nodes,
        struct_heatmap,
        field=field,
        lsp=lsp,
        graph=graph,
        drop_mode="poly",
        blend_mode="poly",
        strategy="poly_embed",
    )


def bind_poly_embed(lsp: LspIndex, field: EmbedField):
    def poly_embed(case, nodes, graph, lex):
        return poly_embed_trace(case, nodes, graph, lex, lsp=lsp, field=field)

    return poly_embed
