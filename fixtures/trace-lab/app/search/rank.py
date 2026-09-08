"""Rank token hits."""

from app.cache.memo import get as cache_get
from app.search.score import score_hit


def rank(toks: list) -> list:
    hits = []
    for t in toks:
        cached = cache_get("tok:" + t)
        hits.append({"tok": t, "s": score_hit(t), "c": cached})
    hits.sort(key=lambda h: -h["s"])
    return hits
