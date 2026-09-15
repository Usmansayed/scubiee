"""Release 0.3.80 — RuntimeController + httpx/tenacity (cross-platform)."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.80",
    notes=(
        "Single RuntimeController owns attach/serve/leave warm lifecycle "
        "(Windows/macOS/Linux; all MCP hosts). Engine HTTP via httpx+tenacity "
        "(CTX_ENGINE_HTTP_TRANSPORT=urllib escape). CTX_MCP_ATTACH_WARM is the "
        "one attach knob; CTX_MCP_AUTO_WARM is a deprecated alias."
    ),
)
class Release_0_3_80:
    pass
