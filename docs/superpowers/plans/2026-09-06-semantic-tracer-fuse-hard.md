# Semantic tracer fuse bakeoff — `verify_hard.json`

Cases: 50 · 16.57s · `real:fastembed`

| Arm | Acc | F1 | Must | Prec | Must@10 |
|-----|-----|----|------|------|---------|
| `composite_v1` | 0.42 | 0.7776 | 0.8044 | 0.8499 | 0.8049 |
| `semantic_tracer_v1` | 0.42 | 0.7781 | 0.8044 | 0.8503 | 0.8141 |
| `semantic_tracer_fuse` | 0.42 | 0.7653 | 0.8044 | 0.8173 | 0.8074 |
| `semantic_tracer_fuse_no_teleport` | 0.42 | 0.7781 | 0.8044 | 0.8503 | 0.8074 |
| `poly_embed` | 0.26 | 0.7915 | 0.8153 | 0.8517 | 0.7976 |
| `hybrid_teleport` | 0.06 | 0.3176 | 0.8757 | 0.2281 | 0.819 |
| `vector_only` | 0.0 | 0.3989 | 0.281 | 0.9067 | 0.6547 |

**Best balanced:** `semantic_tracer_v1`
**Ship-gate winners:** (none)

## vs composite_v1 (fuse)

```json
{
  "must_delta": 0.0,
  "f1_delta": -0.0123,
  "prec_delta": -0.0326,
  "acc_delta": 0.0,
  "must_at_10_delta": 0.0025,
  "ship_gate": false
}
```

## Recommendation

Fuse **with teleport** hurts F1/prec — do not ship that variant.

The **good research composite** is comparator + path polish + trace centroid/hub + info-gain (**teleport off**), matching `semantic_tracer_v1` / default `semantic_tracer_fuse`.

See [`2026-09-06-semantic-tracer-rnd-synthesis.md`](2026-09-06-semantic-tracer-rnd-synthesis.md).

### Fusion contents

- Cycle 1: edge/node comparator best-first + path polish — **KEEP**
- Cycle 2: live trace centroid — **KEEP**; strict teleport — **ablation only**
- Cycle 3 lite: hub penalty + info-gain skip — **KEEP**
- Spine: composite membership + DFG/sink rank — **KEEP**
