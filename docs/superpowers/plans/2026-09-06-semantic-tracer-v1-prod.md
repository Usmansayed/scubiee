# Semantic tracer v1 bakeoff — `verify_prod.json`

Cases: 10 · 14.05s · `real:fastembed`

| Arm | Acc | F1 | Must | Prec | Must@10 |
|-----|-----|----|------|------|---------|
| `composite_v1` | 0.9 | 0.8732 | 0.9667 | 0.8351 | 0.9227 |
| `semantic_tracer_v1` | 0.9 | 0.8779 | 0.9667 | 0.8424 | 0.9318 |
| `poly_embed` | 0.5 | 0.7936 | 0.9208 | 0.7482 | 0.866 |
| `hybrid_teleport` | 0.4 | 0.4978 | 0.9667 | 0.3644 | 0.9011 |
| `vector_only` | 0.0 | 0.3839 | 0.2535 | 0.9167 | 0.615 |

## vs composite_v1

- must Δ 0.0 · F1 Δ 0.0047 · prec Δ 0.0073 · acc Δ 0.0 · must@10 Δ 0.0091
- ship_gate: **False**

## Cycle 2 recommendation

Cycle 1 comparator helped ranking/must@10 — proceed to Cycle 2 (trace centroid + strict teleport).
