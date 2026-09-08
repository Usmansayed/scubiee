"""Comparator-guided best-first with optional trace-centroid refresh + info-gain stop."""

from __future__ import annotations

import heapq
from collections import defaultdict
from typing import Protocol

from trace_lab.engine.best_first import _MODE_WEIGHT
from trace_lab.facts import TypedEdge
from trace_lab.policy.faction import is_foreign_node
from trace_lab.policy.intent import TraceSpec
from trace_lab.policy.slice_mask import demote_sinks_without_query, is_excluded
from trace_lab.types import TraceNode

STRUCT_SEM_BETA = 0.35


class EdgeComparator(Protocol):
    def edge_sim(self, src_id: str, rel: str, dst_id: str) -> float: ...

    def node_sim(self, nid: str) -> float: ...

    def path_sim(self, path: tuple[str, ...]) -> float: ...


class TraceAwareComparator(EdgeComparator, Protocol):
    def refresh_trace(self, scores: dict[str, float], *, top_k: int = 6, min_score: float = 0.35) -> None: ...

    def information_gain(self, nid: str, admitted: set[str]) -> float: ...


def semantic_best_first_expand(
    seed_id: str,
    nodes: dict[str, TraceNode],
    frontier: dict[str, list[TypedEdge]],
    spec: TraceSpec,
    cmp: EdgeComparator,
    *,
    floor: float = 0.12,
    hop_decay: float = 0.97,
    beta: float = STRUCT_SEM_BETA,
    refresh_every: int = 0,
    info_gain_stop: bool = False,
    info_gain_min: float = 0.12,
    max_expansions: int = 0,
) -> tuple[dict[str, float], dict[str, str], dict[str, tuple[str, ...]], set[str]]:
    """Best-first where semantic edge compare modulates expansion priority.

    Membership is still the frontier (legal edges only). Embeddings never invent hops.

    refresh_every > 0: refresh trace centroid on cmp every N admits (Cycle 2).
    info_gain_stop: skip admits with very low information_gain (Cycle 3 lite).
    """
    seed = nodes[seed_id]
    seed_file = seed.file
    scores = {seed_id: 1.0}
    why = {seed_id: f"seed/{spec.mode}|sem"}
    paths: dict[str, tuple[str, ...]] = {seed_id: (seed_id,)}
    reachable: set[str] = {seed_id}
    path_hits: dict[str, int] = defaultdict(lambda: 0)
    path_hits[seed_id] = 1

    heap: list[tuple[float, int, str]] = [(-1.0, 0, seed_id)]
    seen: set[str] = set()
    boosts = _MODE_WEIGHT.get(spec.mode, _MODE_WEIGHT["flow"])
    b0 = float(beta)
    b1 = 1.0 - b0
    admits_since_refresh = 0
    expansions = 0
    refresh = getattr(cmp, "refresh_trace", None)
    info_gain = getattr(cmp, "information_gain", None)

    while heap:
        _neg, hop, uid = heapq.heappop(heap)
        if uid in seen:
            continue
        seen.add(uid)
        expansions += 1
        if max_expansions and expansions > max_expansions:
            break
        if hop >= spec.hop_cap:
            continue
        for e in frontier.get(uid, []):
            dst = nodes.get(e.target)
            if dst is None:
                continue
            if is_excluded(dst, spec):
                continue
            if is_foreign_node(
                dst,
                user_query=spec.user_query,
                seed_file=seed_file,
                seed_reachable=reachable,
            ):
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
            struct_in = scores[uid] * w * (hop_decay**hop)
            if struct_in < floor:
                continue
            if info_gain_stop and callable(info_gain):
                ig = float(info_gain(e.target, reachable))
                if ig < info_gain_min and e.target != seed_id:
                    continue
            edge_sem = float(cmp.edge_sim(uid, e.relation, e.target))
            priority = struct_in * (b0 + b1 * edge_sem)
            if priority < floor * 0.25:
                continue
            if e.target in scores and struct_in <= scores[e.target] + 1e-9:
                path_hits[e.target] += 1
                scores[e.target] = min(1.0, scores[e.target] + struct_in * 0.2)
                continue
            if struct_in <= scores.get(e.target, 0.0) + 1e-9:
                continue
            scores[e.target] = struct_in * (0.90 + 0.10 * edge_sem)
            path_hits[e.target] = max(1, path_hits[e.target])
            why[e.target] = (
                f"{e.relation}:{e.confidence} {nodes[uid].symbol}->{dst.symbol}"
                f"|sem_edge={edge_sem:.2f}"
            )
            paths[e.target] = (paths.get(uid, (uid,)) + (e.target,))[-8:]
            reachable.add(e.target)
            heapq.heappush(heap, (-priority, hop + 1, e.target))
            admits_since_refresh += 1
            if (
                refresh_every > 0
                and callable(refresh)
                and admits_since_refresh >= refresh_every
            ):
                refresh(scores, top_k=6, min_score=0.35)
                admits_since_refresh = 0

    for nid, sc in list(scores.items()):
        if path_hits[nid] > 1:
            scores[nid] = min(1.0, sc * (1.0 + 0.05 * (path_hits[nid] - 1)))

    for nid, path in list(paths.items()):
        if nid == seed_id:
            continue
        ps = float(cmp.path_sim(path))
        scores[nid] = min(1.0, float(scores[nid]) * (0.95 + 0.05 * ps))
        if "sem_path" not in why.get(nid, ""):
            why[nid] = f"{why.get(nid, '')}|sem_path={ps:.2f}".strip("|")

    return scores, why, paths, reachable
