"""Top-3 conductor arches for R&D — selected by cross-suite + holdout consistency.

Frozen controls (do not mutate behavior casually):
  D_rerank, C_gear, A_minrank_expand

Experimental candidates are listed separately and compared under the R&D rule.
"""

from __future__ import annotations

TOP3_ARCHS: list[str] = [
    "D_rerank",
    "C_gear",
    "A_minrank_expand",
]

TOP3_ROLES: dict[str, str] = {
    "D_rerank": "Overall consistent — minrank pool + lexical/path rerank",
    "C_gear": "Semantic specialist — hybrid expand → re-fuse (GEAR-like)",
    "A_minrank_expand": "Structure+text foundation — min-rank + path/symbol boost",
}

EXPERIMENTAL_ARCHS: list[str] = [
    "R_gated_floor",
]

EXPERIMENTAL_ROLES: dict[str, str] = {
    "R_gated_floor": "REJECT default — soft lexical floor; OpenCode A/B net-negative vs D",
}

TOP3_EVAL_GOLDS: list[str] = ["suites", "v3", "diverse", "v2"]
