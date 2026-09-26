"""Release 0.3.131 — a saved file reaches map in seconds, without killing the engine."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.131",
    notes=(
        "A new file saved by an agent reaches map in ~3s (p95 ~4.4s, was ~100s) "
        "without restarting the engine. FAISS add/delete/compact hold the lock "
        "search uses. Saves use a 250ms debounce (CTX_HOT_DEBOUNCE_MS) and publish "
        "by appending to the live binder (CTX_HOT_PUBLISH=0 restores the full "
        "reload; modified/deleted files still take it). A save skips compaction, "
        "the whole-graph merge and capability cards (a later non-hot catch-up "
        "carries them), no longer rewrites the embed-cache snapshot or every "
        "session store, and persists vectors right after publish. The newcomer "
        "repo walk runs off the keeper thread, and junk paths stop re-syncing "
        "every poll. Each save logs one line with per-stage ms."
    ),
)
def v0_3_131() -> None:
    return None
