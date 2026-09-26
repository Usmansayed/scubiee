"""Release 0.3.116 — status agrees with a pack that already succeeded."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.116",
    notes=(
        "agent_ready stays yes when locate is ready. A cold AST bit no longer "
        "reports warming after pack_context has the bundle. ast_hydrated "
        "follows the in-process cache or the hydrate flag."
    ),
)
def v0_3_116() -> None:
    return None
