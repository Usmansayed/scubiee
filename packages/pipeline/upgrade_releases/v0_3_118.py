"""Release 0.3.118 — locate arguments mean what the schema says."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.118",
    notes=(
        "pack and expand honor k (k < 1 is an error, k=1 returns one card). "
        "collect honors an explicit score threshold and max_chars. "
        "expand callers no longer return the callee. callees stay direct calls. "
        "effects and config include direct calls that write files or settings."
    ),
)
def v0_3_118() -> None:
    return None
