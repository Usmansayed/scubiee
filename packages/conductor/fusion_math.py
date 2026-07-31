"""Classical unsupervised rank/score fusion (Fox & Shaw, Cormack RRF, LogISR).

All operate on rank lists (best-first). Rank→score maps avoid incomparable
raw BM25 vs dense vs graph magnitudes.

References:
  - Fox & Shaw 1994: CombSUM / CombMNZ
  - Cormack et al. 2009: Reciprocal Rank Fusion  score = Σ 1/(k+rank)
  - ISR / LogISR: 1/rank² and log(1+1/rank) style monotone maps
  - Montague & Aslam: Condorcet fuse (pairwise majority)
"""

from __future__ import annotations

import math
from collections import defaultdict


def rank_map(ranking: list[str]) -> dict[str, int]:
    return {f: i for i, f in enumerate(ranking, start=1)}


def rrf_score(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank)


def isr_score(rank: int) -> float:
    """Inverse square rank."""
    return 1.0 / (rank * rank)


def logisr_score(rank: int) -> float:
    """Log-smoothed ISR: log(1 + 1/rank²) — softens top-heavy ISR."""
    return math.log1p(1.0 / (rank * rank))


def borda_score(rank: int, n: int) -> float:
    """Borda: n - rank + 1 (higher better)."""
    return float(max(n - rank + 1, 0))


def fuse_combsum(
    rankings: dict[str, list[str]],
    *,
    score_fn=rrf_score,
    weights: dict[str, float] | None = None,
    pool_cap: int = 80,
) -> list[tuple[str, float]]:
    """Σ_c w_c · s(rank_c). Default s = RRF map → weighted RRF."""
    weights = weights or {c: 1.0 for c in rankings}
    scores: dict[str, float] = defaultdict(float)
    for name, ranking in rankings.items():
        w = float(weights.get(name, 1.0))
        if w <= 0:
            continue
        for rank, f in enumerate(ranking[:pool_cap], start=1):
            scores[f] += w * score_fn(rank)
    return sorted(scores.items(), key=lambda x: (-x[1], x[0]))


def fuse_combmnz(
    rankings: dict[str, list[str]],
    *,
    score_fn=rrf_score,
    weights: dict[str, float] | None = None,
    pool_cap: int = 80,
    hit_depth: int = 40,
) -> list[tuple[str, float]]:
    """CombMNZ: (# lists containing doc in top hit_depth) × CombSUM.

    Encodes Lee's observation: systems agree on relevant docs more than
    on non-relevant — agreement count is a relevance prior.
    """
    weights = weights or {c: 1.0 for c in rankings}
    sums: dict[str, float] = defaultdict(float)
    hits: dict[str, int] = defaultdict(int)
    for name, ranking in rankings.items():
        w = float(weights.get(name, 1.0))
        if w <= 0:
            continue
        seen_depth = set(ranking[:hit_depth])
        for rank, f in enumerate(ranking[:pool_cap], start=1):
            sums[f] += w * score_fn(rank)
            if f in seen_depth:
                hits[f] += 1
    scored = {f: sums[f] * max(hits[f], 1) for f in sums}
    return sorted(scored.items(), key=lambda x: (-x[1], x[0]))


def fuse_condorcet(
    rankings: dict[str, list[str]],
    *,
    pool_cap: int = 50,
) -> list[tuple[str, float]]:
    """Pairwise majority: score(f) = wins − losses over union of top pools.

    Approximation of Condorcet-fuse; O(|C|² · n_channels) on candidate set C.
    Ties broken by RRF mass.
    """
    maps = {n: rank_map(r[:pool_cap]) for n, r in rankings.items()}
    candidates = sorted({f for r in rankings.values() for f in r[:pool_cap]})
    big = pool_cap + 10
    wins: dict[str, float] = defaultdict(float)
    for i, a in enumerate(candidates):
        for b in candidates[i + 1 :]:
            a_better = b_better = 0
            for m in maps.values():
                ra, rb = m.get(a, big), m.get(b, big)
                if ra < rb:
                    a_better += 1
                elif rb < ra:
                    b_better += 1
            if a_better > b_better:
                wins[a] += 1.0
                wins[b] -= 1.0
            elif b_better > a_better:
                wins[b] += 1.0
                wins[a] -= 1.0
    rrf = dict(fuse_combsum(rankings, score_fn=rrf_score, pool_cap=pool_cap))
    return sorted(
        ((f, float(wins[f]) + 0.01 * rrf.get(f, 0.0)) for f in candidates),
        key=lambda x: (-x[1], x[0]),
    )


def channel_peakiness(scores: list[float], top_n: int = 5) -> float:
    """How concentrated is mass in top_n? ∈ [0,1]. High → channel is confident."""
    if not scores:
        return 0.0
    s = sorted((max(0.0, float(x)) for x in scores), reverse=True)
    total = sum(s) + 1e-12
    return float(sum(s[:top_n]) / total)


def adaptive_weights_from_peakiness(peak: dict[str, float], floor: float = 0.35) -> dict[str, float]:
    """Map peakiness → weights; floor keeps weak channels from vanishing."""
    if not peak:
        return {}
    m = max(peak.values()) + 1e-12
    return {c: floor + (1.0 - floor) * (p / m) for c, p in peak.items()}
