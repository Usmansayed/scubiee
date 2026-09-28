# Semantic tracer v1 bakeoff — `verify_hard.json`

Cases: 50 · 24.37s · `real:fastembed`

| Arm | Acc | F1 | Must | Prec | Must@10 |
|-----|-----|----|------|------|---------|
| `composite_v1` | 0.42 | 0.7776 | 0.8044 | 0.8499 | 0.8049 |
| `semantic_tracer_v1` | 0.42 | 0.7792 | 0.8044 | 0.8513 | 0.8214 |
| `poly_embed` | 0.26 | 0.7915 | 0.8153 | 0.8517 | 0.7976 |
| `hybrid_teleport` | 0.06 | 0.3176 | 0.8757 | 0.2281 | 0.819 |
| `vector_only` | 0.0 | 0.3989 | 0.281 | 0.9067 | 0.6547 |

## vs composite_v1

- must Δ 0.0 · F1 Δ 0.0016 · prec Δ 0.0014 · acc Δ 0.0 · must@10 Δ 0.0165
- ship_gate: **False**

## Cycle 2 recommendation

Cycle 1 comparator helped ranking/must@10 — proceed to Cycle 2 (trace centroid + strict teleport).

### Mechanism evidence (Cycle 1)

- Comparators change **expansion order** + mild heat tint; they do **not** invent edges (`vector_only` still loses hard).
- On hard: must@10 **0.805 → 0.821** with flat must-rec and tiny F1/prec gains — ranking quality improved without precision freefall.
- Ship gate (must↑ + balanced F1/prec/acc) **not** met — need FN recovery (Cycle 2 teleport), not stronger island rescore.
