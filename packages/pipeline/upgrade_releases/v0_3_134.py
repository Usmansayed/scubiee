"""Release 0.3.134 — Map V3 is the default Scubiee map (one `map` tool)."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.134",
    notes=(
        "Ships Map V3 as the production Scubiee map and retires the old 8-tool "
        "surface. The MCP worker is now pipeline.map_v3_server (served through the "
        "same mcp_bridge transport), exposing one semantic retrieval tool `map` "
        "with configs find | focus | related | graph, plus gate/status for health. "
        "The legacy pack_context / expand_context / collect_hot_context / workspace "
        "/ old-map tools and the pipeline.mcp_locate module are removed from the "
        "package (archived under archive/old-mcp-map/). The core engine "
        "(indexing/retrieval/graph/store and the /v1/* HTTP API) is unchanged — "
        "Map V3 talks to it over the same contract. Enrollment checks moved to "
        "pipeline.project_id._is_enrolled and the gate line to pipeline.gate_cli. "
        "After upgrading, reconnect so the IDE respawns the map_v3_server worker; "
        "autoApprove/alwaysAllow should list map, gate, status."
    ),
)
def v0_3_134() -> None:
    return None
