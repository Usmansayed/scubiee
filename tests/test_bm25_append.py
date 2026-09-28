"""BM25Index.append_docs / mark_dead: hot publish keeps lexical search current."""

from __future__ import annotations

import numpy as np

from conductor.bm25_index import BM25Index


def test_append_matches_full_rebuild_on_new_terms():
    base = ["def alpha(): pass", "class Beta: gamma", "delta epsilon alpha"]
    extra = ["def zzfresh_handler(payload): return payload", "alpha zzfresh_handler"]
    inc = BM25Index(base)
    inc.append_docs(extra)
    full = BM25Index(base + extra)
    assert inc.N == full.N == 5
    for q in ("zzfresh_handler", "zzfresh_handler payload"):
        # Terms first seen in the appended docs get exact IDF; postings/lengths are exact.
        np.testing.assert_allclose(inc.score_all(q), full.score_all(q), rtol=1e-12, atol=1e-12)
    # Older terms keep their previous IDF (N drifted by 2), but still rank the same docs.
    assert int(np.argmax(inc.score_all("gamma"))) == int(np.argmax(full.score_all("gamma"))) == 1


def test_mark_dead_zeroes_tombstones():
    idx = BM25Index(["old_token here", "other text"])
    assert idx.score_all("old_token")[0] > 0
    idx.mark_dead([0])
    assert idx.score_all("old_token")[0] == 0.0
    idx.append_docs(["old_token moved here"])
    s = idx.score_all("old_token")
    assert s[0] == 0.0 and s[2] > 0


def test_snapshot_consistent_for_concurrent_readers():
    idx = BM25Index(["a b c"] * 10)
    postings, denom, _idf, _dead = idx._snap
    idx.append_docs(["zz_new a"])
    # A reader holding the old snapshot sees a coherent old world.
    assert int(max(p[0].max() for p in postings.values())) < denom.shape[0]
    new_postings, new_denom, _, _ = idx._snap
    assert int(max(p[0].max() for p in new_postings.values())) < new_denom.shape[0]
