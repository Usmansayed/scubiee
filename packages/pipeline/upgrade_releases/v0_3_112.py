"""Release 0.3.112 — status flags match the capability they name."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.112",
    notes=(
        "ast_hydrated is true only when this process holds the AST cache. "
        "agent_ready is yes only when pack can run. warm_ready requires the "
        "embedder. A missing warm_state is unknown, not ready."
    ),
)
def v0_3_112() -> None:
    return None
