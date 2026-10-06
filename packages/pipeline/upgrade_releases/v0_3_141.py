"""Release 0.3.141 — CLI search no-index UX + seed-spec dedup."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.141",
    notes=(
        "Two polish fixes, no surface change. (1) `scubiee search` on a repo that "
        "is not indexed yet now prints a clean JSON error with an actionable hint "
        "(`Run: scubiee init <path>`) instead of dumping an uncaught Python traceback "
        "(pipeline.__main__.cmd_search catches the local-engine no-index case). "
        "(2) trace_lab.multi_seed.seed_specs_from_args now dedupes identical seed "
        "slots so an identical seed passed twice maps once, not twice. Map surface "
        "(map/gate/status, configs find|focus|related|graph) unchanged in this release."
    ),
)
def v0_3_141() -> None:
    return None
