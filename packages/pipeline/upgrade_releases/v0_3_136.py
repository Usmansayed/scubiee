"""Release 0.3.136 — Map V3 only: CLI, rules, docs, and env all match the one `map` tool."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.136",
    notes=(
        "Completes the Map V3 cutover across every surface. The `scubiee map` CLI now "
        "drives the shipped map tool directly (config=find|focus|related|graph) and the "
        "old `scubiee pack` / `scubiee expand` subcommands are gone (the retired "
        "locate_cli/mcp_response_lean modules and their eval harness are archived under "
        "archive/old-mcp-map/). Generated agent rules/steering, the shipped rule "
        "templates, and the product docs (README, MCP tools reference, Cursor/commands "
        "guides) now describe only the one `map` tool plus gate/status — no "
        "pack_context/expand_context/collect_hot_context/workspace/expand. `scubiee "
        "connect` no longer writes the dead CTX_MCP_SURFACE / CTX_MCP_EXPERIMENT env "
        "knobs, and host autoApprove/alwaysAllow stay map/gate/status. No engine change."
    ),
)
def v0_3_136() -> None:
    return None
