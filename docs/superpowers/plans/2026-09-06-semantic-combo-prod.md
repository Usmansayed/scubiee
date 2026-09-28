# Semantic combo bakeoff — `verify_prod.json`

Cases: 10 · Variants: 55 · Backend: `real:fastembed` · 10.58s

## Baseline (`composite_v1`)

- Acc 0.9 · F1 0.8732 · Must-rec 0.9667 · Prec 0.8351

## Top 15 by must-rec → F1 → acc

| Arm | Acc | F1 | Must | Prec | Keep? |
|-----|-----|----|------|------|-------|
| `add_gate_q30s70` | 0.9 | 0.8732 | 0.9667 | 0.8351 | no |
| `add_gate_q50s50` | 0.9 | 0.8732 | 0.9667 | 0.8351 | no |
| `add_gate_q60s40` | 0.9 | 0.8732 | 0.9667 | 0.8351 | no |
| `add_gate_s_only` | 0.9 | 0.8732 | 0.9667 | 0.8351 | no |
| `add_q30s70_a10` | 0.9 | 0.8732 | 0.9667 | 0.8351 | no |
| `add_q30s70_a15` | 0.9 | 0.8732 | 0.9667 | 0.8351 | no |
| `add_q30s70_a25` | 0.9 | 0.8732 | 0.9667 | 0.8351 | no |
| `add_q30s70_a40` | 0.9 | 0.8732 | 0.9667 | 0.8351 | no |
| `add_q50s50_a10` | 0.9 | 0.8732 | 0.9667 | 0.8351 | no |
| `add_q50s50_a15` | 0.9 | 0.8732 | 0.9667 | 0.8351 | no |
| `add_q50s50_a25` | 0.9 | 0.8732 | 0.9667 | 0.8351 | no |
| `add_q50s50_a40` | 0.9 | 0.8732 | 0.9667 | 0.8351 | no |
| `add_q60s40_a10` | 0.9 | 0.8732 | 0.9667 | 0.8351 | no |
| `add_q60s40_a15` | 0.9 | 0.8732 | 0.9667 | 0.8351 | no |
| `add_q60s40_a25` | 0.9 | 0.8732 | 0.9667 | 0.8351 | no |

**Best by ranking:** `add_gate_q30s70`

**Keep-gate winners:** (none)

## Verdict

No variant met the keep gate (must↑ or hard↑ with F1 drop ≤0.02 and prec drop ≤0.03). Rank-only and teleport combos did not earn a default flip.
Note: raw best by must/F1 is `add_gate_q30s70` (may fail keep gate on precision).
