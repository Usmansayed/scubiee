"""Release 0.3.103 — Mac host-sim settle honors wall-clock; expand retries ast_warming."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.103",
    notes=(
        "Host-sim settle no longer early-exits when warm_phase=dense (MLX hits dense "
        "in ~1–3s while AST may still be warming). expand_first retries on "
        "ast_warming for up to ~20s. Mac Gate M / full preprod battery on 0.3.102 tip."
    ),
)
def v0_3_103() -> None:
    return None
