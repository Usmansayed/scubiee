# 4 hard distributed multi-file expansion tests (v9)

Elapsed 5.52s · each test spans many files (network expansion).

## Summary

| Arm | Acc | F1 | Must | Hot files | Failed |
|-----|-----|----|------|-----------|--------|
| `composite_v1` | 1.0000 | 0.9869 | 1.0000 | 9.8 | — |
| `semantic_tracer_fuse` | 1.0000 | 0.9869 | 1.0000 | 9.8 | — |
| `hyb_fuse_demote_noise_plus` | 1.0000 | 0.9869 | 1.0000 | 9.8 | — |
| `poly_embed` | 0.5000 | 0.8725 | 0.8195 | 8.0 | d2,d3 |

Delta candidate vs composite: {'acc_delta': 0.0, 'must_delta': 0.0, 'f1_delta': 0.0}

## Per test

### `d1` — dist-checkout-graph (must=13 across **13 files**)

| Arm | OK | Must | F1 | Hot files | Missing |
|-----|----|------|----|-----------|---------|
| `composite_v1` | True | 1.00 | 1.000 | 15 | — |
| `semantic_tracer_fuse` | True | 1.00 | 1.000 | 15 | — |
| `poly_embed` | True | 1.00 | 1.000 | 14 | — |
| `hyb_fuse_demote_noise_plus` | True | 1.00 | 1.000 | 15 | — |

### `d2` — dist-auth-identity (must=8 across **7 files**)

| Arm | OK | Must | F1 | Hot files | Missing |
|-----|----|------|----|-----------|---------|
| `composite_v1` | True | 1.00 | 1.000 | 7 | — |
| `semantic_tracer_fuse` | True | 1.00 | 1.000 | 7 | — |
| `poly_embed` | False | 0.50 | 0.667 | 3 | connect,User.lookup,UserRepository.resolve,decode |
| `hyb_fuse_demote_noise_plus` | True | 1.00 | 1.000 | 7 | — |

### `d3` — dist-webhook-pay (must=9 across **9 files**)

| Arm | OK | Must | F1 | Hot files | Missing |
|-----|----|------|----|-----------|---------|
| `composite_v1` | True | 1.00 | 0.947 | 9 | — |
| `semantic_tracer_fuse` | True | 1.00 | 0.947 | 9 | — |
| `poly_embed` | False | 0.78 | 0.824 | 7 | record,get |
| `hyb_fuse_demote_noise_plus` | True | 1.00 | 0.947 | 9 | — |

### `d4` — dist-upload-search (must=8 across **8 files**)

| Arm | OK | Must | F1 | Hot files | Missing |
|-----|----|------|----|-----------|---------|
| `composite_v1` | True | 1.00 | 1.000 | 8 | — |
| `semantic_tracer_fuse` | True | 1.00 | 1.000 | 8 | — |
| `poly_embed` | True | 1.00 | 1.000 | 8 | — |
| `hyb_fuse_demote_noise_plus` | True | 1.00 | 1.000 | 8 | — |

