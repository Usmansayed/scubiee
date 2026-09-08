"""Optional Graphify edge adapter."""

from __future__ import annotations

from trace_lab.ast_graph import AstTraceGraph
from trace_lab.facts import TypedEdge

_KEEP = frozenset({"calls", "uses", "contains", "method", "imports", "inherits"})


def edges_from_graphify(gfy: AstTraceGraph | None) -> list[TypedEdge]:
    if gfy is None:
        return []
    out: list[TypedEdge] = []
    for e in gfy.edges:
        if e.relation not in _KEEP:
            continue
        rel = {
            "calls": "CALLS",
            "uses": "USES",
            "contains": "CONTAINS",
            "method": "CONTAINS",
            "imports": "IMPORTS",
            "inherits": "OVERRIDES",
        }.get(e.relation, e.relation.upper())
        out.append(
            TypedEdge(e.source, e.target, rel, float(e.weight) * 0.95, confidence="graphify")
        )
    return out
