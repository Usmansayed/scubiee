# Semantic Tracer v1 — Cycle 1 Design

**Date:** 2026-09-06  
**Status:** Cycle 1–3 lite + `semantic_tracer_fuse` implemented (research arm)
**Mission:** R&D semantic tracer using embeddings as **comparators** inside expansion, not post-hoc island rescore.

## Thesis

```text
Graph membership  = what is allowed
Semantic compare  = what to prefer among legal hops
Heatmap           = fused relevance map
```

Arm name: `semantic_tracer_v1`. Production default remains `composite_v1` until ship gate.

## Cycle 1 pipeline

```text
seed + query
  → TraceSpec
  → call/DFG edges (shared with composite_v1 cache)
  → membership filter (_membership_edges)
  → frontier
  → semantic_best_first (edge comparator priority)
  → path_sem polish
  → apply_rank_composite (DFG boost + sink demote)
  → heatmap
```

## Comparator formulas (Cycle 1)

```text
node_sem(nid)  = 0.6 * cos(q, nid) + 0.4 * cos(seed, nid)
edge_text      = "{src_symbol} --{rel}--> {dst_symbol}"
edge_sem       = 0.5 * cos(q, edge_text) + 0.5 * node_sem(dst)
struct_in      = parent_score * edge_weight * mode_boost * hop_decay^hop
priority       = struct_in * (0.35 + 0.65 * edge_sem)   # heap order only
stored_heat    = struct_in * (0.90 + 0.10 * edge_sem)   # mild tint
path_sem       = mean(node_sem along path[1:])
final          = min(1, stored_heat * (0.95 + 0.05 * path_sem))
```

Comparators primarily change **which legal hops expand first**; heat stays near structural so hot-threshold decisions remain meaningful.

## Modules

| Path | Role |
|------|------|
| `semantic_compare.py` | node/edge/path comparators over EmbedField |
| `engine/semantic_best_first.py` | comparator-guided best-first |
| `semantic_tracer_v1.py` | orchestrator + bind |

## Roadmap

| Cycle | Focus |
|-------|--------|
| 1 | Edge + path comparators on composite membership |
| 2 | Trace-state centroid + strict verified teleport |
| 3 | Multi-rep docs + info-gain stop |

## Non-goals (Cycle 1)

ANN membership, LLM expansion, MCP default flip, island-only α rescore as the main line.

## Ship gate (promote default later)

On `verify_hard` vs `composite_v1`: must-rec ↑ and F1 drop ≤ 0.02 and prec drop ≤ 0.03 and hard acc drop ≤ 0.05.
