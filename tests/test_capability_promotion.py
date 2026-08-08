"""Capability cards must not evict the RAG window on SOFT queries.

Cards are BM25 over module summaries, so scores clear a bare floor for almost
any English query. Before the promotion rule existed, `merge` mode prepended up
to top_k cards and pushed every real hit out of a 5-target savings budget.
"""

from __future__ import annotations

from pipeline.capability import CapabilityIndex, LocateHit
from pipeline.engine import CAP_MERGE_MAX, promotable_cards


def _hits(*scores: float) -> list[LocateHit]:
    return [
        LocateHit(
            path=f"packages/pipeline/mod_{i}.py",
            symbol=f"mod_{i}",
            why="module card",
            score=s,
            card_id=f"c{i}",
        )
        for i, s in enumerate(scores)
    ]


def _index() -> CapabilityIndex:
    return CapabilityIndex([])


def test_indecisive_leader_promotes_nothing():
    # 12.06 vs 11.10 is the real shape of an English query against module cards:
    # every card scores high, none is decisive. RAG should own the window.
    assert promotable_cards(_index(), _hits(12.06, 11.10, 10.25), top_k=5) == []


def test_decisive_leader_is_capped_so_rag_keeps_most_of_the_window():
    promoted = promotable_cards(_index(), _hits(20.0, 2.5, 2.4, 2.3, 2.2), top_k=5)
    assert len(promoted) == CAP_MERGE_MAX
    assert promoted[0].score == 20.0


def test_promotion_never_exceeds_top_k():
    promoted = promotable_cards(_index(), _hits(20.0, 2.5, 2.4), top_k=1)
    assert len(promoted) == 1


def test_weak_scores_are_dropped_even_when_the_leader_is_decisive():
    promoted = promotable_cards(_index(), _hits(20.0, 0.5, 0.4), top_k=5)
    assert [h.score for h in promoted] == [20.0]


def test_no_capability_index_promotes_nothing():
    assert promotable_cards(None, _hits(20.0, 1.0), top_k=5) == []
    assert promotable_cards(_index(), [], top_k=5) == []
