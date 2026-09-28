# Semantic system tracer — verify_prod bakeoff (2026-09-05)

Board: `fixtures/trace-lab/verify_prod.json` (10 cases)  
Full JSON: `docs/superpowers/plans/2026-09-05-semantic-system-verify-prod.json`

## Summary

| Arm | Hard | Must-rec | Prec | F1 |
|-----|------|----------|------|-----|
| polytrace (default) | 3/10 | 0.917 | 0.734 | **0.784** |
| **callgraph_jedi** | **5/10** | **0.967** | 0.510 | 0.641 |
| dfg_slice / pdg / hybrid / rank_* | 2/10 | 0.967 | ~0.23 | ~0.36 |
| ultimate_trace | 2/10 | 0.776 | 0.767 | 0.729 |

## Ship gate

Required: hard ≥ poly, must-rec ≥ 0.90, F1 ≥ poly, forbidden-hot ≤ poly.

- `callgraph_jedi`: hard OK, recall OK, **F1 fails** (precision).
- `rank_default`: **fails** (hard + F1).

**Default remains `polytrace`.** Opt-in: `CTX_TRACE_ENGINE=callgraph_jedi` (or `system`).

## Wins vs polytrace

- `callgraph_jedi` hard-passes **p10 pricing-only**, **p28 webhook**, **p33 search** (poly fails).
- Policy: user-paragraph-only intent + excludes helps pricing/webhook.

## Next precision work

DFG arms over-admit (precision ~0.23). Need stronger sink demotion + slice_mask before enabling DFG in the default layered preset.
