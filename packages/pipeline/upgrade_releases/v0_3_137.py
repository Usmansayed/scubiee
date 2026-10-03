"""Release 0.3.137 — Map V3 only across every acceptance/harness surface too."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.137",
    notes=(
        "Final sweep of the Map V3 cutover. The in-package host-sim SLA harness "
        "(pipeline.mcp_host_sim) now drives the shipped map tool — its pack/expand "
        "SLA phases call map config=focus / config=related instead of the retired "
        "pack_context / expand_context. The live acceptance tests "
        "(mac/windows_production_test) and the ship-surface checkers "
        "(bug_bounty_update_surface, scubiee_mcp_ship_check, _kiro_mcp_smoke) assert "
        "the Map V3 surface {gate, map, status} with configs find|focus|related|graph. "
        "The remaining standalone old-surface probe scripts were archived under "
        "archive/old-mcp-map/. No engine or runtime change — the shipped MCP worker "
        "(pipeline.map_v3_server) is unchanged from 0.3.136."
    ),
)
def v0_3_137() -> None:
    return None
