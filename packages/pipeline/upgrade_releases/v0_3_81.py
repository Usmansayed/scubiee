"""Release 0.3.81 — embed keepalive + keeper defer while clients connected."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.81",
    notes=(
        "Steady map after idle: engine-side embed keepalive (CTX_EMBED_KEEPALIVE, "
        "default 20s dummy encode while active_clients>0) keeps DML/GPU clocks up; "
        "keeper skips interval ticks while MCP/IDE clients are connected "
        "(CTX_KEEPER_DEFER_WHILE_CLIENTS=1). MCP heartbeat also pokes /v1/embed/keepalive."
    ),
)
class Release_0_3_81:
    pass
