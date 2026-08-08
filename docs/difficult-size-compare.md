# Difficult multi-suite size comparison

**Setup:** 139 queries across 6 suites; indexes reused (no re-embed). Arms: mix@450/350/300/250, budget_c@300.

## Macro (difficult only)

| Arm | Macro R@5 | Macro MRR | Soft52 R@5 |
|-----|-----------|-----------|------------|
| **mix_350** | **0.680** | **0.597** | 0.692 |
| budget_c_300 | 0.677 | 0.581 | 0.654 |
| mix_250 | 0.670 | 0.603 | 0.673 |
| mix_450 | 0.670 | 0.584 | **0.731** |
| mix_300 | 0.657 | 0.592 | 0.712 |

Δ macro R@5 vs mix@450: mix_350 **+0.01**, mix_300 **−0.013**, mix_250 **0.00**.

## Per-suite R@5 highlights

| Suite | mix@450 | mix@350 | mix@300 | Note |
|-------|---------|---------|---------|------|
| hard_v1 / hard_plus | 0.92 / 0.90 | same | same | size-invariant |
| soft_hard | 0.60 | **0.65** | **0.65** | smaller can help |
| paraphrase | **0.40** | 0.40 | 0.35 | 300 slightly weaker |
| adversarial | **0.53** | 0.53 | 0.47 | 300 weaker |
| soft_v1 | **0.73** | 0.69 | 0.71 | 450 still best soft |

## mix@300 regressions vs @450 (only 3)

- paraphrase: inspiration headed browser
- paraphrase: observe after session open
- adversarial: agent summary card vs dribbble distractor

## Real comparison verdict

1. **Hard symbol locate does not need 450** — flat across sizes.
2. Under **difficult macro**, **mix@350 ≈ best**; mix@300 is within −0.02 of 450 → still holds.
3. Soft-52 still prefers 450; hard/adversarial are the stress tests.
4. **Practical ship:** `MAX_CHARS=300` or **350** for a safer middle (won difficult macro).

Report: `out/difficult_compare/REPORT.md`
