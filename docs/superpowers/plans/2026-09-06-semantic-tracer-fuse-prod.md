# Semantic tracer fuse bakeoff — `verify_prod.json`

Cases: 10 · 9.32s · `real:fastembed`

| Arm | Acc | F1 | Must | Prec | Must@10 |
|-----|-----|----|------|------|---------|
| `composite_v1` | 0.9 | 0.8732 | 0.9667 | 0.8351 | 0.9227 |
| `semantic_tracer_v1` | 0.9 | 0.8779 | 0.9667 | 0.8424 | 0.9318 |
| `semantic_tracer_fuse` | 0.9 | 0.835 | 0.9667 | 0.7563 | 0.9318 |
| `semantic_tracer_fuse_no_teleport` | 0.9 | 0.8779 | 0.9667 | 0.8424 | 0.9318 |
| `poly_embed` | 0.5 | 0.7936 | 0.9208 | 0.7482 | 0.866 |
| `hybrid_teleport` | 0.4 | 0.4978 | 0.9667 | 0.3644 | 0.9011 |
| `vector_only` | 0.0 | 0.3839 | 0.2535 | 0.9167 | 0.615 |

**Best balanced:** `semantic_tracer_v1`
**Ship-gate winners:** (none)

## vs composite_v1 (fuse)

```json
{
  "must_delta": 0.0,
  "f1_delta": -0.0382,
  "prec_delta": -0.0788,
  "acc_delta": 0.0,
  "must_at_10_delta": 0.0091,
  "ship_gate": false
}
```

## Recommendation

Fuse did not beat composite_v1 on balanced metrics — keep composite_v1; retain fuse for ablation research.

### Fusion contents

- Cycle 1: edge/node comparator best-first + path polish
- Cycle 2: live trace centroid + strict verified teleport
- Cycle 3 lite: hub penalty + info-gain skip
- Spine: composite membership + DFG/sink rank
