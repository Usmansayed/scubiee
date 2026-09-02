"""Release 0.3.7 — MCP pin refresh (connected-tool model)."""

from __future__ import annotations

from pipeline.upgrade_registry import release, update_component
from pipeline.upgrade_manifest import GATE_RULES_FORMAT, MCP_PIN_FORMAT

MCP_PINS = update_component(
    "mcp_pins",
    reason="refresh MCP pins for connected-tool install model",
    pin_format=MCP_PIN_FORMAT,
)
GATE_RULES = update_component(
    "gate_rules",
    reason="refresh GATE rules for token-efficient gating",
    pin_format=GATE_RULES_FORMAT,
)


@release("0.3.7", notes="Connected-tool MCP pins + project-local GATE rules")
class Release_0_3_7:
    mcp_pins = MCP_PINS
    gate_rules = GATE_RULES
