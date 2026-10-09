# Size ladder — how small without losing quality?

**Question:** Can we shrink the mix char budget and keep locate quality?

**Answer:** Yes — **~300 chars** is the knee. Soft R@5 stays within −0.02 of mix@450; hard R@5 unchanged. Below 250 quality falls off.

## Results (frontend-mcp, seq=512, soft52 / hard12)

| Arm | Avg chars | Soft R@5 | Soft MRR | Hard R@5 | Embed s | vs mix@450 |
|-----|-----------|----------|----------|----------|---------|------------|
| mix@450 | 414 | **0.731** | 0.564 | 0.917 | 111 | baseline |
| mix@350 | 329 | 0.692 | 0.526 | 0.917 | 85 | −0.039 |
| **mix@300** | **288** | **0.712** | **0.549** | **0.917** | **70** | **−0.019** ✓ |
| mix@250 | 241 | 0.673 | 0.546 | 0.917 | 60 | −0.058 |
| mix@200 | 175 | 0.615 | 0.440 | 0.917 | 51 | −0.115 |
| budget_c@300 | 284 | 0.654 | 0.522 | **1.0** | 73 | −0.077 |
| budget_c@250 | 266 | 0.615 | 0.491 | **1.0** | 68 | −0.115 |

Knee rule: soft R@5 ≥ mix@450 − 0.02 and hard R@5 ≥ 0.9 → **mix@300**.

## Research insights worth pursuing

1. **Information density ≫ window size** (already shown: seq 128≡512).
2. **Fixed-budget allocation**: rare-ident body spend beats identity-heavy (budget_c > budget_a at 450).
3. **Size knee at ~300 for mix**: ~30% fewer chars, ~37% faster embed, soft quality ≈ flat.
4. **Non-monotonic 350 vs 300**: mix@300 beat mix@350 slightly — suggests mid-cut field boundaries matter; worth studying *which fields get truncated* at each budget.
5. **Tight windows favor structured mix over pure % budgets**: budget_c loses to mix when both are ≤300.
6. **Hard symbol locate is almost budget-invariant** down to 200 — soft NL is the sensitive metric.

## Recommended next experiments

| Experiment | Hypothesis |
|------------|------------|
| Field ablation at 300 | Drop Related/Imports/Types first; keep File+Symbol+Intent+Rare |
| Adaptive budget | Short symbols → 200; long modules → 300–350 |
| Cross-model | Repeat ladder on another embedder (Jina/Qwen) — is 300 universal? |
| Ship default | `CTX_COMPRESS_MAX_CHARS=300` with mix; confirm on 2nd repo |

## Artifact

`out/size_ladder/REPORT.md`
