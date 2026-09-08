"""Non-LLM recall belt — maximize must-recall via wide structure + embeds.

Arms:
  recall_belt  — bidirectional AST/LSP(+Graphify) island; keep ALL; hot-floor scores
  recall_fuse  — max(polytrace, recall_belt) per node (coverage ∪ precision proposer)

No LLM. Target: must-rec ≥ 0.90 on verify_hard; precision is expected lower.
"""

from __future__ import annotations

import heapq
import math
from collections import deque

from conductor.bm25_index import tokenize
from trace_lab.ast_graph import AstTraceGraph
from trace_lab.embed_field import EmbedField
from trace_lab.lsp_index import LspIndex
from trace_lab.types import GoldCase, HeatCell, Heatmap, TraceNode

FORWARD = frozenset({"calls", "uses", "contains", "dispatches", "overrides"})
BACKWARD = frozenset({"called_by", "imported_by"})
_HOT = 0.50
_MAX_HOPS = 7
_STRUCT_FLOOR = 0.06


def _channels(
    uid: str,
    graph: AstTraceGraph,
    lsp: LspIndex,
    gfy: AstTraceGraph | None,
) -> list[tuple[str, str, float]]:
    out: list[tuple[str, str, float]] = []
    seen: set[tuple[str, str]] = set()

    def add(vid: str, rel: str, w: float) -> None:
        key = (vid, rel)
        if key in seen or vid == uid:
            return
        seen.add(key)
        out.append((vid, rel, w))

    for g, prefix in ((graph, ""), (gfy, "g:")):
        if g is None:
            continue
        for vid, rel, w in g.neighbors(uid, directed=True):
            if rel in FORWARD or rel in BACKWARD or prefix:
                add(vid, f"{prefix}{rel}", w)
        # undirected pass catches rev edges graphify may only store one way
        for vid, rel, w in g.neighbors(uid, directed=False):
            add(vid, f"{prefix}{rel}", w * 0.95)

    for vid in lsp.dispatch.get(uid, []):
        add(vid, "dispatches", 0.88)
    for vid in lsp.overrides.get(uid, []):
        add(vid, "overrides", 0.75)
    for vid in lsp.used_by.get(uid, []):
        add(vid, "used_by", 0.90)
    return out


def _joint(query: str, node: TraceNode, *, dense: float, bm25: float) -> float:
    qtoks = {t for t in tokenize(query) if len(t) > 1}
    blob = f"{node.file} {node.symbol} {(node.lex_text or node.text or '')[:400]}".lower()
    ftoks = {t for t in tokenize(blob) if len(t) > 1}
    path_ov = len(qtoks & ftoks)
    short = node.symbol.split(".")[-1].lower()
    exact = 2.0 if short in qtoks else 0.0
    stem = node.file.replace("\\", "/").rsplit("/", 1)[-1].replace(".py", "").lower()
    if stem in qtoks:
        exact += 1.5
    return exact + 0.35 * path_ov + 0.12 * bm25 + 6.0 * max(dense, 0.0)


def expand_island(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lsp: LspIndex,
    field: EmbedField,
    gfy: AstTraceGraph | None,
) -> tuple[dict[str, float], dict[str, str], dict[str, tuple[str, ...]]]:
    seed = case.seed.id
    q_aff = field.affinities(case.query)
    scores: dict[str, float] = {seed: 1.0}
    why: dict[str, str] = {seed: "seed/recall"}
    paths: dict[str, tuple[str, ...]] = {seed: (seed,)}
    heap: list[tuple[float, int, str]] = [(-1.0, 0, seed)]
    seen: set[str] = set()

    while heap:
        _neg, hop, uid = heapq.heappop(heap)
        if uid in seen:
            continue
        seen.add(uid)
        if hop >= _MAX_HOPS:
            continue
        for vid, rel, weight in _channels(uid, graph, lsp, gfy):
            dst = nodes.get(vid)
            if dst is None or dst.kind == "class":
                continue
            qa = q_aff.get(vid, 0.0)
            # Loose gate: almost always expand; only skip deep near-zero affinity noise
            if hop >= 4 and qa < 0.02 and "g:" not in rel and rel not in {
                "dispatches",
                "overrides",
                "used_by",
                "calls",
                "called_by",
            }:
                continue
            incoming = scores[uid] * max(weight, 0.35) * (0.97**hop) * (0.70 + 0.30 * max(qa, 0.0))
            if incoming < _STRUCT_FLOOR:
                continue
            if incoming <= scores.get(vid, 0.0) + 1e-9:
                continue
            scores[vid] = incoming
            why[vid] = f"{rel}"
            paths[vid] = (paths.get(uid, (uid,)) + (vid,))[-12:]
            heapq.heappush(heap, (-incoming, hop + 1, vid))

    # Always take full 2-hop structural neighborhood (recall floor)
    q: deque[tuple[str, int]] = deque([(seed, 0)])
    seen2 = {seed}
    while q:
        uid, hop = q.popleft()
        if hop >= 2:
            continue
        for vid, rel, weight in _channels(uid, graph, lsp, gfy):
            if vid not in nodes or nodes[vid].kind == "class":
                continue
            scores[vid] = max(scores.get(vid, 0.0), 0.75 * max(weight, 0.4) * (0.9**hop))
            why.setdefault(vid, f"force2/{rel}")
            paths.setdefault(vid, (seed, vid) if hop == 0 else paths.get(uid, (uid,)) + (vid,))
            if vid not in seen2:
                seen2.add(vid)
                q.append((vid, hop + 1))

    return scores, why, paths


