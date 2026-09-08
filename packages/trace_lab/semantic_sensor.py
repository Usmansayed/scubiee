"""Semantic sensor for composite_v1 — Phase 0 rank-only fusion.

Embeddings rescore admitted structural nodes. They do not invent membership.
"""

from __future__ import annotations

from typing import Any

from trace_lab.types import HeatCell, Heatmap

W_QUERY = 0.6
W_SEED = 0.4
ALPHA_DEFAULT = 0.15
TAU_DEFAULT = 0.25
SEM_GATE_FACTOR = 0.35
SPINE_STRUCT_FLOOR = 0.45


def blend_sem(
    q_sim: float,
    s_sim: float,
    *,
    w_query: float = W_QUERY,
    w_seed: float = W_SEED,
) -> float:
    """Weighted query/seed similarity in [0, 1] (affinities assumed already ~[0,1])."""
    return float(w_query) * float(q_sim) + float(w_seed) * float(s_sim)


def node_sem_scores(
    node_ids: list[str],
    *,
    q_aff: dict[str, float],
    seed_id: str,
    seed_aff: dict[str, float] | None = None,
    w_query: float = W_QUERY,
    w_seed: float = W_SEED,
) -> dict[str, float]:
    """Per-node blended semantic score.

    ``seed_aff`` is cos(seed_vec, node). If omitted, use pair with seed via
    q_aff-style map keyed the same way (caller supplies pair cosines).
    """
    seed_aff = seed_aff or {}
    out: dict[str, float] = {}
    for nid in node_ids:
        q = float(q_aff.get(nid, 0.0))
        s = float(seed_aff.get(nid, 1.0 if nid == seed_id else 0.0))
        out[nid] = blend_sem(q, s, w_query=w_query, w_seed=w_seed)
    return out


def is_spine_protected(cell: HeatCell, *, seed_id: str) -> bool:
    if cell.node_id == seed_id:
        return True
    why = (cell.why or "").lower()
    if "dfg_boost" in why:
        return True
    path = cell.path or (cell.node_id,)
    if len(path) >= 2 and float(cell.score) >= SPINE_STRUCT_FLOOR:
        return True
    return False


def _tag(why: str, tag: str) -> str:
    why = (why or "").strip("|")
    if tag in why:
        return why
    return f"{why}|{tag}".strip("|")


def apply_additive(
    heatmap: Heatmap,
    sem: dict[str, float],
    *,
    alpha: float = ALPHA_DEFAULT,
    strategy: str = "composite_semantic_add",
    extra: dict[str, Any] | None = None,
) -> Heatmap:
    """score' = min(1, struct + alpha * sem). Same membership."""
    cells: list[HeatCell] = []
    for c in heatmap.cells:
        s = float(sem.get(c.node_id, 0.0))
        new_sc = min(1.0, float(c.score) + alpha * s)
        cells.append(
            HeatCell(
                node_id=c.node_id,
                score=round(new_sc, 4),
                why=_tag(c.why, "sem_add"),
                path=c.path,
                relation=c.relation,
            )
        )
    cells.sort(key=lambda x: -x.score)
    meta = dict(heatmap.extra or {})
    meta.update(extra or {})
    meta["semantic_mode"] = "add"
    meta["alpha"] = alpha
    meta["engine"] = strategy
    return Heatmap(strategy=strategy, cells=cells, extra=meta)


def apply_vector_only(
    *,
    seed_id: str,
    sem: dict[str, float],
    k: int = 24,
    strategy: str = "vector_only",
    extra: dict[str, Any] | None = None,
) -> Heatmap:
    """Research baseline: heatmap from semantic scores alone (no graph membership)."""
    ranked = sorted(sem.items(), key=lambda kv: -kv[1])[: max(1, k)]
    cells: list[HeatCell] = []
    for nid, sc in ranked:
        if sc <= 0 and nid != seed_id:
            continue
        score = 1.0 if nid == seed_id else min(1.0, max(0.0, float(sc)))
        cells.append(
            HeatCell(
                node_id=nid,
                score=round(score, 4),
                why="vector_only|seed" if nid == seed_id else "vector_only",
                path=(seed_id, nid) if nid != seed_id else (seed_id,),
            )
        )
    if seed_id not in {c.node_id for c in cells}:
        cells.insert(
            0,
            HeatCell(node_id=seed_id, score=1.0, why="vector_only|seed", path=(seed_id,)),
        )
    cells.sort(key=lambda x: -x.score)
    meta = dict(extra or {})
    meta["semantic_mode"] = "vector_only"
    meta["engine"] = strategy
    return Heatmap(strategy=strategy, cells=cells, extra=meta)


def apply_add_then_gate(
    heatmap: Heatmap,
    sem: dict[str, float],
    *,
    alpha: float = ALPHA_DEFAULT,
    tau: float = TAU_DEFAULT,
    factor: float = SEM_GATE_FACTOR,
    seed_id: str,
    strategy: str = "composite_semantic_add_gate",
    extra: dict[str, Any] | None = None,
) -> Heatmap:
    """Combo: additive boost then semantic gate on the boosted scores."""
    boosted = apply_additive(heatmap, sem, alpha=alpha, strategy="tmp_add")
    out = apply_gate(
        boosted,
        sem,
        tau=tau,
        factor=factor,
        seed_id=seed_id,
        strategy=strategy,
        extra=extra,
    )
    meta = dict(out.extra or {})
    meta["semantic_mode"] = "add_gate"
    meta["alpha"] = alpha
    meta["tau"] = tau
    return Heatmap(strategy=strategy, cells=out.cells, extra=meta)


def apply_gate(
    heatmap: Heatmap,
    sem: dict[str, float],
    *,
    tau: float = TAU_DEFAULT,
    factor: float = SEM_GATE_FACTOR,
    seed_id: str,
    strategy: str = "composite_semantic_gate",
    extra: dict[str, Any] | None = None,
) -> Heatmap:
    """Demote low-sem non-spine nodes; never demote seed / DFG spine."""
    cells: list[HeatCell] = []
    for c in heatmap.cells:
        s = float(sem.get(c.node_id, 0.0))
        if is_spine_protected(c, seed_id=seed_id) or s >= tau:
            cells.append(
                HeatCell(
                    node_id=c.node_id,
                    score=round(float(c.score), 4),
                    why=c.why,
                    path=c.path,
                    relation=c.relation,
                )
            )
            continue
        new_sc = float(c.score) * factor
        cells.append(
            HeatCell(
                node_id=c.node_id,
                score=round(new_sc, 4),
                why=_tag(c.why, "sem_gate"),
                path=c.path,
                relation=c.relation,
            )
        )
    cells.sort(key=lambda x: -x.score)
    meta = dict(heatmap.extra or {})
    meta.update(extra or {})
    meta["semantic_mode"] = "gate"
    meta["tau"] = tau
    meta["gate_factor"] = factor
    meta["engine"] = strategy
    return Heatmap(strategy=strategy, cells=cells, extra=meta)
