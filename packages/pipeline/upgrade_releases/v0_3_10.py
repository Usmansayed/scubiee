"""Release 0.3.10 — scubiee-mcp-bridge + CTX_SCUBIEE_BUILD hot reload."""

from __future__ import annotations

from pipeline.upgrade_registry import reinstall_component, release, update_component
from pipeline.upgrade_manifest import MCP_PIN_FORMAT

MCP_PINS = update_component(
    "mcp_pins",
    reason="scubiee-mcp-bridge + CTX_SCUBIEE_BUILD for post-upgrade hot reload",
    pin_format=MCP_PIN_FORMAT,
)
DAEMON = reinstall_component(
    "daemon",
    reason="restart engine on new package after bridge migration",
)


@release("0.3.10", notes="MCP bridge hot reload; upgrade supervisor hardening")
class Release_0_3_10:
    mcp_pins = MCP_PINS
    daemon = DAEMON
