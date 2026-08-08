# Budget allocation for fixed embedding windows

**Question:** Given a fixed ~450-character embed budget, how should we spend it?

**Finding:** At fixed budget, shifting spend toward **rare-identifier body fill** beats identity-heavy packing on soft locate. Shipped `mix` still leads overall (structured core + scored body), but the A→B→C ladder is the clean ablation.

## Setup

- Corpus: frontend-mcp, 3148 chunks (full re-enrich)
- Budget: **450 chars** | Embed seq: **512** | FAISS + TurboQuant 4-bit | `R_plan`
- Soft: 52 vague queries | Hard: 12 symbol queries

## Results

| Mode | Alloc (meta/sym/api/body) | Soft R@5 | Soft MRR | Hard R@5 |
|------|---------------------------|----------|----------|----------|
| skeleton | AST skeleton | 0.635 | 0.450 | 0.917 |
| card | meta-first card | 0.635 | 0.460 | 0.917 |
| budget_a | 40/30/20/**10** | 0.635 | 0.484 | **1.0** |
| budget_b | 25/25/20/**30** | 0.635 | 0.505 | **1.0** |
| budget_c | 20/20/10/**50** + rare-idents | **0.673** | **0.539** | **1.0** |
| mix (shipped) | card core + scored body | **0.731** | **0.564** | 0.917 |

Order: **mix > budget_c > budget_b > budget_a > card > skeleton**

## Insight

1. **Window size is not the bottleneck** (seq 128≡512 on mix). **Density / allocation is.**
2. Within a fixed budget, **more rare-identifier body** (A→C) monotonically improves soft MRR and lifts R@5 at C.
3. **Rare-ident fill** beats “first N body chars” as the body policy.
4. Production `mix` still wins soft — allocation presets are the scientific ladder; mix is the engineered winner.

## Modes

```text
CTX_COMPRESS=budget_a|budget_b|budget_c|mix|card|skeleton
CTX_COMPRESS_MAX_CHARS=450   # budget experiments used 450
```

Report artifact: `out/budget_alloc/REPORT.md`
