"""Release 0.3.84 — warm while MCP connected; unload 10s after last client."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.84",
    notes=(
        "Default CTX_DISCONNECT_DEBOUNCE_S / CTX_ENGINE_IDLE_S = 10s. "
        "enforce_mcp_warm_contract: reap orphan MCP → reconcile clients → hold RUN "
        "while any client remains, else standby+stop engine. Watchdog + idle sweeper "
        "both enforce the contract; leave falls back to local unregister if HTTP fails."
    ),
)
class Release_0_3_84:
    pass
