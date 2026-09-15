"""Release 0.3.85 — attach warm binds index + search probe; 30s warm deadline."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.85",
    notes=(
        "Attach warm opens the repo and runs a soft-search probe so first map is not a "
        "35s cold bind. CTX_WARM_DEADLINE_MS default 30s. Leave-only unload + deferred "
        "MCP local register hold (0.3.84 follow-through). mcp_host_sim Lane A harness."
    ),
)
class Release_0_3_85:
    pass
