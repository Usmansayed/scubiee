"""Release 0.3.79 — attach-warm ≤10s then ms steady while any client connected."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.79",
    notes=(
        "Attach-time parallel warm (CTX_MCP_ATTACH_WARM=1): engine + DML dummy "
        "encode + AST disk-bundle hydrate within CTX_WARM_DEADLINE_MS (10s). "
        "First map joins remaining budget instead of engine_warming thrash. "
        "status exposes warm_ready / warm_phase. Map proximity cache "
        "(CTX_MAP_RESULT_CACHE). Unload still only after all clients leave."
    ),
)
class Release_0_3_79:
    pass
