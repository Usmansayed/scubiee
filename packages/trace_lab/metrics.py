"""Gold-heatmap metrics: recall, precision, FN/FP, ranking, token waste."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from trace_lab.types import GoldCase, Heatmap, TraceNode


@dataclass
class TraceMetrics:
    case_id: str
    strategy: str
    recall_must: float
    precision_hot: float
    f1: float
    false_negatives: list[str]
    false_positives_forbidden: list[str]
    extra_hot: list[str]
    inversions: int
    ndcg: float
    token_precision: float
    hot_count: int
    hot_tokens: int
    useful_tokens: int

    def as_dict(self) -> dict:
        return asdict(self)


def _gain(nid: str, gold: GoldCase) -> float:
    if nid in gold.must_ids:
        return 3.0
    if nid in gold.should_ids:
        return 2.0
    if nid in gold.must_not_ids:
        return 0.0
    return 0.5


def ndcg_at_k(ranked: list[str], gold: GoldCase, k: int = 12) -> float:
    k = min(k, len(ranked))
    if k == 0:
        return 0.0
    dcg = 0.0
    for i, nid in enumerate(ranked[:k], start=1):
        dcg += _gain(nid, gold) / math.log2(i + 1)
    ideal = sorted(
        (_gain(n, gold) for n in (gold.must_ids | gold.should_ids | gold.must_not_ids | set(ranked[:k]))),
        reverse=True,
    )[:k]
    idcg = 0.0
    for i, g in enumerate(ideal, start=1):
        idcg += g / math.log2(i + 1)
    return 0.0 if idcg <= 0 else round(dcg / idcg, 4)


def evaluate(
    heatmap: Heatmap,
    gold: GoldCase,
    nodes: dict[str, TraceNode],
    *,
    hot_threshold: float = 0.45,
) -> TraceMetrics:
    ranked = heatmap.ranked_ids()
    hot = [c.node_id for c in heatmap.cells if c.score >= hot_threshold]
    hot_set = set(hot)
    must = gold.must_ids
    relevant = gold.relevant_ids
    must_not = gold.must_not_ids

    found_must = must & hot_set
    recall = len(found_must) / max(len(must), 1)
    precision = len(hot_set & relevant) / max(len(hot_set), 1)
    if recall + precision <= 0:
        f1 = 0.0
    else:
        f1 = 2 * recall * precision / (recall + precision)

    rank_of = {nid: i for i, nid in enumerate(ranked, start=1)}
    inversions = 0
    for bad in must_not:
        rb = rank_of.get(bad)
        if rb is None:
            continue
        for good in must:
            rg = rank_of.get(good)
            if rg is not None and rb < rg:
                inversions += 1

    hot_tokens = 0
    useful_tokens = 0
    for nid in hot:
        n = nodes.get(nid)
        if n is None:
            continue
        hot_tokens += n.token_count
        if nid in relevant:
            useful_tokens += n.token_count
    token_precision = useful_tokens / max(hot_tokens, 1)

    return TraceMetrics(
        case_id=gold.id,
        strategy=heatmap.strategy,
        recall_must=round(recall, 4),
        precision_hot=round(precision, 4),
        f1=round(f1, 4),
        false_negatives=sorted(must - hot_set),
        false_positives_forbidden=sorted(hot_set & must_not),
        extra_hot=sorted(hot_set - relevant - must_not),
        inversions=inversions,
        ndcg=ndcg_at_k(ranked, gold),
        token_precision=round(token_precision, 4),
        hot_count=len(hot),
        hot_tokens=hot_tokens,
        useful_tokens=useful_tokens,
    )
