"""Hybrid tracers: composite / semantic fuse propose; embed keep/drop decides.

Research arms only — do not flip production default until cross-board ship gate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from trace_lab.ast_graph import AstTraceGraph
from trace_lab.embed_field import EmbedField
from trace_lab.embed_filter import BlendMode, DropMode, apply_embed_keep_drop
from trace_lab.lsp_index import LspIndex
from trace_lab.semantic_index import SemanticIndex
from trace_lab.types import GoldCase, Heatmap, TraceNode

# Exhaustive combo grid (base × drop × blend) for bakeoffs.
HYBRID_SPECS: list[tuple[str, str, DropMode, BlendMode]] = [
    # fuse + poly family (primary bet)
    ("hyb_fuse_poly", "semantic_tracer_fuse", "poly", "poly"),
    ("hyb_fuse_strict", "semantic_tracer_fuse", "strict", "poly"),
    ("hyb_fuse_mild", "semantic_tracer_fuse", "mild", "poly"),
    ("hyb_fuse_rescore", "semantic_tracer_fuse", "off", "poly"),
    ("hyb_fuse_aff", "semantic_tracer_fuse", "poly", "aff"),
    ("hyb_fuse_struct", "semantic_tracer_fuse", "poly", "struct"),
    ("hyb_fuse_strict_aff", "semantic_tracer_fuse", "strict", "aff"),
    ("hyb_fuse_mild_struct", "semantic_tracer_fuse", "mild", "struct"),
    ("hyb_fuse_balanced", "semantic_tracer_fuse", "balanced", "poly"),
    ("hyb_fuse_adaptive", "semantic_tracer_fuse", "adaptive", "poly"),
    ("hyb_fuse_demote_strict", "semantic_tracer_fuse", "demote_strict", "poly"),
    ("hyb_fuse_demote_bal", "semantic_tracer_fuse", "demote_balanced", "poly"),
    ("hyb_fuse_noise", "semantic_tracer_fuse", "noise", "poly"),
    ("hyb_fuse_demote_noise", "semantic_tracer_fuse", "demote_noise", "poly"),
    ("hyb_fuse_adaptive2", "semantic_tracer_fuse", "adaptive", "poly"),
    ("hyb_fuse_noise_plus", "semantic_tracer_fuse", "noise_plus", "poly"),
    ("hyb_fuse_demote_noise_plus", "semantic_tracer_fuse", "demote_noise_plus", "poly"),
    # composite + poly family
    ("hyb_comp_poly", "composite_v1", "poly", "poly"),
    ("hyb_comp_strict", "composite_v1", "strict", "poly"),
    ("hyb_comp_mild", "composite_v1", "mild", "poly"),
    ("hyb_comp_aff", "composite_v1", "poly", "aff"),
    ("hyb_comp_rescore", "composite_v1", "off", "aff"),
    ("hyb_comp_balanced", "composite_v1", "balanced", "poly"),
    ("hyb_comp_adaptive", "composite_v1", "adaptive", "poly"),
    ("hyb_comp_demote_strict", "composite_v1", "demote_strict", "poly"),
    ("hyb_comp_demote_noise", "composite_v1", "demote_noise", "poly"),
    ("hyb_comp_noise", "composite_v1", "noise", "poly"),
    ("hyb_comp_demote_noise_plus", "composite_v1", "demote_noise_plus", "poly"),
    # v1 comparator + poly
    ("hyb_v1_poly", "semantic_tracer_v1", "poly", "poly"),
    ("hyb_v1_strict", "semantic_tracer_v1", "strict", "poly"),
    ("hyb_v1_aff", "semantic_tracer_v1", "poly", "aff"),
    ("hyb_v1_adaptive", "semantic_tracer_v1", "adaptive", "poly"),
    ("hyb_v1_demote_strict", "semantic_tracer_v1", "demote_strict", "poly"),
    # polytrace island + alternate blends (poly_embed is poly/poly already)
    ("hyb_poly_strict", "polytrace", "strict", "poly"),
    ("hyb_poly_mild", "polytrace", "mild", "poly"),
    ("hyb_poly_aff", "polytrace", "poly", "aff"),
    ("hyb_poly_struct", "polytrace", "poly", "struct"),
    ("hyb_poly_adaptive", "polytrace", "adaptive", "poly"),
    ("hyb_poly_demote_strict", "polytrace", "demote_strict", "poly"),
    ("hyb_poly_balanced", "polytrace", "balanced", "poly"),
]


def bind_hybrid_filter(
    base_tracer: Callable,
    lsp: LspIndex,
    field: EmbedField | SemanticIndex,
    *,
    drop_mode: DropMode = "poly",
    blend_mode: BlendMode = "poly",
    strategy: str = "hyb_filter",
):
    if isinstance(field, EmbedField):
        emb = field
    elif isinstance(field, SemanticIndex):
        emb = field.field
    else:
        raise TypeError("hybrid filter needs EmbedField affinities")

    def run(case: GoldCase, nodes: dict[str, TraceNode], graph: AstTraceGraph, lex) -> Heatmap:
        base_hm = base_tracer(case, nodes, graph, lex)
        return apply_embed_keep_drop(
            case,
            nodes,
            base_hm,
            field=emb,
            lsp=lsp,
            graph=graph,
            drop_mode=drop_mode,
            blend_mode=blend_mode,
            strategy=strategy,
        )

    return run


def register_hybrid_arms(
    tracers: dict,
    root: Path,
    lsp: LspIndex,
    field: EmbedField,
    extra_graph: AstTraceGraph | None = None,
) -> None:
    """Register all HYBRID_SPECS that can resolve their base tracer."""
    # Ensure bases exist
    if "semantic_tracer_fuse" not in tracers:
        from trace_lab.semantic_tracer_fuse import bind_semantic_tracer_fuse

        tracers["semantic_tracer_fuse"] = bind_semantic_tracer_fuse(
            root, lsp, field, extra_graph=extra_graph
        )
    if "semantic_tracer_v1" not in tracers:
        from trace_lab.semantic_tracer_v1 import bind_semantic_tracer_v1

        tracers["semantic_tracer_v1"] = bind_semantic_tracer_v1(
            root, lsp, field, extra_graph=extra_graph
        )

    for name, base, drop, blend in HYBRID_SPECS:
        if base not in tracers:
            continue
        tracers[name] = bind_hybrid_filter(
            tracers[base],
            lsp,
            field,
            drop_mode=drop,
            blend_mode=blend,
            strategy=name,
        )
