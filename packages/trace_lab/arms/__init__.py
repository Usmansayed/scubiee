"""Switchable bakeoff arms for the semantic tracer system."""

from __future__ import annotations

from pathlib import Path

from trace_lab.ast_graph import AstTraceGraph
from trace_lab.lsp_index import LspIndex
from trace_lab.system_trace import bind_system_trace


def register_system_arms(
    root: Path,
    lsp: LspIndex,
    extra_graph: AstTraceGraph | None,
    tracers: dict,
) -> dict:
    """Add layered arms without removing polytrace."""
    root = Path(root)
    tracers["callgraph_jedi"] = bind_system_trace(
        root,
        lsp,
        extra_graph,
        with_jedi=True,
        with_dfg=False,
        with_cfg=False,
        teleport=False,
        ppr=False,
        strategy="callgraph_jedi",
    )
    tracers["dfg_slice"] = bind_system_trace(
        root,
        lsp,
        extra_graph,
        with_jedi=True,
        with_dfg=True,
        with_cfg=False,
        teleport=False,
        ppr=False,
        strategy="dfg_slice",
    )
    tracers["pdg_prio"] = bind_system_trace(
        root,
        lsp,
        extra_graph,
        with_jedi=True,
        with_dfg=True,
        with_cfg=True,
        teleport=False,
        ppr=False,
        strategy="pdg_prio",
    )
    tracers["hybrid_teleport"] = bind_system_trace(
        root,
        lsp,
        extra_graph,
        with_jedi=True,
        with_dfg=True,
        with_cfg=True,
        teleport=True,
        ppr=False,
        strategy="hybrid_teleport",
    )
    tracers["rank_default"] = bind_system_trace(
        root,
        lsp,
        extra_graph,
        with_jedi=True,
        with_dfg=True,
        with_cfg=True,
        teleport=True,
        ppr=False,
        strategy="rank_default",
    )
    tracers["rank_strict"] = bind_system_trace(
        root,
        lsp,
        extra_graph,
        with_jedi=True,
        with_dfg=True,
        with_cfg=True,
        teleport=True,
        ppr=True,
        strategy="rank_strict",
    )
    from trace_lab.composite_v1 import bind_composite_v1

    tracers["composite_v1"] = bind_composite_v1(root, lsp, extra_graph)
    # composite_semantic_* require EmbedField — registered in compile_bundle when
    # with_embed_power=True (or bind via register_composite_semantic_arms).
    return tracers


def register_composite_semantic_arms(
    root: Path,
    lsp: LspIndex,
    field,
    extra_graph: AstTraceGraph | None,
    tracers: dict,
) -> dict:
    """Register semantic sensor wrappers + semantic_tracer_v1 (needs EmbedField)."""
    from trace_lab.composite_semantic import bind_composite_semantic
    from trace_lab.semantic_tracer_v1 import bind_semantic_tracer_v1

    tracers["composite_semantic_add"] = bind_composite_semantic(
        root, lsp, field, mode="add", extra_graph=extra_graph
    )
    tracers["composite_semantic_gate"] = bind_composite_semantic(
        root, lsp, field, mode="gate", extra_graph=extra_graph
    )
    tracers["semantic_tracer_v1"] = bind_semantic_tracer_v1(
        root, lsp, field, extra_graph=extra_graph
    )
    from trace_lab.semantic_tracer_fuse import bind_semantic_tracer_fuse

    tracers["semantic_tracer_fuse"] = bind_semantic_tracer_fuse(
        root, lsp, field, extra_graph=extra_graph
    )
    return tracers
