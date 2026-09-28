# Semantic Program Tracer — System Design

**Date:** 2026-09-05  
**Status:** approved — implementing  
**Sources:** `SCUBIEE_SEMANTIC_TRACER_RESEARCH.md`, plan `semantic_tracer_system_design`

## 1. Diagnosis

`ultimate_trace` was polytrace + ranking knobs, not research §34. On `verify_prod`:

| Arm | Hard | Must-rec | Prec | F1 |
|-----|------|----------|------|-----|
| polytrace | 3/10 | 0.917 | 0.734 | **0.784** |
| ultimate_trace | 2/10 | 0.776 | 0.767 | 0.729 |

Systemic failure classes:

| Code | Name | Example |
|------|------|---------|
| `intent_poison` | Seed chunk text flips intent / unlocks factions | `TOKEN_TTL`, `log("ok")` in paste |
| `no_dfg` | Cannot separate data spine from sink leaves | `log`/`track` vs `decode→resolve→lookup` |
| `faction_block` | Path faction blocks seed-reachable infra | search→`database.connect` |
| `rank_crush` | Ranking drops admitted musts below hot (0.45) | ultimate PPR/genericness |
| `no_slice_mask` | Cannot honor “pricing-only” / “no telemetry” | checkout siblings stay hot |
| `hop_truncate` | Wrong intent → hop_cap too small | “only care” → config → hop 2 |
| `missing_edge` | Call/resolve gap | attribute calls without Jedi |

**Invariant:** Fact engines decide *membership*. Ranking only *orders*. Knobs may demote; they must not erase DFG/call spine nodes without an explicit slice mask.

## 2. Product goal

Query (user paragraph) + seed anchor(s) → smallest useful behavioral subgraph as symbol/line heatmap with evidence. No LLM for program facts.

## 3. Architecture

```text
USER_QUERY (text only)     SEED_ANCHORS (file/symbol/line; text not for intent)
         |                            |
         v                            v
  policy/intent.py              Seed materializer
  policy/slice_mask.py                 |
         |                             v
         |                    facts/* (deterministic)
         |                             |
         +------------> engine/frontier.py (typed unscored edges)
                                   |
                                   v
                         engine/best_first.py + engine/rank.py
                                   |
                                   v
                         Heatmap (score, why, path, signals)
```

### Modules (`packages/trace_lab/`)

| Path | Role |
|------|------|
| `facts/symbols.py` | Symbol index wrappers |
| `facts/call_graph.py` | CALLS/CALLED_BY (AST + Jedi + optional Graphify) |
| `facts/dfg.py` | Def-use, param/return, attribute flow |
| `facts/cfg.py` | Light blocks/branches → CONTROLS |
| `facts/pdg.py` | Compose DATA ∪ CONTROL ∪ CALL |
| `facts/dispatch.py` | Registry/overrides from lsp_index |
| `facts/graphify_adapter.py` | Optional Graphify edges |
| `policy/intent.py` | Mode + excludes from **user paragraph only** |
| `policy/faction.py` | Factions + seed-closure override |
| `policy/slice_mask.py` | Drop excluded leaves before heat |
| `engine/frontier.py` | Typed candidate edges |
| `engine/best_first.py` | Expand by typed weights |
| `engine/rank.py` | Path reinforce, leaf genericness, teleport, optional PPR |
| `engine/heatmap.py` | Cell assembly |
| `arms/*.py` | Switchable bakeoff strategies |
| `failure_report.py` | Phase 0 FN/FP + exploration cost |

`polytrace` remains the baseline arm. `ultimate_trace` knobs live only as rank presets.

## 4. Edge types

Structural: `CALLS`, `CALLED_BY`, `IMPORTS`, `CONTAINS`, `OVERRIDES`, `DISPATCHES`  
Data: `PASSES_DATA_TO`, `READS`, `WRITES`, `PRODUCES`, `CONSUMES`  
Control: `CONTROLS`, `GUARDS`

Confidence tags on edges: `ast` | `jedi` | `graphify` | `dfg` | `cfg`.

## 5. Policy fixes

1. Intent/lexicon/faction unlocks use **user paragraph only**.
2. Seed-closure: CALL/DATA-reachable from seed within budget is not foreign by path alone.
3. Hot contract: admitted DFG-spine nodes stay ≥ 0.45 under `rank_default`.

## 6. Phases and ship gate

| Phase | Deliverable | Gate |
|-------|-------------|------|
| 0 | Failure harness | FN/FP classification reports |
| 1 | Baselines frozen | bm25, ast_propagate, polytrace documented |
| 2 | CallGraph + Jedi | must-rec ≥ poly on auth/checkout; F1 drop ≤ 0.02 |
| 3 | DFG slice | side-effect cases: spine hot, sinks cold |
| 4 | CFG + slice_mask | pricing-only / no-telemetry hard pass |
| 5 | Teleport | BM25 admit only with structural link |
| 6 | Rank presets | ship gate below |
| 7 | Learn-to-rank | deferred until FN corpus stable |

**Ship gate (MCP default):** hard ≥ polytrace, must-rec ≥ 0.90, F1 ≥ polytrace, forbidden-hot ≤ polytrace. Until then `CTX_TRACE_ENGINE` defaults to `polytrace`; winners opt-in via env.

## 7. Deferred

Joern/CPG, GNN, LLM Trace Director as primary path.
