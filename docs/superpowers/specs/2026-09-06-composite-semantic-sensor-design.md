# Composite Semantic Sensor — Phase 0 Design

**Date:** 2026-09-06  
**Status:** Phase 0 implemented — bakeoff flat vs composite_v1; keep as opt-in scaffold, do not default  
**Parent research:** `SCUBIEE_SEMANTIC_TRACER_RESEARCH.md`, user prompt (vector as sensor)

## 1. Thesis

`composite_v1` remains structural ground truth (membership → best-first → DFG boost).  
Embeddings are a **semantic sensor**: they may rescore or soft-demote admitted nodes; they must not invent membership in Phase 0.

## 2. Roadmap (kill phases that lose bakeoffs)

| Phase | Focus | Ship question |
|-------|--------|---------------|
| **0** | Query + seed cosine; additive vs gate | Ranking lift without precision collapse? |
| **1** | Verified teleport / FN recovery | Cut false negatives? |
| **2** | Trace state / edge / path / stop | Better expansion? |
| **3** | Multi-rep indexes + noise | Better representations without LLM? |

## 3. Phase 0 architecture

```text
run_composite_v1(case, …)  →  island heatmap
        ↓
semantic_sensor (EmbedField)
  sem = 0.6 * q_sim + 0.4 * s_sim
  mode=add  → score' = min(1, struct + α·sem)     α=0.15
  mode=gate → demote if sem < τ unless seed/spine  τ=0.25, factor=0.35
        ↓
Heatmap strategy=composite_semantic_{add|gate}
```

**Invariant:** same node set as `composite_v1` (no adds/drops). Only scores + `why` tags change.

### Spine protection (gate)

Never demote:

- seed
- cells with `dfg_boost` in `why`
- cells with `len(path) ≥ 2` and `struct ≥ 0.45`

### Modules

| Path | Role |
|------|------|
| `trace_lab/semantic_sensor.py` | Pure blend + additive/gate |
| `trace_lab/composite_semantic.py` | Wrapper arm + bind |
| `trace_lab/semantic_index.py` | Facade over `EmbedField`; future fingerprint/model/rep-version |

### Arms

- `composite_semantic_add`
- `composite_semantic_gate`

Registered when `EmbedField` is available (`compile_bundle(..., with_embed_power=True)` / prod_eval).  
**MCP/CLI default stays `composite_v1`.** No engine flip in Phase 0.

## 4. Keep / kill gate

Vs `composite_v1` on the same gold board:

- Keep a mode only if (must-rec ↑ **or** hard ↑) **and** F1 drop ≤ 0.02 **and** precision drop ≤ 0.03.
- Else kill that mode; document recommendation. Do not change production default.

## 5. Non-goals (Phase 0)

ANN membership, dumping vector top-k into heatmap, LLM expansion, multi-rep indexes, centroids, path scoring, semantic stopping, mutating `run_composite_v1` itself.

## 6. Success

Evidence package: working arms, A/B metrics, written keep/kill recommendation.
