"""Release 0.3.140 — Map V3: idle keepalive so the first call after a break stays fast."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.140",
    notes=(
        "Keeps the map tool fast after an idle gap. The worker's grep fast-path relies "
        "on a short (10s) stat-TTL; after a few minutes idle it expired, so the first "
        "call back (e.g. focus) paid a ~300ms per-file stat() storm re-validating ~5k "
        "files (~550ms total). A lightweight keepalive thread in the MCP worker now "
        "re-stamps that validation on a timer while idle and extends the effective TTL "
        "to cover the pulse interval, so the first post-idle call skips the storm: "
        "focus-after-idle ~555ms -> ~230ms, with warm steady-state and all tool output "
        "byte-identical. Interval is CTX_MAP_WARM_INTERVAL_S (default 120s; 0 disables). "
        "Pairs with the 0.3.139 engine/embedder residency (CTX_ENGINE_IDLE_S / "
        "CTX_EMBED_IDLE_DEMOTE_S = 4800s) that already prevents the ~20s dense re-warm. "
        "No ranking or payload change; map/gate/status surface unchanged."
    ),
)
def v0_3_140() -> None:
    return None
