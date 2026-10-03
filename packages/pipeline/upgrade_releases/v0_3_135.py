"""Release 0.3.135 — connect writes the Map V3 approve surface (map/gate/status)."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.135",
    notes=(
        "Follow-up to the Map V3 cutover: `scubiee connect` now writes the Map V3 "
        "tool surface into host autoApprove/alwaysAllow (and Cursor/Claude "
        "allowlists) — gate, map, status — instead of the retired 8-tool set. The "
        "old names (pack_context, expand_context, collect_hot_context, workspace, "
        "expand) are treated as stale and pruned from any pre-migration config on "
        "the next connect, so hosts stop advertising dead tools. No engine change."
    ),
)
def v0_3_135() -> None:
    return None
