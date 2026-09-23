"""Release 0.3.104 — collect, expand, and pack read the current file."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.104",
    notes=(
        "collect_hot_context(file::symbol) reads the function on disk, not the "
        "module header, including when the AST bundle is cold. expand accepts a "
        "heatmap id (file::symbol or file:start-end). Lean pack keeps seeds hot "
        "and pins their line spans to the current file, on the cold map fallback "
        "and on multi_seed_v1."
    ),
)
def v0_3_104() -> None:
    return None
