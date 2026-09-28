# Pre-switch consistency (NEW boards v5/v6/v7)

Candidate: `hyb_fuse_demote_noise_plus` · elapsed 8.49s

**Consistent / go_switch:** `True` · board wins 3/3 · regressions none

## Aggregate

| Arm | Acc | F1 | Must | Prec | min Acc |
|-----|-----|----|------|------|---------|
| `hyb_fuse_demote_noise_plus` | 0.8492 | 0.7730 | 1.0000 | 0.6745 | 0.7143 |
| `hyb_comp_demote_noise_plus` | 0.8492 | 0.7679 | 1.0000 | 0.6673 | 0.7143 |
| `semantic_tracer_fuse` | 0.6865 | 0.7570 | 1.0000 | 0.6548 | 0.5000 |
| `composite_v1` | 0.6865 | 0.7561 | 1.0000 | 0.6540 | 0.5000 |
| `poly_embed` | 0.6825 | 0.7458 | 1.0000 | 0.6357 | 0.5000 |

Delta vs composite: acc +0.1627, F1 +0.0169, must +0.0000

## Per board

### verify_ood_v5.json (n=12)

| Arm | Acc | F1 | Must | Failed |
|-----|-----|----|------|--------|
| `composite_v1` | 0.5000 | 0.7791 | 1.0000 | a01,a02,a03,a04,a05,a10 |
| `semantic_tracer_fuse` | 0.5000 | 0.7791 | 1.0000 | a01,a02,a03,a04,a05,a10 |
| `poly_embed` | 0.5000 | 0.7670 | 1.0000 | a01,a02,a03,a04,a05,a10 |
| `hyb_fuse_demote_noise_plus` | 0.8333 | 0.8034 | 1.0000 | a05,a10 |
| `hyb_comp_demote_noise_plus` | 0.8333 | 0.8034 | 1.0000 | a05,a10 |

### verify_ood_v6.json (n=12)

| Arm | Acc | F1 | Must | Failed |
|-----|-----|----|------|--------|
| `composite_v1` | 0.9167 | 0.7606 | 1.0000 | b07 |
| `semantic_tracer_fuse` | 0.9167 | 0.7606 | 1.0000 | b07 |
| `poly_embed` | 0.8333 | 0.7060 | 1.0000 | b07,b11 |
| `hyb_fuse_demote_noise_plus` | 1.0000 | 0.7797 | 1.0000 | — |
| `hyb_comp_demote_noise_plus` | 1.0000 | 0.7797 | 1.0000 | — |

### verify_ood_v7.json (n=14)

| Arm | Acc | F1 | Must | Failed |
|-----|-----|----|------|--------|
| `composite_v1` | 0.6429 | 0.7287 | 1.0000 | c01,c03,c04,c06,c10 |
| `semantic_tracer_fuse` | 0.6429 | 0.7314 | 1.0000 | c01,c03,c04,c06,c10 |
| `poly_embed` | 0.7143 | 0.7645 | 1.0000 | c01,c04,c06,c10 |
| `hyb_fuse_demote_noise_plus` | 0.7143 | 0.7359 | 1.0000 | c01,c03,c04,c06 |
| `hyb_comp_demote_noise_plus` | 0.7143 | 0.7206 | 1.0000 | c01,c03,c04,c06 |

