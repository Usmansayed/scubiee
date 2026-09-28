# OOD semantic search experiments — findings

**Board:** `fixtures/trace-lab/verify_ood_v2.json` — **18 brand-new cases** (webhooks, oauth, checkout, uploads, search, flags, tax, inventory, shipping). **Not** `verify_hard` / `verify_prod`.

## Results (ranked by must → F1 → acc)

| Arm | Acc | F1 | Must | Prec | Must@10 |
|-----|-----|----|------|------|---------|
| `hybrid_teleport` | 0.22 | 0.27 | **1.00** | 0.23* | 0.98 |
| `semantic_dual` | 0.67 | 0.73 | **0.97** | — | 0.97 |
| **`poly_embed`** | **0.83** | **0.77** | 0.96 | — | 0.96 |
| `semantic_tracer_v1` / fuse | 0.72 | 0.72 | 0.96 | — | 0.96 |
| `semantic_meet` | 0.72 | 0.72 | 0.96 | — | 0.96 |
| `composite_v1` | 0.72 | 0.72 | 0.96 | — | 0.96 |
| `semantic_waypoint` | 0.72 | 0.72 | 0.96 | — | 0.96 |
| `semantic_ensemble` | 0.72 | 0.70 | 0.96 | — | 0.96 |

\*hybrid prec collapsed (not shippable).

## What “different semantic search” meant here

| Strategy | Idea | Outcome on OOD |
|----------|------|----------------|
| **waypoint** | ANN targets → heat seed→target paths | ≈ composite (paths already covered) |
| **meet** | Forward ∩ backward from semantic targets | ≈ composite |
| **dual** | 2nd embed seed + linked merge | Must↑ slightly; hard acc↓ (must_not) |
| **ensemble** | max(composite, fuse, poly) | Dilutes poly’s precision wins |
| **poly_embed** | Structure proposes; embeds **keep/drop** | **Clear win:** acc **0.72→0.83**, F1↑ |

## Significant improvement

On this **new** hard board, the semantic approach that actually moves the needle is **not** teleport/waypoints — it is **poly_embed’s comparator-as-filter**: embeddings decide which structural candidates are junk vs relevant.

Ship gate (must↑ and F1/prec/acc bounds vs composite): still no formal winner (poly_embed must flat-to-slightly-down vs dual’s must, but poly dominates hard correctness).

## Recommendation

1. Treat **`poly_embed`** as the OOD research champion for balanced quality.  
2. Keep **`semantic_tracer_v1`/`fuse`** for ranking (must@10) on older boards.  
3. Next merge attempt: **poly-style drop/keep on top of composite membership** (fuse poly’s residual filter into `semantic_tracer_fuse`), not more ANN teleports.  
4. Retire evaluating on `verify_hard` alone — always include `verify_ood_v2` (and future OOD boards).
