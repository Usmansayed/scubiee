"""Assemble heatmap cells."""

from __future__ import annotations

from trace_lab.types import HeatCell, Heatmap


def to_heatmap(
    strategy: str,
    scores: dict[str, float],
    why: dict[str, str],
    paths: dict[str, tuple[str, ...]],
    *,
    extra: dict | None = None,
) -> Heatmap:
    cells = [
        HeatCell(
            node_id=nid,
            score=round(sc, 4),
            why=why.get(nid, strategy),
            path=paths.get(nid, (nid,)),
        )
        for nid, sc in sorted(scores.items(), key=lambda kv: -kv[1])
        if sc > 0
    ]
    return Heatmap(strategy=strategy, cells=cells, extra=extra or {})
