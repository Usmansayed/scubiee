# Semantic tracer R&D synthesis (Cycles 1–3 + fuse)

**Date:** 2026-09-06  
**Artifact:** `semantic_tracer_fuse` (opt-in research arm)  
**Production default:** still `composite_v1`

## What we learned

| Mechanism | Evidence | Keep? |
|-----------|----------|-------|
| Graph membership (composite) | Ground truth; required | **Yes** |
| Query/seed/edge comparator in best-first | must@10 ↑ on hard/prod; F1/prec flat-to-up | **Yes** |
| Path polish (light) | Tied to v1 gains | **Yes** |
| Live trace centroid + hub penalty | Neutral-to-slight; cheap with fast edge_sim | **Yes** (in fuse) |
| Info-gain skip | Soft filter; no harm observed | **Yes** (lite) |
| Strict embed teleport | Prod F1 0.878→0.835; hard F1↓ prec↓ | **No** (ablation only) |
| Pure vector_only | Acc 0 on hard | **No** |
| Loose hybrid_teleport | Must↑ but prec collapse | **No** for default |

## Winning composite recipe (`semantic_tracer_fuse`)

```text
membership (_membership_edges)
  → SemanticComparator (node+trace, hub penalty, fast edge_sim)
  → semantic_best_first (priority from edge_sem; mild heat tint)
      + refresh_trace every 3 admits
      + info_gain_stop
  → path polish (light)
  → apply_rank_composite (DFG + sink)
  → heatmap
```

Teleport is **off by default**. Ablation arm: `semantic_tracer_fuse_teleport`.

## Bakeoff snapshot

### verify_prod
| Arm | Acc | F1 | Must@10 |
|-----|-----|----|---------|
| composite_v1 | 0.90 | 0.873 | 0.923 |
| semantic_tracer_v1 | 0.90 | **0.878** | **0.932** |
| fuse (no teleport) | 0.90 | **0.878** | **0.932** |
| fuse+teleport | 0.90 | 0.835 | 0.932 |

### verify_hard
| Arm | Acc | F1 | Must@10 |
|-----|-----|----|---------|
| composite_v1 | 0.42 | 0.778 | 0.805 |
| semantic_tracer_v1 | 0.42 | 0.778 | **0.814** |
| fuse (no teleport) | 0.42 | 0.778 | 0.807 |
| fuse+teleport | 0.42 | 0.765 | 0.807 |

Ship gate (must↑ + F1/prec/acc bounds): **not met**. Ranking quality improved; FN recovery via teleport not yet precision-safe.

## Recommendation

1. Keep **`composite_v1`** as MCP/CLI default.  
2. Keep **`semantic_tracer_fuse`** (= comparator + centroid/hub + info-gain, no teleport) as the research composite for further cycles.  
3. Next: multi-rep behavior docs (Cycle 3) or **stricter** teleport with must_not-aware admission — not looser ANN dumps.
