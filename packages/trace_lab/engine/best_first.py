"""Best-first expansion over typed frontier edges."""

from __future__ import annotations

import heapq
from collections import defaultdict

from trace_lab.facts import TypedEdge
from trace_lab.policy.faction import is_foreign_node
from trace_lab.policy.intent import TraceSpec
from trace_lab.policy.slice_mask import demote_sinks_without_query, is_excluded
from trace_lab.types import TraceNode

_MODE_WEIGHT = {
    "flow": {
        "PASSES_DATA_TO": 1.15,
        "PRODUCES": 1.05,
        "CONSUMES": 1.05,
        "READS": 1.0,
        "CALLS": 1.0,
        "calls": 1.0,
        "USES": 0.95,
        "uses": 0.95,
        "CONTROLS": 0.9,
        "DISPATCHES": 1.0,
        "CONTAINS": 0.7,
    },
    "config": {
        "USES": 1.15,
        "uses": 1.15,
        "CALLS": 0.85,
        "calls": 0.85,
        "PASSES_DATA_TO": 0.8,
    },
    "refs": {"CALLED_BY": 1.2, "called_by": 1.2, "USES": 0.5},
    "entry": {"CALLS": 1.08, "DISPATCHES": 1.1, "PASSES_DATA_TO": 1.05},
    "site": {"CALLS": 0.7, "PASSES_DATA_TO": 0.5},
}


def best_first_expand(
    seed_id: str,
    nodes: dict[str, TraceNode],
    frontier: dict[str, list[TypedEdge]],
    spec: TraceSpec,
    *,
    floor: float = 0.12,
    hop_decay: float = 0.97,
) -> tuple[dict[str, float], dict[str, str], dict[str, tuple[str, ...]], set[str]]:
    seed = nodes[seed_id]
    seed_file = seed.file
    scores = {seed_id: 1.0}
    why = {seed_id: f"seed/{spec.mode}"}
    paths: dict[str, tuple[str, ...]] = {seed_id: (seed_id,)}
    reachable: set[str] = {seed_id}
    path_hits: dict[str, int] = defaultdict(lambda: 0)
    path_hits[seed_id] = 1

    heap: list[tuple[float, int, str]] = [(-1.0, 0, seed_id)]
    seen: set[str] = set()
    boosts = _MODE_WEIGHT.get(spec.mode, _MODE_WEIGHT["flow"])

    while heap:
        _neg, hop, uid = heapq.heappop(heap)
        if uid in seen:
            continue
        seen.add(uid)
        if hop >= spec.hop_cap:
            continue
        for e in frontier.get(uid, []):
            dst = nodes.get(e.target)
            if dst is None:
                continue
            if is_excluded(dst, spec):
                continue
            # Seed-closure: tentatively allow if we will mark reachable after admit
            if is_foreign_node(
                dst,
                user_query=spec.user_query,
                seed_file=seed_file,
                seed_reachable=reachable,
            ):
                # Allow one hop into infra if CALL/DATA from already-reachable
                if e.relation not in {
                    "CALLS",
                    "calls",
                    "PASSES_DATA_TO",
                    "PRODUCES",
                    "CONSUMES",
                    "DISPATCHES",
                }:
                    continue
            w = float(e.weight) * float(boosts.get(e.relation, 1.0))
            if demote_sinks_without_query(dst, spec.user_query):
                w *= 0.25
            incoming = scores[uid] * w * (hop_decay**hop)
            if incoming < floor:
                continue
            if e.target in scores and incoming <= scores[e.target] + 1e-9:
                # path reinforce
                path_hits[e.target] += 1
                scores[e.target] = min(1.0, scores[e.target] + incoming * 0.2)
                continue
            if incoming <= scores.get(e.target, 0.0) + 1e-9:
                continue
            scores[e.target] = incoming
            path_hits[e.target] = max(1, path_hits[e.target])
            why[e.target] = f"{e.relation}:{e.confidence} {nodes[uid].symbol}->{dst.symbol}"
            paths[e.target] = (paths.get(uid, (uid,)) + (e.target,))[-8:]
            reachable.add(e.target)
            heapq.heappush(heap, (-incoming, hop + 1, e.target))

    # Keep spine scores hot: boost high data-weight path nodes
    for nid, sc in list(scores.items()):
        if path_hits[nid] > 1:
            scores[nid] = min(1.0, sc * (1.0 + 0.05 * (path_hits[nid] - 1)))
    return scores, why, paths, reachable
