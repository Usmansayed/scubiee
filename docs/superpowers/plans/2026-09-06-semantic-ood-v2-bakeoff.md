# Semantic novel strategies — OOD hard board v2

Board: `verify_ood_v2.json` (18 NEW cases) · 7.56s

**Not** verify_hard / verify_prod.

| Arm | Acc | F1 | Must | Prec | Must@10 |
|-----|-----|----|------|------|---------|
| `hybrid_teleport` | 0.2222 | 0.2657 | 1.0 | 0.161 | 0.9815 |
| `semantic_dual` | 0.6667 | 0.7298 | 0.9722 | 0.6417 | 0.9722 |
| `poly_embed` | 0.8333 | 0.7712 | 0.9583 | 0.7111 | 0.9583 |
| `semantic_tracer_v1` | 0.7222 | 0.7236 | 0.9583 | 0.6505 | 0.9583 |
| `semantic_tracer_fuse` | 0.7222 | 0.7236 | 0.9583 | 0.6505 | 0.9583 |
| `semantic_meet` | 0.7222 | 0.7207 | 0.9583 | 0.6474 | 0.9583 |
| `composite_v1` | 0.7222 | 0.719 | 0.9583 | 0.6454 | 0.9583 |
| `semantic_waypoint` | 0.7222 | 0.719 | 0.9583 | 0.6454 | 0.9583 |
| `semantic_ensemble` | 0.7222 | 0.6976 | 0.9583 | 0.6143 | 0.9583 |

**Best (must→F1→acc):** `hybrid_teleport` (recall-only — prec collapse)
**Best balanced (acc+F1):** **`poly_embed`** — hard acc **0.83** vs composite **0.72**
**Ship-gate winners vs composite_v1:** (none)

See full write-up: [`2026-09-06-semantic-ood-v2-findings.md`](2026-09-06-semantic-ood-v2-findings.md).

### Strategies under test

- `semantic_waypoint` — ANN targets + heat shortest seed→target paths
- `semantic_meet` — forward BFS ∩ backward from semantic targets
- `semantic_dual` — second embed seed + merge structural expands (linked-only)
- `semantic_ensemble` — max(composite, fuse, poly)
- baselines: composite_v1, semantic_tracer_v1/fuse, poly_embed, hybrid_teleport
