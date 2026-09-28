# Rich-context OOD board v8

Queries that **need more context**: long E2E must chains, vague prompts, deep cross-module hops.

Candidate: `hyb_fuse_demote_noise_plus` · elapsed 5.95s · **rich_context_ok:** `True`

Delta vs composite: {'accuracy': 0.0, 'f1': 0.0, 'must': 0.0, 'rich_acc': 0.0, 'rich_must': 0.0}

| Arm | Acc | F1 | Must | Must@10 | n_hot | Rich Acc | Rich Must | Failed |
|-----|-----|----|------|---------|-------|----------|-----------|--------|
| `composite_v1` | 1.0000 | 0.9456 | 1.0000 | 0.9844 | 6.9 | 1.0 | 1.0 | — |
| `semantic_tracer_fuse` | 1.0000 | 0.9456 | 1.0000 | 1.0000 | 6.9 | 1.0 | 1.0 | — |
| `hyb_fuse_demote_noise_plus` | 1.0000 | 0.9456 | 1.0000 | 1.0000 | 6.9 | 1.0 | 1.0 | — |
| `hyb_comp_demote_noise_plus` | 1.0000 | 0.9387 | 1.0000 | 0.9922 | 6.9 | 1.0 | 1.0 | — |
| `poly_embed` | 0.8125 | 0.8758 | 0.9598 | 0.9598 | 7.1 | 0.8571 | 0.9796 | r05,r09,r14 |
| `hyb_fuse_demote_strict` | 0.3750 | 0.8948 | 0.8512 | 0.9844 | 4.8 | 0.2857 | 0.8384 | r01,r02,r03,r04,r05,r07,r09,r11 |

## Per-case must recall (candidate vs composite)

| Case | n_must | composite must | candidate must | cand correct |
|------|--------|----------------|----------------|--------------|
| `r01` | 8 | 1.00 | 1.00 | True |
| `r02` | 7 | 1.00 | 1.00 | True |
| `r03` | 7 | 1.00 | 1.00 | True |
| `r04` | 6 | 1.00 | 1.00 | True |
| `r05` | 7 | 1.00 | 1.00 | True |
| `r06` | 4 | 1.00 | 1.00 | True |
| `r07` | 4 | 1.00 | 1.00 | True |
| `r08` | 6 | 1.00 | 1.00 | True |
| `r09` | 4 | 1.00 | 1.00 | True |
| `r10` | 5 | 1.00 | 1.00 | True |
| `r11` | 4 | 1.00 | 1.00 | True |
| `r12` | 4 | 1.00 | 1.00 | True |
| `r13` | 4 | 1.00 | 1.00 | True |
| `r14` | 4 | 1.00 | 1.00 | True |
| `r15` | 3 | 1.00 | 1.00 | True |
| `r16` | 4 | 1.00 | 1.00 | True |
