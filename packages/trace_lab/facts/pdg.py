"""PDG view: compose call + data + control edges."""

from __future__ import annotations

from trace_lab.facts import TypedEdge


def compose_pdg(*edge_groups: list[TypedEdge]) -> list[TypedEdge]:
    best: dict[tuple[str, str, str], TypedEdge] = {}
    for group in edge_groups:
        for e in group:
            key = (e.source, e.target, e.relation)
            prev = best.get(key)
            if prev is None or e.weight > prev.weight:
                best[key] = e
    return list(best.values())


def out_adj(edges: list[TypedEdge]) -> dict[str, list[TypedEdge]]:
    adj: dict[str, list[TypedEdge]] = {}
    for e in edges:
        adj.setdefault(e.source, []).append(e)
    return adj
