"""Relevance-aware graph walk: decay, hub penalty, multi-path, query mix."""

from __future__ import annotations

import heapq
from dataclasses import dataclass

from trace_lab.ast_graph import AstTraceGraph
from trace_lab.retrieve import query_mix_for, query_similarity
from trace_lab.types import HeatCell, Heatmap, TraceNode

INFRA_PATH_MARKERS = (
    "/logger.py",
    "/analytics/",
    "/billing/",
    "/http/",
    "/health.py",
    "/session.py",
)

_REVERSE_REL = frozenset({"called_by", "imported_by"})


@dataclass
class PropagatePolicy:
    max_hops: int = 5
    floor: float = 0.12
    hop_decay: float = 0.82
    infra_penalty: float = 0.14
    query_mix: float | None = None
    hub_degree: int = 5
    hub_penalty: float = 0.28
    directed: bool = True
    multi_path: float = 0.45
    strategy_name: str = "ast_propagate"


def is_infra(node: TraceNode, query: str) -> bool:
    path = "/" + node.file.replace("\\", "/")
    if not any(m in path for m in INFRA_PATH_MARKERS):
        return False
    # Query-conditioned: "log output" should keep logger.
    ql = query.lower()
    if "log" in ql and path.endswith("/logger.py"):
        return False
    return True


def propagate(
    graph: AstTraceGraph,
    seed_scores: dict[str, float],
    query: str,
    *,
    policy: PropagatePolicy | None = None,
    why0: dict[str, str] | None = None,
) -> Heatmap:
    pol = policy or PropagatePolicy()
    mix = query_mix_for(query) if pol.query_mix is None else pol.query_mix
    scores = {k: float(v) for k, v in seed_scores.items() if v > 0}
    why = dict(why0 or {})
    paths: dict[str, tuple[str, ...]] = {k: (k,) for k in scores}
    hops = {k: 0 for k in scores}
    heap: list[tuple[float, int, str]] = [(-sc, 0, nid) for nid, sc in scores.items()]
    heapq.heapify(heap)
    expanded: set[str] = set()

    while heap:
        neg, hop, uid = heapq.heappop(heap)
        best = scores.get(uid, 0.0)
        if -neg < best - 1e-9:
            continue
        if uid in expanded:
            continue
        expanded.add(uid)
        if hop >= pol.max_hops:
            continue
        u_node = graph.nodes.get(uid)
        u_is_hub = graph.degree.get(uid, 0) >= pol.hub_degree
        for vid, rel, weight in graph.neighbors(uid, directed=pol.directed):
            if vid == uid or vid in paths.get(uid, ()):
                continue
            if rel in _REVERSE_REL and u_is_hub:
                continue
            if rel.startswith("rev:") and u_is_hub:
                continue
            vnode = graph.nodes.get(vid)
            if vnode is None:
                continue
            incoming = best * weight * (pol.hop_decay**hop)
            qsim = query_similarity(query, vnode)
            incoming *= (1.0 - mix) + mix * qsim
            if is_infra(vnode, query):
                incoming *= pol.infra_penalty
                if graph.degree.get(vid, 0) >= pol.hub_degree:
                    incoming *= pol.hub_penalty
            if incoming < pol.floor:
                continue
            if vid in expanded:
                scores[vid] = min(1.0, scores[vid] + incoming * pol.multi_path * 0.2)
                continue
            if incoming <= scores.get(vid, 0.0) + 1e-9:
                continue
            scores[vid] = incoming
            hops[vid] = hop + 1
            src_sym = u_node.symbol if u_node is not None else uid
            why[vid] = f"{rel} from {src_sym}"
            paths[vid] = (paths.get(uid, (uid,)) + (vid,))[-8:]
            heapq.heappush(heap, (-incoming, hop + 1, vid))

    cells = [
        HeatCell(
            node_id=nid,
            score=round(sc, 4),
            why=why.get(nid, "propagated"),
            path=paths.get(nid, (nid,)),
        )
        for nid, sc in scores.items()
    ]
    cells.sort(key=lambda c: -c.score)
    return Heatmap(
        strategy=pol.strategy_name,
        cells=cells,
        extra={"hops": hops, "query_mix": mix},
    )
