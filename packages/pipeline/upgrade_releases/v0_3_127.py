"""Release 0.3.127 — mmap FAISS indexes are copied before add or delete."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.127",
    notes=(
        "A dirty sync that adds a vector no longer aborts the engine. "
        "Memory-mapped FAISS indexes are reloaded into owned memory before "
        "add or remove. Search can still open the index as a view."
    ),
)
def v0_3_127() -> None:
    return None
