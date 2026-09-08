"""Verified semantic teleport — vector proposes, structure verifies (Phase 1 spike)."""

from __future__ import annotations

from typing import Any

from trace_lab.ast_graph import AstTraceGraph
from trace_lab.lsp_index import LspIndex
from trace_lab.policy.slice_mask import demote_sinks_without_query
from trace_lab.types import HeatCell, Heatmap, TraceNode


def _linked(
    uid: str,
    vid: str,
    graph: AstTraceGraph,
    lsp: LspIndex,
    extra: AstTraceGraph | None,
) -> bool:
    """True if undirected 1-hop structural relationship exists."""
    for dst, rel, _w in graph.neighbors(uid, directed=True):
        if dst == vid and rel in {
            "calls",
            "uses",
            "contains",
            "dispatches",
            "overrides",
        }:
            return True
    for dst, rel, _w in graph.neighbors(vid, directed=True):
        if dst == uid:
            return True
    if vid in lsp.dispatch.get(uid, ()) or uid in lsp.dispatch.get(vid, ()):
        return True
    if vid in lsp.overrides.get(uid, ()) or uid in lsp.overrides.get(vid, ()):
        return True
    if extra is not None:
        for dst, _rel, _w in extra.neighbors(uid, directed=True):
            if dst == vid:
                return True
        for dst, _rel, _w in extra.neighbors(vid, directed=True):
            if dst == uid:
                return True
    return False


def apply_embed_teleport(
    heatmap: Heatmap,
    *,
    seed_id: str,
    query: str,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lsp: LspIndex,
    sem_all: dict[str, float],
    extra_graph: AstTraceGraph | None = None,
    top_k: int = 12,
    min_sem: float = 0.35,
    admit_floor: float = 0.46,
    strategy: str = "composite_embed_teleport",
    extra: dict[str, Any] | None = None,
) -> Heatmap:
    """Admit vector neighbors that touch the structural island (or seed)."""
    by = {c.node_id: HeatCell(c.node_id, c.score, c.why, c.path, c.relation) for c in heatmap.cells}
    admitted = set(by)
    if seed_id not in by:
        by[seed_id] = HeatCell(seed_id, 1.0, "seed", (seed_id,))
        admitted.add(seed_id)

    cands = sorted(sem_all.items(), key=lambda kv: -kv[1])[: max(top_k * 3, top_k)]
    teleported = 0
    for nid, sc in cands:
        if teleported >= top_k:
            break
        if nid in admitted or nid == seed_id:
            continue
        if float(sc) < min_sem:
            continue
        dst = nodes.get(nid)
        if dst is None or dst.kind == "class":
            continue
        if demote_sinks_without_query(dst, query):
            continue
        # Must link to current island (propose → verify)
        linked = any(
            _linked(a, nid, graph, lsp, extra_graph) for a in list(admitted)[:120]
        )
        if not linked:
            continue
        admit = max(admit_floor, float(sc))
        prev = by.get(nid)
        if prev is None or admit > prev.score:
            by[nid] = HeatCell(
                node_id=nid,
                score=round(min(1.0, admit), 4),
                why=f"embed_teleport+struct sem={sc:.2f}",
                path=(seed_id, nid),
            )
        admitted.add(nid)
        teleported += 1

    cells = sorted(by.values(), key=lambda c: -c.score)
    meta = dict(heatmap.extra or {})
    meta.update(extra or {})
    meta["semantic_mode"] = "embed_teleport"
    meta["teleported"] = teleported
    meta["engine"] = strategy
    return Heatmap(strategy=strategy, cells=cells, extra=meta)


