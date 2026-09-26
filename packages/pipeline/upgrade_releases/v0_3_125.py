"""Release 0.3.125 — publish a dirty batch only when chunks change."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.125",
    notes=(
        "A dirty sync that upserts or removes no chunks does not reload the "
        "search index or bump generation. Sync failures are logged and the "
        "paths are queued again. While the engine is running, a cold embedder "
        "defers the batch until FastEmbed is already loaded."
    ),
)
def v0_3_125() -> None:
    return None
