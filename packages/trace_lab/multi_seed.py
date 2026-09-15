"""Adaptive multi-seed heatmap helpers for ``run_map_context`` / pack.

Shipped as the implementation behind the 0.3.76 notes (adaptive secondary
seeds skip full poly when already on seed1's island). The call site in
``pipeline.context_trace`` imported this module before the file existed.
"""

from __future__ import annotations

import os
from typing import Any

from trace_lab.ast_graph import AstTraceGraph
from trace_lab.types import HeatCell, Heatmap


def multi_seed_adaptive_enabled() -> bool:
    """``CTX_MULTI_SEED_ADAPTIVE=0`` restores full-poly-per-seed."""
    raw = (os.environ.get("CTX_MULTI_SEED_ADAPTIVE") or "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return True


def seed_specs_from_args(
    *,
    seed_file: str = "",
    seed_symbol: str = "",
    seed_line: int = 0,
    seed2_file: str = "",
    seed2_symbol: str = "",
    seed2_line: int = 0,
    seed3_file: str = "",
    seed3_symbol: str = "",
    seed3_line: int = 0,
) -> list[dict[str, Any]]:
    """Normalize up to three seed slots into non-empty file specs."""
    slots = (
        (seed_file, seed_symbol, seed_line),
        (seed2_file, seed2_symbol, seed2_line),
        (seed3_file, seed3_symbol, seed3_line),
    )
    out: list[dict[str, Any]] = []
    for file, symbol, line in slots:
        f = str(file or "").replace("\\", "/").strip()
        if not f:
            continue
        out.append(
            {
                "file": f,
                "symbol": str(symbol or "").strip(),
                "line": int(line or 0),
            }
        )
    return out


def seed_covered_by_heatmap(heatmap: Heatmap | None, node_id: str) -> bool:
    """True when ``node_id`` already appears on the primary heatmap island."""
    if heatmap is None or not node_id:
        return False
    return node_id in heatmap.by_id()


def light_seed_heatmap(node_id: str, graph: AstTraceGraph, *, hops: int = 1) -> Heatmap:
    """Cheap hop-island around a secondary seed (no full polytrace)."""
    scores: dict[str, float] = {node_id: 1.0}
    why: dict[str, str] = {node_id: "light_seed"}
    frontier = [node_id]
    for hop in range(1, max(1, hops) + 1):
        nxt: list[str] = []
        decay = 1.0 / (hop + 1)
        for uid in frontier:
            try:
                neigh = graph.neighbors(uid, directed=False)
            except Exception:  # noqa: BLE001
                neigh = []
            for vid, rel, _w in neigh:
                if vid in scores:
                    continue
                scores[vid] = round(decay, 4)
                why[vid] = f"light_hop/{rel}"
                nxt.append(vid)
        frontier = nxt
        if not frontier:
            break
    cells = [
        HeatCell(node_id=nid, score=sc, why=why.get(nid, "light_seed"), path=(node_id, nid))
        for nid, sc in sorted(scores.items(), key=lambda kv: -kv[1])
    ]
    return Heatmap(
        strategy="light_seed",
        cells=cells,
        extra={"seed": node_id, "hops": hops},
    )


def merge_seed_heatmaps(
    maps: list[Heatmap],
    seed_ids: list[str],
    graph: AstTraceGraph | None = None,
) -> Heatmap:
    """Max-merge heatmaps; boost nodes seen on ≥2 seeds (agreement corridor)."""
    del graph  # reserved for corridor walk; callers pass it for API stability
    if not maps:
        return Heatmap(strategy="multi_seed_v1", cells=[], extra={"mode": "empty"})
    if len(maps) == 1:
        only = maps[0]
        return Heatmap(
            strategy="multi_seed_v1",
            cells=list(only.cells),
            extra={"mode": "single", "seeds": list(seed_ids), **dict(only.extra or {})},
        )

    best: dict[str, HeatCell] = {}
    hits: dict[str, int] = {}
    for hm in maps:
        seen_in_map: set[str] = set()
        for cell in hm.cells:
            nid = cell.node_id
            seen_in_map.add(nid)
            prev = best.get(nid)
            if prev is None or cell.score > prev.score:
                best[nid] = HeatCell(
                    node_id=nid,
                    score=float(cell.score),
                    why=cell.why,
                    path=tuple(cell.path) if cell.path else (nid,),
                    relation=cell.relation,
                )
        for nid in seen_in_map:
            hits[nid] = hits.get(nid, 0) + 1

    # Agreement boost: nodes on multiple seed islands rise without drowning seed1.
    for nid, n_hit in hits.items():
        if n_hit < 2:
            continue
        cell = best[nid]
        boosted = min(1.0, float(cell.score) * (1.0 + 0.15 * (n_hit - 1)))
        best[nid] = HeatCell(
            node_id=nid,
            score=round(boosted, 4),
            why=f"agree/{cell.why}" if not str(cell.why).startswith("agree/") else cell.why,
            path=cell.path,
            relation=cell.relation,
        )

    cells = sorted(best.values(), key=lambda c: -c.score)
    return Heatmap(
        strategy="multi_seed_v1",
        cells=cells,
        extra={
            "mode": "agreement_corridor",
            "seeds": list(seed_ids),
            "n_maps": len(maps),
            "agreement_n": sum(1 for n in hits.values() if n >= 2),
        },
    )
