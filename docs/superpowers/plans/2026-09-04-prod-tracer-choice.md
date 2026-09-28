# Production-like tracer choice

## Recommendation

**Ship `polytrace` as the default production tracer** when the agent supplies:
1. a short detailed paragraph of intent, and  
2. two seed code chunks (primary + secondary anchor).

On `verify_prod` (10 cases, that format):

| arm | hard | must-rec | prec | F1 |
|-----|------|----------|------|----|
| **polytrace** | **3/10** | **0.917** | **0.734** | **0.784** |
| semantic_trace | 1/10 | 0.69 | 0.45 | 0.53 |
| recall_belt | 0/10 | 1.00 | 0.12 | 0.21 |
| recall_fuse | 0/10 | 1.00 | 0.12 | 0.21 |

Detailed prompts lift polytrace must-rec from ~0.82 (vague hard-50) to **~0.92** — already in the 90%+ band without an LLM.

**Keep `recall_belt` / `recall_fuse` as the coverage floor** for a later dual-budget product (widen → prune). Do **not** ship the 0.8B director as the main path.

## How to run

```text
python -m trace_lab --verify-prod
```

Board: `fixtures/trace-lab/verify_prod.json`  
Results: `docs/superpowers/plans/verify-prod-results.json`
