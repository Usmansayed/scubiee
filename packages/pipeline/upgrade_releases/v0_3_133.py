"""Release 0.3.133 — graph sync lane fix + honest /health warm phase."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.133",
    notes=(
        "Fixes two bugs found in cross-surface QA. The dedup MinHash gained the "
        "vectorized update_batch() its call site expected, so graph catch-up no "
        "longer aborts with 'MinHash object has no attribute update_batch' — the "
        "graph lane (pack_context/expand_context freshness) stays healthy after "
        "every rebuild instead of silently degrading behind the hot BM25 lane. "
        "The /health endpoint now derives warm_phase from live warm flags, so a "
        "stale on-disk phase file no longer pins it to 'down' on a fully warm "
        "engine; it reports soft/dense consistently with warm_state and "
        "embedder_loaded."
    ),
)
def v0_3_133() -> None:
    return None
