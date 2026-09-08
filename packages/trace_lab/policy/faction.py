"""Faction firewall with seed-closure override."""

from __future__ import annotations

from conductor.bm25_index import tokenize
from trace_lab.polytrace import _ALLIES, faction_of
from trace_lab.types import TraceNode


def is_foreign_node(
    node: TraceNode,
    *,
    user_query: str,
    seed_file: str,
    seed_reachable: set[str] | None = None,
) -> bool:
    """Foreign unless allied, query-named plat, same file, or seed-closure reachable."""
    if seed_reachable and node.id in seed_reachable:
        return False
    nf = faction_of(node.file)
    if nf == "plat":
        qtoks = set(tokenize(user_query))
        ql = user_query.lower()
        if qtoks & {"log", "logger", "logging"}:
            return False
        if any(p in ql for p in ("print", "printing", "log output", "write log")):
            return False
        return True
    if node.file.replace("\\", "/") == seed_file.replace("\\", "/"):
        return False
    seed_fac = faction_of(seed_file)
    return nf not in _ALLIES.get(seed_fac, frozenset({seed_fac}))
