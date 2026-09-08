"""Slice mask: drop excluded leaves before / during heat."""

from __future__ import annotations

import re

from conductor.bm25_index import tokenize
from trace_lab.facts import TypedEdge
from trace_lab.policy.intent import TraceSpec
from trace_lab.types import TraceNode

_SINK_DEFAULT = frozenset({"log", "logger", "track", "analytics", "print", "info", "debug"})
_SINK_QUERY_TOKENS = frozenset(
    {"log", "logger", "logging", "track", "tracking", "analytics", "telemetry", "print"}
)


def short_name(node: TraceNode) -> str:
    return node.symbol.split(".")[-1].lower()


def is_excluded(node: TraceNode, spec: TraceSpec) -> bool:
    if not spec.exclude_names:
        return False
    return short_name(node) in {n.lower() for n in spec.exclude_names}


def filter_edges(
    edges: list[TypedEdge],
    nodes: dict[str, TraceNode],
    spec: TraceSpec,
) -> list[TypedEdge]:
    if not spec.exclude_names:
        return edges
    ex = {n.lower() for n in spec.exclude_names}
    out: list[TypedEdge] = []
    for e in edges:
        dst = nodes.get(e.target)
        if dst is not None and short_name(dst) in ex:
            continue
        out.append(e)
    return out


def demote_sinks_without_query(
    node: TraceNode,
    user_query: str,
) -> bool:
    """True if node is a generic sink and query does not name it.

    Uses tokenized word match so "login" does not count as naming "log".
    """
    s = short_name(node)
    if s not in _SINK_DEFAULT:
        return False
    ql = (user_query or "").lower()
    # Negative framing ("without telemetry", "drop log") does not name sinks.
    if re.search(
        r"\b(without|no|drop|exclude|unrelated)\b.{0,40}\b(telemetry|logging|log|track|analytics)\b",
        ql,
    ) or re.search(
        r"\b(telemetry|logging|log|track|analytics)\b.{0,40}\b(noise|only|out)\b",
        ql,
    ):
        return True
    qtoks = set(tokenize(ql))
    if qtoks & _SINK_QUERY_TOKENS:
        return False
    if re.search(r"\b(with\s+telemetry|include\s+(logging|logs))\b", ql):
        return False
    return True
