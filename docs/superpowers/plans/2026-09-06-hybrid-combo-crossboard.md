# Hybrid combo cross-board sweep

Elapsed: 12.38s · boards: verify_ood_v2.json, verify_ood_v3.json, verify_ood_v4.json

**Anti-overfit rule:** win on ≥2 of v2/v3/v4; do not crown v2-only winners.

## Verdict

**Ship candidate (research):** `hyb_fuse_demote_noise_plus`  
(= `semantic_tracer_fuse` island + demote log/track/analytics + deep foreign weak nodes below hot)

| Metric (mean of 3 boards) | composite_v1 | **hyb_fuse_demote_noise_plus** |
|---------------------------|--------------|-------------------------------|
| Accuracy | 0.803 | **0.863** (+6pp) |
| F1 | 0.785 | **0.797** |
| Must | 0.976 | 0.976 (flat) |
| Board wins | — | **3 / 3** |

`hyb_comp_demote_noise_plus` ties it (same filter on composite base).  
F1-max arm `hyb_fuse_demote_strict` hits F1 **0.87** but loses hard-acc on v3 — keep as ablation, not default.

Production default stays `composite_v1` until a prod MCP ship gate; this arm is wired in `compile_bundle(with_embed_power=True)`.

## Aggregate (mean across boards)

| Arm | Acc | F1 | Must | Prec | Board wins |
|-----|-----|----|------|------|------------|
| `hyb_fuse_demote_noise_plus` | 0.8634 | 0.7968 | 0.9757 | 0.7266 | 3 |
| `hyb_comp_demote_noise_plus` | 0.8634 | 0.7968 | 0.9757 | 0.7266 | 3 |
| `hyb_fuse_demote_strict` | 0.7801 | 0.8744 | 0.9688 | 0.8426 | 2 |
| `hyb_comp_demote_strict` | 0.7801 | 0.8744 | 0.9688 | 0.8426 | 2 |
| `hyb_v1_demote_strict` | 0.7801 | 0.8744 | 0.9688 | 0.8426 | 2 |
| `hyb_fuse_strict` | 0.7801 | 0.8733 | 0.9688 | 0.8413 | 2 |
| `hyb_fuse_strict_aff` | 0.7801 | 0.8733 | 0.9688 | 0.8413 | 2 |
| `hyb_comp_strict` | 0.7801 | 0.8733 | 0.9688 | 0.8413 | 2 |
| `hyb_v1_strict` | 0.7801 | 0.8733 | 0.9688 | 0.8413 | 2 |
| `hyb_fuse_demote_bal` | 0.8009 | 0.8029 | 0.9757 | 0.7349 | 2 |
| `hyb_fuse_balanced` | 0.8009 | 0.8018 | 0.9757 | 0.7336 | 2 |
| `hyb_comp_balanced` | 0.8009 | 0.8006 | 0.9757 | 0.7320 | 2 |
| `hyb_fuse_noise_plus` | 0.8218 | 0.7919 | 0.9757 | 0.7214 | 2 |
| `hyb_fuse_demote_noise` | 0.8449 | 0.7867 | 0.9757 | 0.7148 | 2 |
| `hyb_poly_adaptive` | 0.8403 | 0.7860 | 0.9757 | 0.7166 | 2 |
| `hyb_comp_demote_noise` | 0.8449 | 0.7834 | 0.9757 | 0.7098 | 2 |
| `hyb_poly_demote_strict` | 0.7963 | 0.8742 | 0.9688 | 0.8384 | 1 |
| `hyb_poly_strict` | 0.7963 | 0.8710 | 0.9688 | 0.8338 | 1 |
| `hyb_poly_balanced` | 0.8171 | 0.8065 | 0.9757 | 0.7419 | 1 |
| `hyb_fuse_noise` | 0.8032 | 0.7819 | 0.9757 | 0.7096 | 1 |
| `hyb_fuse_poly` | 0.7824 | 0.7794 | 0.9757 | 0.7032 | 1 |
| `hyb_fuse_aff` | 0.7824 | 0.7794 | 0.9757 | 0.7032 | 1 |
| `hyb_fuse_struct` | 0.7824 | 0.7794 | 0.9757 | 0.7032 | 1 |
| `hyb_fuse_adaptive` | 0.8032 | 0.7776 | 0.9757 | 0.7036 | 1 |
| `hyb_fuse_adaptive2` | 0.8032 | 0.7776 | 0.9757 | 0.7036 | 1 |
| `hyb_v1_adaptive` | 0.8032 | 0.7776 | 0.9757 | 0.7036 | 1 |
| `hyb_v1_poly` | 0.7824 | 0.7772 | 0.9757 | 0.7001 | 1 |
| `hyb_v1_aff` | 0.7824 | 0.7772 | 0.9757 | 0.7001 | 1 |
| `poly_embed` | 0.7986 | 0.7768 | 0.9757 | 0.7037 | 1 |
| `hyb_poly_mild` | 0.7986 | 0.7768 | 0.9757 | 0.7037 | 1 |
| `hyb_poly_aff` | 0.7986 | 0.7768 | 0.9757 | 0.7037 | 1 |
| `hyb_poly_struct` | 0.7986 | 0.7768 | 0.9757 | 0.7037 | 1 |
| `hyb_comp_noise` | 0.8032 | 0.7753 | 0.9757 | 0.7006 | 1 |
| `hyb_comp_poly` | 0.7824 | 0.7748 | 0.9757 | 0.6971 | 1 |
| `hyb_comp_aff` | 0.7824 | 0.7748 | 0.9757 | 0.6971 | 1 |
| `hyb_comp_adaptive` | 0.8032 | 0.7730 | 0.9757 | 0.6975 | 1 |
| `semantic_tracer_fuse` | 0.8032 | 0.7862 | 0.9757 | 0.7133 | 0 |
| `semantic_tracer_v1` | 0.8032 | 0.7862 | 0.9757 | 0.7133 | 0 |
| `composite_v1` | 0.8032 | 0.7846 | 0.9757 | 0.7116 | 0 |
| `hyb_fuse_mild` | 0.7824 | 0.7715 | 0.9757 | 0.6945 | 0 |
| `hyb_fuse_mild_struct` | 0.7824 | 0.7715 | 0.9757 | 0.6945 | 0 |
| `hyb_fuse_rescore` | 0.7824 | 0.7707 | 0.9757 | 0.6935 | 0 |
| `hyb_comp_mild` | 0.7824 | 0.7660 | 0.9757 | 0.6875 | 0 |
| `hyb_comp_rescore` | 0.7824 | 0.7652 | 0.9757 | 0.6865 | 0 |

