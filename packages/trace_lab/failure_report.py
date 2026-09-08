"""Phase 0: FN/FP failure reports + exploration cost."""

from __future__ import annotations

from typing import Any

from trace_lab.sim import HOT_THRESHOLD
from trace_lab.types import GoldCase, Heatmap, TraceNode

FAILURE_CLASSES = (
    "intent_poison",
    "no_dfg",
    "faction_block",
    "rank_crush",
    "no_slice_mask",
    "hop_truncate",
    "missing_edge",
    "unknown",
)


def classify_miss(
    nid: str,
    *,
    gold: GoldCase,
    heatmap: Heatmap,
    hot_threshold: float = HOT_THRESHOLD,
) -> str:
    """Heuristic failure class for a missed must-node."""
    cell = next((c for c in heatmap.cells if c.node_id == nid), None)
    ql = (gold.query or "").lower()
    if "## seed code anchors" in ql and any(x in ql for x in ("token_ttl", "log(", 'log("')):
        if cell is None:
            return "intent_poison"
    if cell is not None and 0 < cell.score < hot_threshold:
        return "rank_crush"
    if any(x in ql for x in ("only care", "pricing only", "no telemetry", "without logging")):
        if cell is None:
            return "no_slice_mask"
    if cell is None:
        return "missing_edge"
    return "unknown"


def build_failure_report(
    gold: GoldCase,
    heatmap: Heatmap,
    nodes: dict[str, TraceNode],
    *,
    hot_threshold: float = HOT_THRESHOLD,
) -> dict[str, Any]:
    hot = {c.node_id for c in heatmap.cells if c.score >= hot_threshold}
    must = gold.must_ids
    must_not = gold.must_not_ids
    fn = sorted(must - hot)
    fp_forbidden = sorted(must_not & hot)
    explored = len(heatmap.cells)
    return {
        "case_id": gold.id,
        "strategy": heatmap.strategy,
        "explored_nodes": explored,
        "hot_count": len(hot),
        "must_recall": round(len(must & hot) / max(len(must), 1), 4),
        "false_negatives": [
            {
                "id": nid,
                "symbol": nodes[nid].symbol if nid in nodes else nid,
                "file": nodes[nid].file if nid in nodes else "",
                "class": classify_miss(nid, gold=gold, heatmap=heatmap, hot_threshold=hot_threshold),
                "score": next((c.score for c in heatmap.cells if c.node_id == nid), None),
            }
            for nid in fn
        ],
        "false_positives_forbidden": [
            {
                "id": nid,
                "symbol": nodes[nid].symbol if nid in nodes else nid,
                "score": next((c.score for c in heatmap.cells if c.node_id == nid), None),
            }
            for nid in fp_forbidden
        ],
    }