def recall_belt(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex,
    *,
    lsp: LspIndex,
    field: EmbedField,
    gfy: AstTraceGraph | None = None,
) -> Heatmap:
    """Keep entire expanded island hot — maximize must-recall."""
    scores, why, paths = expand_island(case, nodes, graph, lsp, field, gfy)
    q_aff = field.affinities(case.query)
    bm_raw = lex.bm25_scores(case.query) if lex is not None else {}
    island = set(scores)

    cells: list[HeatCell] = []
    for nid in island:
        node = nodes[nid]
        qa = q_aff.get(nid, 0.0)
        joint = _joint(case.query, node, dense=qa, bm25=bm_raw.get(nid, 0.0))
        joint_n = 1.0 - math.exp(-max(joint, 0.0) / 4.0)
        st = scores.get(nid, 0.0)
        hop = max(0, len(paths.get(nid, (nid,))) - 1)
        # Rank by semantics but everyone stays ≥ hot floor
        score = 0.35 * min(1.0, st) + 0.35 * max(0.0, qa) + 0.30 * joint_n
        score = max(score, _HOT - 0.02 * max(0, hop - 2))
        if nid == case.seed.id:
            score = 1.0
        score = max(score, _HOT)
        cells.append(
            HeatCell(
                node_id=nid,
                score=round(min(1.0, score), 4),
                why=why.get(nid, "recall"),
                path=paths.get(nid, (nid,)),
            )
        )
    cells.sort(key=lambda c: -c.score)
    return Heatmap(
        strategy="recall_belt",
        cells=cells,
        extra={"island": len(island), "backend": field.backend},
    )


def recall_fuse(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex,
    *,
    lsp: LspIndex,
    field: EmbedField,
    poly_fn,
    gfy: AstTraceGraph | None = None,
) -> Heatmap:
    """Union polytrace (precise proposer) with recall_belt island."""
    belt = recall_belt(case, nodes, graph, lex, lsp=lsp, field=field, gfy=gfy)
    poly = poly_fn(case, nodes, graph, lex)
    by: dict[str, HeatCell] = {}
    for c in belt.cells:
        by[c.node_id] = HeatCell(
            node_id=c.node_id,
            score=c.score,
            why=f"belt/{c.why}",
            path=c.path,
        )
    for c in poly.cells:
        prev = by.get(c.node_id)
        if prev is None or c.score > prev.score:
            by[c.node_id] = HeatCell(
                node_id=c.node_id,
                score=max(c.score, _HOT) if c.score >= 0.40 else c.score,
                why=f"poly/{c.why}",
                path=c.path,
            )
        else:
            # Both present: bump toward hot
            by[c.node_id] = HeatCell(
                node_id=c.node_id,
                score=max(prev.score, c.score, _HOT),
                why=f"fuse/{prev.why}",
                path=prev.path or c.path,
            )
    cells = sorted(by.values(), key=lambda c: -c.score)
    return Heatmap(
        strategy="recall_fuse",
        cells=cells,
        extra={"belt": len(belt.cells), "poly": len(poly.cells), "fused": len(cells)},
    )


def bind_recall_belt(lsp: LspIndex, field: EmbedField, gfy: AstTraceGraph | None = None):
    def _run(case, nodes, graph, lex):
        return recall_belt(case, nodes, graph, lex, lsp=lsp, field=field, gfy=gfy)

    return _run


def bind_recall_fuse(
    lsp: LspIndex,
    field: EmbedField,
    poly_fn,
    gfy: AstTraceGraph | None = None,
):
    def _run(case, nodes, graph, lex):
        return recall_fuse(
            case, nodes, graph, lex, lsp=lsp, field=field, poly_fn=poly_fn, gfy=gfy
        )

    return _run
