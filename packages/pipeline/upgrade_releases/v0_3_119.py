"""Release 0.3.119 — pack k is the heatmap size."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.119",
    notes=(
        "pack_context stops growing a thin seed past k, and the heatmap is "
        "trimmed to k. Requested seeds are kept when there are more seeds than k. "
        "Body budgets of 1 character are no longer raised to 200, 400, or 500."
    ),
)
def v0_3_119() -> None:
    return None
