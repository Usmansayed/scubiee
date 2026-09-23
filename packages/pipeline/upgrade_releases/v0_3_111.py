"""Release 0.3.111 — status.ast_hydrated matches a warm AST cache."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.111",
    notes=(
        "status.ast_hydrated follows the in-process AST cache and the hydrate "
        "flag. A successful pack or expand no longer leaves that status bit false."
    ),
)
def v0_3_111() -> None:
    return None