def apply_strict_embed_teleport(
    heatmap: Heatmap,
    *,
    seed_id: str,
    query: str,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lsp: LspIndex,
    sem_all: dict[str, float],
    hub_penalty_fn=None,
    extra_graph: AstTraceGraph | None = None,
    top_k: int = 6,
    min_sem: float = 0.48,
    admit_floor: float = 0.46,
    strategy: str = "strict_embed_teleport",
    extra: dict[str, Any] | None = None,
) -> Heatmap:
    """Strict FN recovery: high semantic bar + structural link + hub penalty."""
    by = {c.node_id: HeatCell(c.node_id, c.score, c.why, c.path, c.relation) for c in heatmap.cells}
    admitted = set(by)
    if seed_id not in by:
        by[seed_id] = HeatCell(seed_id, 1.0, "seed", (seed_id,))
        admitted.add(seed_id)

    cands = sorted(sem_all.items(), key=lambda kv: -kv[1])[: max(top_k * 4, top_k)]
    teleported = 0
    for nid, sc in cands:
        if teleported >= top_k:
            break
        if nid in admitted or nid == seed_id:
            continue
        if float(sc) < min_sem:
            continue
        dst = nodes.get(nid)
        if dst is None or dst.kind == "class":
            continue
        if demote_sinks_without_query(dst, query):
            continue
        pen = float(hub_penalty_fn(nid)) if callable(hub_penalty_fn) else 1.0
        if pen < 0.55 and float(sc) < min_sem + 0.08:
            continue  # reject weak hub-like teleports
        linked = any(_linked(a, nid, graph, lsp, extra_graph) for a in list(admitted)[:80])
        if not linked:
            continue
        admit = max(admit_floor, float(sc) * pen)
        if admit < admit_floor:
            continue
        prev = by.get(nid)
        if prev is None or admit > prev.score:
            by[nid] = HeatCell(
                node_id=nid,
                score=round(min(1.0, admit), 4),
                why=f"strict_teleport+struct sem={sc:.2f}|hub_pen={pen:.2f}",
                path=(seed_id, nid),
            )
        admitted.add(nid)
        teleported += 1

    cells = sorted(by.values(), key=lambda c: -c.score)
    meta = dict(heatmap.extra or {})
    meta.update(extra or {})
    meta["semantic_mode"] = "strict_embed_teleport"
    meta["teleported"] = teleported
    meta["engine"] = strategy
    return Heatmap(strategy=strategy, cells=cells, extra=meta)


def apply_bm25_teleport(
    heatmap: Heatmap,
    *,
    seed_id: str,
    query: str,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lsp: LspIndex,
    lex,
    extra_graph: AstTraceGraph | None = None,
    top_k: int = 8,
    min_bm25: float = 0.40,
    admit_floor: float = 0.46,
    strategy: str = "composite_bm25_teleport",
    extra: dict[str, Any] | None = None,
) -> Heatmap:
    """BM25 propose + structural verify (lexical twin of embed teleport)."""
    from trace_lab.retrieve import normalize

    by = {c.node_id: HeatCell(c.node_id, c.score, c.why, c.path, c.relation) for c in heatmap.cells}
    admitted = set(by)
    if seed_id not in by:
        by[seed_id] = HeatCell(seed_id, 1.0, "seed", (seed_id,))
        admitted.add(seed_id)

    bm = normalize(lex.bm25_scores(query)) if lex is not None else {}
    teleported = 0
    for nid, sc in sorted(bm.items(), key=lambda kv: -kv[1])[: top_k * 3]:
        if teleported >= top_k:
            break
        if nid in admitted or float(sc) < min_bm25:
            continue
        dst = nodes.get(nid)
        if dst is None or dst.kind == "class":
            continue
        if demote_sinks_without_query(dst, query):
            continue
        linked = any(_linked(a, nid, graph, lsp, extra_graph) for a in list(admitted)[:120])
        if not linked:
            continue
        admit = max(admit_floor, 0.45 * float(sc))
        prev = by.get(nid)
        if prev is None or admit > prev.score:
            by[nid] = HeatCell(
                node_id=nid,
                score=round(min(1.0, admit), 4),
                why=f"bm25_teleport+struct bm25={sc:.2f}",
                path=(seed_id, nid),
            )
        admitted.add(nid)
        teleported += 1

    cells = sorted(by.values(), key=lambda c: -c.score)
    meta = dict(heatmap.extra or {})
    meta.update(extra or {})
    meta["semantic_mode"] = "bm25_teleport"
    meta["teleported"] = teleported
    meta["engine"] = strategy
    return Heatmap(strategy=strategy, cells=cells, extra=meta)
