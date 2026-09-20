"""Release 0.3.99 — quiet prewarm + 45s abort + Kiro process-real SLA."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.99",
    notes=(
        "Quiet attach: never wait=True /health-join during ORT prewarm. Hung "
        "prewarm aborts at 45s (no stamp refresh). Map/search return warming "
        "while phase=prewarm. Keepalive ticks only after dense. Lane B drives "
        "the full BridgeHost SLA with CTX_MCP_CLIENT=kiro (not pin-only)."
    ),
)
def v0_3_99() -> None:
    return None
