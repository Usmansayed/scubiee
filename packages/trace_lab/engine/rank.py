"""Ranking presets: teleport, optional PPR, leaf genericness — membership already fixed."""

from __future__ import annotations

from collections import defaultdict

from conductor.bm25_index import tokenize
from trace_lab.facts import TypedEdge
from trace_lab.policy.intent import TraceSpec
from trace_lab.policy.slice_mask import demote_sinks_without_query, short_name
from trace_lab.retrieve import normalize
from trace_lab.types import TraceNode


def apply_rank_default(
    scores: dict[str, float],
    why: dict[str, str],
    paths: dict[str, tuple[str, ...]],
    nodes: dict[str, TraceNode],
    frontier: dict[str, list[TypedEdge]],
    spec: TraceSpec,
    lex,
    *,
    teleport: bool = True,
    ppr: bool = False,
) -> tuple[dict[str, float], dict[str, str], dict[str, tuple[str, ...]]]:
    scores = dict(scores)
    why = dict(why)
    paths = dict(paths)
    admitted = set(scores)

    # Soft demote sink leaves that are not deep spines
    for nid in list(scores):
        n = nodes.get(nid)
        if n is None:
            continue
        if demote_sinks_without_query(n, spec.user_query) and len(paths.get(nid, ())) <= 2:
            if scores[nid] < 0.6:
                scores[nid] *= 0.5

    if teleport and lex is not None and spec.mode in {"flow", "entry", "config"}:
        bm = normalize(lex.bm25_scores(spec.user_query))
        for nid, sc in sorted(bm.items(), key=lambda kv: -kv[1])[:8]:
            if nid in admitted or sc < 0.4:
                continue
            dst = nodes.get(nid)
            if dst is None or is_excluded_name(dst, spec):
                continue
            linked = False
            for a in list(admitted)[:100]:
                for e in frontier.get(a, []):
                    if e.target == nid:
                        linked = True
                        break
                if linked:
                    break
                for e in frontier.get(nid, []):
                    if e.target in admitted:
                        linked = True
                        break
                if linked:
                    break
            if not linked:
                continue
            if demote_sinks_without_query(dst, spec.user_query):
                continue
            admit = max(0.46, 0.45 * sc)  # keep teleported structural hits hot
            scores[nid] = max(scores.get(nid, 0.0), admit)
            why[nid] = f"teleport+struct bm25={sc:.2f}"
            seed0 = next(iter(admitted))
            paths[nid] = (seed0, nid)
            admitted.add(nid)

    if ppr and len(scores) >= 3:
        scores = _light_ppr(scores, frontier)

    # Hot contract: non-sink admitted nodes with meaningful score stay ≥ 0.45
    for nid, sc in list(scores.items()):
        n = nodes.get(nid)
        if n is None:
            continue
        if demote_sinks_without_query(n, spec.user_query):
            continue
        if sc >= 0.28:
            scores[nid] = max(sc, 0.46)

    return scores, why, paths


def is_excluded_name(node: TraceNode, spec: TraceSpec) -> bool:
    return short_name(node) in {n.lower() for n in spec.exclude_names}


def _light_ppr(
    scores: dict[str, float],
    frontier: dict[str, list[TypedEdge]],
    *,
    damping: float = 0.85,
    iters: int = 5,
) -> dict[str, float]:
    nodes = list(scores)
    nset = set(nodes)
    total = sum(max(0.0, scores[n]) for n in nodes) or 1.0
    pers = {n: max(0.0, scores[n]) / total for n in nodes}
    rank = dict(pers)
    for _ in range(iters):
        nxt = {n: (1.0 - damping) * pers[n] for n in nodes}
        for u in nodes:
            outs = [(e.target, e.weight) for e in frontier.get(u, []) if e.target in nset]
            if not outs:
                for n in nodes:
                    nxt[n] += damping * rank[u] / len(nodes)
                continue
            tw = sum(w for _v, w in outs) or 1.0
            for v, w in outs:
                nxt[v] += damping * rank[u] * (w / tw)
        rank = nxt
    out = {n: 0.7 * scores[n] + 0.3 * rank.get(n, 0.0) for n in nodes}
    seed = max(scores, key=lambda k: scores[k])
    if out.get(seed, 0) > 0:
        scale = scores[seed] / out[seed]
        out = {k: min(1.0, v * scale) for k, v in out.items()}
    return out
