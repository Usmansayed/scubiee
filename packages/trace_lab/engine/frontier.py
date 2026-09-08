"""Frontier adjacency from typed edges."""

from __future__ import annotations

from collections import defaultdict

from trace_lab.facts import TypedEdge


def build_frontier(edges: list[TypedEdge]) -> dict[str, list[TypedEdge]]:
    adj: dict[str, list[TypedEdge]] = defaultdict(list)
    for e in edges:
        adj[e.source].append(e)
    return dict(adj)
