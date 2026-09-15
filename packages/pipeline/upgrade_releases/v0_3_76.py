"""Release 0.3.76 — adaptive multi-seed pack speed + stage timing."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.76",
    notes=(
        "R7 pack speed: adaptive secondary seeds skip full composite_v1 poly when "
        "already covered by seed1 island (light hop heatmap + merge_seed_v1). "
        "run_map_context exposes timing stages; multi-seed SLA target 8s. "
        "CTX_MULTI_SEED_ADAPTIVE=0 restores full-poly-per-seed."
    ),
)
class Release_0_3_76:
    pass
