"""Release 0.3.107 — named callees stay ranked; expand and repo bind match disk."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.107",
    notes=(
        "Naming a callee in the pack query keeps its span tie-break, so "
        "run_map_context and run_collect_hot stay above short helpers. "
        "expand_context reads a symbol from disk when the baked graph lacks it, "
        "including imported callees. Cold is a score under the hot threshold. "
        "An explicit missing root or unknown project_id stays unmanaged. "
        "prewarm_pack_graph and ensure_composite_edges ship in the wheel."
    ),
)
def v0_3_107() -> None:
    return None
