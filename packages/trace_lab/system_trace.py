"""Composable semantic system tracer (fact layer → frontier → best-first → rank)."""

from __future__ import annotations

from pathlib import Path

from trace_lab.ast_graph import AstTraceGraph
from trace_lab.engine.best_first import best_first_expand
from trace_lab.engine.frontier import build_frontier
from trace_lab.engine.heatmap import to_heatmap
from trace_lab.engine.rank import apply_rank_default
from trace_lab.facts.call_graph import build_enriched_call_graph
from trace_lab.facts.cfg import build_cfg_edges
from trace_lab.facts.dfg import build_dfg_edges
from trace_lab.facts.graphify_adapter import edges_from_graphify
from trace_lab.facts.pdg import compose_pdg
from trace_lab.lsp_index import LspIndex
from trace_lab.policy.intent import parse_trace_spec
from trace_lab.policy.slice_mask import filter_edges
from trace_lab.types import GoldCase, Heatmap, TraceNode


def _user_query(case: GoldCase) -> str:
    """Strip seed-code enrichment blocks if present (## Seed code anchors)."""
    q = case.query or ""
    marker = "## Seed code anchors"
    if marker in q:
        q = q.split(marker, 1)[0].strip()
    # Also strip leading title-only noise after prompt
    return q.strip()


def _embed_query(case: GoldCase) -> str:
    """Query text for embedding affinities — keep seed code anchors when present.

    Intent/slice parsing stays on `_user_query` (paragraph only) so pasted chunks
    cannot poison mode detection; embeddings still see the related code.
    """
    q = (case.query or "").strip()
    return q or _user_query(case)


def run_system_trace(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex,
    *,
    root: Path,
    lsp: LspIndex,
    extra_graph: AstTraceGraph | None = None,
    with_jedi: bool = True,
    with_dfg: bool = True,
    with_cfg: bool = True,
    teleport: bool = True,
    ppr: bool = False,
    strategy: str = "system_trace",
) -> Heatmap:
    seed = case.seed.id
    if seed not in nodes:
        raise KeyError(f"seed {seed} not in corpus")

    user_q = _user_query(case)
    spec = parse_trace_spec(user_q)

    call_e = build_enriched_call_graph(
        root, nodes, graph, lsp, extra=extra_graph, with_jedi=with_jedi
    )
    groups = [call_e, edges_from_graphify(extra_graph)]
    if with_dfg:
        groups.append(build_dfg_edges(root, nodes, call_e))
    if with_cfg:
        groups.append(build_cfg_edges(root, nodes))
    edges = compose_pdg(*groups)
    edges = filter_edges(edges, nodes, spec)
    frontier = build_frontier(edges)

    scores, why, paths, _reach = best_first_expand(seed, nodes, frontier, spec)
    scores, why, paths = apply_rank_default(
        scores,
        why,
        paths,
        nodes,
        frontier,
        spec,
        lex,
        teleport=teleport,
        ppr=ppr,
    )
    return to_heatmap(
        strategy,
        scores,
        why,
        paths,
        extra={
            "mode": spec.mode,
            "excludes": sorted(spec.exclude_names),
            "n_edges": len(edges),
            "engine": "semantic_system",
        },
    )


def bind_system_trace(
    root: Path,
    lsp: LspIndex,
    extra_graph: AstTraceGraph | None = None,
    **kwargs,
):
    root = Path(root)
    cache: dict[str, object] = {}

    def _run(case, nodes, graph, lex):
        # Cache PDG edges per (root, with_jedi, with_dfg, with_cfg) across cases
        key = (
            str(root),
            bool(kwargs.get("with_jedi", True)),
            bool(kwargs.get("with_dfg", True)),
            bool(kwargs.get("with_cfg", True)),
            id(nodes),
        )
        if key not in cache:
            call_e = build_enriched_call_graph(
                root,
                nodes,
                graph,
                lsp,
                extra=extra_graph,
                with_jedi=bool(kwargs.get("with_jedi", True)),
            )
            groups = [call_e, edges_from_graphify(extra_graph)]
            if kwargs.get("with_dfg", True):
                groups.append(build_dfg_edges(root, nodes, call_e))
            if kwargs.get("with_cfg", True):
                groups.append(build_cfg_edges(root, nodes))
            cache[key] = compose_pdg(*groups)

        edges = cache[key]  # type: ignore[assignment]
        seed = case.seed.id
        if seed not in nodes:
            raise KeyError(f"seed {seed} not in corpus")
        user_q = _user_query(case)
        spec = parse_trace_spec(user_q)
        from trace_lab.policy.slice_mask import filter_edges

        edged = filter_edges(list(edges), nodes, spec)  # type: ignore[arg-type]
        frontier = build_frontier(edged)
        scores, why, paths, _reach = best_first_expand(seed, nodes, frontier, spec)
        scores, why, paths = apply_rank_default(
            scores,
            why,
            paths,
            nodes,
            frontier,
            spec,
            lex,
            teleport=bool(kwargs.get("teleport", True)),
            ppr=bool(kwargs.get("ppr", False)),
        )
        return to_heatmap(
            str(kwargs.get("strategy") or "system_trace"),
            scores,
            why,
            paths,
            extra={
                "mode": spec.mode,
                "excludes": sorted(spec.exclude_names),
                "n_edges": len(edged),
                "engine": "semantic_system",
            },
        )

    return _run
