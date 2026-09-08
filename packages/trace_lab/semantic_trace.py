"""SemanticTrace — structure proposes, embeddings decide (no faction/intent tables).
Pipeline:
  1) Bidirectional AST+LSP expansion from seed (topology only)
  2) CodeRank affinities to query + seed centroid
  3) Contrastive residual vs island mean (drop semantic outliers)
  4) Lexical+dense joint score (cross-encoder stand-in) for ranking
  5) Keep bridges on paths between seed and high-affinity anchors
No path factions, no keyword intent hop caps, no symbol allowlists.
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
_HOT_FLOOR = 0.48
_MAX_HOPS = 6
_STRUCT_FLOOR = 0.10
def _channels(uid: str, graph: AstTraceGraph, lsp: LspIndex) -> list[tuple[str, str, float]]:
    out: list[tuple[str, str, float]] = []
    seen: set[tuple[str, str]] = set()
    def add(vid: str, rel: str, w: float) -> None:
        key = (vid, rel)
        if key in seen or vid == uid:
            return
        seen.add(key)
        out.append((vid, rel, w))
    for vid, rel, w in graph.neighbors(uid, directed=True):
        if rel in FORWARD or rel in BACKWARD:
            add(vid, rel, w)
    for vid in lsp.dispatch.get(uid, []):
        add(vid, "dispatches", 0.88)
    for vid in lsp.overrides.get(uid, []):
        add(vid, "overrides", 0.75)
    for vid in lsp.used_by.get(uid, []):
        add(vid, "used_by", 0.90)
    # defs of same short name are weak; skip — too noisy
    return out
def _joint_rerank(
    query: str,
    nid: str,
    node: TraceNode,
    *,
    dense: float,
    bm25: float,
) -> float:
    """Cross-encoder stand-in: joint lexical overlap + dense (Conductor D-style)."""
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
def _bfs_path(
    graph: AstTraceGraph,
    lsp: LspIndex,
    island: set[str],
    start: str,
    goal: str,
) -> list[str] | None:
    if start not in island or goal not in island:
        return None
    parent = {start: start}
    q = deque([start])
    while q:
        u = q.popleft()
        if u == goal:
            break
        for v, rel, _w in _channels(u, graph, lsp):
            if v not in island or v in parent:
                continue
            parent[v] = u
            q.append(v)
    if goal not in parent:
        return None
    path = [goal]
    while path[-1] != start:
        path.append(parent[path[-1]])
    path.reverse()
    return path
def semantic_trace(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex,
    *,
    lsp: LspIndex,
    field: EmbedField,
) -> Heatmap:
    seed = case.seed.id
    if seed not in nodes:
        raise KeyError(seed)
    q_aff = field.affinities(case.query)
    seed_vec = field.vec(seed)
    # Seed-local centroid: seed + direct neighbors' mean (semantic neighborhood)
    nbr_ids = [v for v, _r, _w in _channels(seed, graph, lsp) if v in field._by_id]
    if nbr_ids:
        import numpy as np
        m = field.vec(seed).copy()
        for nid in nbr_ids[:12]:
            m = m + field.vec(nid)
        m = m / (1 + min(len(nbr_ids), 12))
        nrm = float(np.linalg.norm(m)) or 1.0
        seed_centroid = m / nrm
    else:
        seed_centroid = seed_vec
    def seed_aff(nid: str) -> float:
        return float(field.vec(nid) @ seed_centroid)
    # --- 1) Structure propose (affinity-gated BFS, no factions) ---
    scores: dict[str, float] = {seed: 1.0}
    why: dict[str, str] = {seed: "seed/semantic"}
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
        src = nodes.get(uid)
        if src is None:
            continue
        for vid, rel, weight in _channels(uid, graph, lsp):
            dst = nodes.get(vid)
            if dst is None or dst.kind == "class":
                continue
            # Affinity gate: always allow hop0→1; deeper needs semantic support
            qa = q_aff.get(vid, 0.0)
            sa = seed_aff(vid)
            gate = 0.35 * qa + 0.65 * max(sa, 0.0)
            if hop >= 1 and gate < 0.08 and rel not in {"dispatches", "overrides", "used_by"}:
                # still allow strong structural forward calls one more hop if parent is hot
                if scores[uid] < 0.55 or hop >= 3:
                    continue
            incoming = scores[uid] * weight * (0.96**hop) * (0.55 + 0.45 * max(gate, 0.0))
            if incoming < _STRUCT_FLOOR:
                continue
            if incoming <= scores.get(vid, 0.0) + 1e-9:
                continue
            scores[vid] = incoming
            why[vid] = f"{rel} {src.symbol}->{dst.symbol}"
            paths[vid] = (paths.get(uid, (uid,)) + (vid,))[-10:]
            heapq.heappush(heap, (-incoming, hop + 1, vid))
    island = set(scores.keys())
    if len(island) < 2:
        # Fallback: 1-hop structural regardless of affinity
        for vid, rel, weight in _channels(seed, graph, lsp):
            if vid in nodes and nodes[vid].kind != "class":
                scores[vid] = max(scores.get(vid, 0.0), 0.7 * weight)
                why[vid] = f"{rel}-fallback"
                paths[vid] = (seed, vid)
                island.add(vid)
    # --- 2) Semantic anchors + contrastive residual prune ---
    aff_vals = [q_aff.get(n, 0.0) for n in island] or [0.0]
    peak = max(aff_vals) or 1e-6
    mean_aff = sum(aff_vals) / len(aff_vals)
    # Top anchors by query affinity (semantic focus of the prompt)
    ranked_by_aff = sorted(island, key=lambda n: q_aff.get(n, 0.0), reverse=True)
    n_anchor = max(3, min(8, len(island) // 3 + 1))
    anchors = {nid for nid in ranked_by_aff[:n_anchor] if nodes[nid].kind != "class"}
    anchors.add(seed)
    # Also relative floor
    for nid in island:
        if q_aff.get(nid, 0.0) >= peak * 0.55 and nodes[nid].kind != "class":
            anchors.add(nid)

    # Negative centroid: mean of lowest-affinity island members (contrast)
    import numpy as np

    low = ranked_by_aff[-max(2, len(island) // 4) :] if len(island) >= 4 else []
    if low:
        neg = np.mean(np.stack([field.vec(n) for n in low], axis=0), axis=0)
        neg = neg / (float(np.linalg.norm(neg)) or 1.0)
    else:
        neg = None

    def toward_goal(nid: str) -> float:
        qa = q_aff.get(nid, 0.0)
        if neg is None:
            return qa - mean_aff
        neg_cos = float(field.vec(nid) @ neg)
        return qa - neg_cos

    # Bridge set: paths seed → anchors inside island
    bridge: set[str] = set()
    for a in anchors:
        path = _bfs_path(graph, lsp, island, seed, a)
        if path:
            bridge.update(path)
        bridge.update(p for p in paths.get(a, ()) if p in island)

    keep: set[str] = {seed}
    for nid in island:
        qa = q_aff.get(nid, 0.0)
        hop = max(0, len(paths.get(nid, (nid,))) - 1)
        goal = toward_goal(nid)
        if hop <= 1:
            keep.add(nid)
            continue
        if nid in anchors or nid in bridge:
            keep.add(nid)
            continue
        # Deeper nodes need clear semantic pull toward the query goal
        if hop == 2 and goal >= -0.02 and qa >= peak * 0.30:
            keep.add(nid)
            continue
        if hop >= 3 and goal >= 0.02 and qa >= peak * 0.40:
            keep.add(nid)

    for u in list(keep):
        for v in lsp.dispatch.get(u, []):
            if v in island:
                keep.add(v)
                keep.update(p for p in paths.get(v, ()) if p in island)
        for v in lsp.overrides.get(u, []):
            if v in island:
                keep.add(v)
    keep.add(seed)

    # --- 3) BM25 on island for joint rerank ---
    bm_raw = lex.bm25_scores(case.query) if lex is not None else {}
    bm_max = max((bm_raw.get(n, 0.0) for n in keep), default=1.0) or 1.0
    qa_list = [q_aff.get(n, 0.0) for n in keep] or [0.0]
    qa_min, qa_max = min(qa_list), max(qa_list)
    qa_span = max(qa_max - qa_min, 1e-6)
    st_list = [scores.get(n, 0.0) for n in keep] or [0.0]
    st_max = max(st_list) or 1.0

    cells: list[HeatCell] = []
    for nid in keep:
        node = nodes[nid]
        qa = q_aff.get(nid, 0.0)
        qa_n = (qa - qa_min) / qa_span
        st_n = scores.get(nid, 0.0) / st_max
        sa_n = max(0.0, min(1.0, (seed_aff(nid) + 1.0) / 2.0))
        joint = _joint_rerank(case.query, nid, node, dense=qa, bm25=bm_raw.get(nid, 0.0))
        joint_n = 1.0 - math.exp(-max(joint, 0.0) / 4.0)
        hop = max(0, len(paths.get(nid, (nid,))) - 1)
        goal = toward_goal(nid)
        if hop <= 1:
            score = 0.55 * st_n + 0.20 * qa_n + 0.15 * joint_n + 0.10 * sa_n
        elif nid in anchors or nid in bridge:
            score = 0.30 * st_n + 0.35 * qa_n + 0.25 * joint_n + 0.10 * sa_n
        else:
            score = 0.15 * st_n + 0.45 * qa_n + 0.30 * joint_n + 0.10 * sa_n
        if nid == seed:
            score = 1.0
        else:
            # Hot floor only for bridges/near/anchors that lean toward the goal
            if (hop <= 1 or nid in bridge or nid in anchors) and goal >= -0.05:
                score = max(score, _HOT_FLOOR)
            # Precision: demote goal-opposing nodes below hot
            if goal < -0.04 and nid not in anchors and hop >= 2:
                score = min(score, 0.42)
            if goal < -0.08 and hop >= 1 and nid not in bridge:
                score = min(score, 0.40)
        w = why.get(nid, "semantic")
        if nid in anchors and nid != seed:
            w = f"sem-anchor a={qa:.3f} g={goal:.3f}"
        elif nid in bridge and nid != seed:
            w = f"sem-bridge/{w}"
        cells.append(
            HeatCell(
                node_id=nid,
                score=round(min(1.0, score), 4),
                why=w,
                path=paths.get(nid, (nid,)),
            )
        )
    cells.sort(key=lambda c: -c.score)
    return Heatmap(
        strategy="semantic_trace",
        cells=cells,
        extra={
            "backend": field.backend,
            "island": len(island),
            "kept": len(keep),
            "anchors": sorted(anchors),
            "peak_aff": round(peak, 4),
            "mean_aff": round(mean_aff, 4),
        },
    )


def bind_semantic_trace(lsp: LspIndex, field: EmbedField):
    def _run(case, nodes, graph, lex):
        return semantic_trace(case, nodes, graph, lex, lsp=lsp, field=field)

    return _run

