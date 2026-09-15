"""Release 0.3.73 — reliability master plan: ready honesty, stamp refresh, SLA, latency."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.73",
    notes=(
        "Reliability: cold-start acceptance script; nonblocking warm skips "
        "open_repo while /health is down; status never claims fully ready "
        "without embedder_loaded; connect refreshes CTX_SCUBIEE_BUILD to "
        "installed version; keeper skips ticks/polls during locate_streak; "
        "registry atomic replace retries PermissionError; pack_context "
        "surfaces elapsed_ms SLA hints. Expected MCP tree documented "
        "(bridge→locate)."
    ),
)
class Release_0_3_73:
    pass
