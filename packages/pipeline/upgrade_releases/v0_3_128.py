"""Release 0.3.128 — search and the chunk corpus share one address space."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.128",
    notes=(
        "A newly synced file is now searchable. The dense channel is re-indexed "
        "into chunk position space, so a FAISS hit maps to the chunk it actually "
        "belongs to instead of whatever sat at the same offset in the vector "
        "store, and tail chunks no longer raise an out-of-bounds error that "
        "turned every search into a 500. Vectors are written before chunk lines, "
        "chunks that lost their vector are re-embedded, a delete compacts the "
        "collection, and a no-delta batch records the hashes it verified so the "
        "keeper stops re-syncing the same paths forever."
    ),
)
def v0_3_128() -> None:
    return None
