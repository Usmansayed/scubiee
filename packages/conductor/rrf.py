"""Weighted Reciprocal Rank Fusion."""

from __future__ import annotations

from collections import defaultdict


def weighted_rrf(
    ranked_lists: dict[str, list[int]],
    weights: dict[str, float],
    *,
    k: int = 60,
) -> list[tuple[int, float]]:
    """Fuse ranked id lists. Each list is best-first. Returns (id, score) desc."""
    scores: dict[int, float] = defaultdict(float)
    for name, ranking in ranked_lists.items():
        w = float(weights.get(name, 1.0))
        if w <= 0:
            continue
        for rank, doc_id in enumerate(ranking, start=1):
            scores[int(doc_id)] += w / (k + rank)
    return sorted(scores.items(), key=lambda x: (-x[1], x[0]))