**Hard generalizers:** ['hyb_fuse_demote_noise_plus', 'hyb_comp_demote_noise_plus', 'hyb_fuse_demote_strict', 'hyb_comp_demote_strict', 'hyb_v1_demote_strict', 'hyb_fuse_strict', 'hyb_fuse_strict_aff', 'hyb_comp_strict', 'hyb_v1_strict', 'hyb_fuse_demote_noise', 'hyb_poly_adaptive', 'hyb_comp_demote_noise']
**Soft (≥2 board wins):** ['hyb_fuse_demote_bal', 'hyb_fuse_balanced', 'hyb_comp_balanced', 'hyb_fuse_noise_plus']
**Best by rank key:** `hyb_fuse_demote_noise_plus`

## Per board

### verify_ood_v2.json (n=18)

| Arm | Acc | F1 | Must |
|-----|-----|----|------|
| `hyb_poly_demote_strict` | 0.8889 | 0.8934 | 0.9583 |
| `hyb_poly_strict` | 0.8889 | 0.8837 | 0.9583 |
| `hyb_poly_balanced` | 0.8889 | 0.8028 | 0.9583 |
| `hyb_poly_adaptive` | 0.8333 | 0.7742 | 0.9583 |
| `poly_embed` | 0.8333 | 0.7712 | 0.9583 |
| `hyb_poly_mild` | 0.8333 | 0.7712 | 0.9583 |
| `hyb_poly_aff` | 0.8333 | 0.7712 | 0.9583 |
| `hyb_poly_struct` | 0.8333 | 0.7712 | 0.9583 |
| `hyb_fuse_demote_strict` | 0.7778 | 0.8701 | 0.9583 |
| `hyb_comp_demote_strict` | 0.7778 | 0.8701 | 0.9583 |
| `hyb_v1_demote_strict` | 0.7778 | 0.8701 | 0.9583 |
| `hyb_fuse_strict` | 0.7778 | 0.8668 | 0.9583 |

### verify_ood_v3.json (n=16)

| Arm | Acc | F1 | Must |
|-----|-----|----|------|
| `hyb_fuse_demote_noise_plus` | 1.0000 | 0.9157 | 1.0000 |
| `hyb_comp_demote_noise_plus` | 1.0000 | 0.9157 | 1.0000 |
| `hyb_fuse_demote_noise` | 1.0000 | 0.9069 | 1.0000 |
| `hyb_comp_demote_noise` | 1.0000 | 0.9069 | 1.0000 |
| `composite_v1` | 0.9375 | 0.9090 | 1.0000 |
| `semantic_tracer_fuse` | 0.9375 | 0.9090 | 1.0000 |
| `semantic_tracer_v1` | 0.9375 | 0.9090 | 1.0000 |
| `hyb_poly_adaptive` | 0.9375 | 0.8441 | 1.0000 |
| `hyb_fuse_noise_plus` | 0.8750 | 0.9011 | 1.0000 |
| `hyb_fuse_balanced` | 0.8750 | 0.8977 | 1.0000 |
| `hyb_fuse_demote_bal` | 0.8750 | 0.8977 | 1.0000 |
| `hyb_comp_balanced` | 0.8750 | 0.8977 | 1.0000 |

### verify_ood_v4.json (n=16)

| Arm | Acc | F1 | Must |
|-----|-----|----|------|
| `hyb_fuse_noise_plus` | 0.8125 | 0.7387 | 0.9688 |
| `hyb_fuse_demote_noise_plus` | 0.8125 | 0.7387 | 0.9688 |
| `hyb_comp_demote_noise_plus` | 0.8125 | 0.7387 | 0.9688 |
| `hyb_fuse_adaptive` | 0.8125 | 0.7297 | 0.9688 |
| `hyb_fuse_noise` | 0.8125 | 0.7297 | 0.9688 |
| `hyb_fuse_demote_noise` | 0.8125 | 0.7297 | 0.9688 |
| `hyb_fuse_adaptive2` | 0.8125 | 0.7297 | 0.9688 |
| `hyb_v1_adaptive` | 0.8125 | 0.7297 | 0.9688 |
| `hyb_comp_demote_noise` | 0.8125 | 0.7257 | 0.9688 |
| `hyb_comp_adaptive` | 0.8125 | 0.7205 | 0.9688 |
| `hyb_comp_noise` | 0.8125 | 0.7205 | 0.9688 |
| `hyb_fuse_strict` | 0.7500 | 0.8184 | 0.9688 |

