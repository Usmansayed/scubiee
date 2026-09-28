# Novel Context-Tracing Strategies Implementation Plan

> **For agentic workers:** Implement task-by-task against `packages/trace_lab`. Run `python -m trace_lab` and `pytest tests/test_trace_lab.py tests/test_trace_lab_novel.py` after the new tracers are registered. Do not change MCP `map` / production locate in this pass.

**Goal:** Add genuinely new tracing algorithms to the trace-lab simulator, score them on the gold heatmaps, and keep any method that beats lexical search without exploding into hubs.

**Architecture:** Research-inspired tracers live in `packages/trace_lab/novel.py` and register through `default_tracers()`. They consume the existing AST graph + BM25 index. No LLM, no embeddings, no daemon — the sim stays deterministic.

**Tech Stack:** Python 3.10+, numpy, existing `trace_lab` corpus/graph/metrics, `conductor.fusion_math.fuse_combmnz`.

**Spec:** This document (research + design). Gold cases remain `fixtures/trace-lab/cases/*.json`.

## Global Constraints

- No new runtime dependencies.
- Strategies must be deterministic and finish in milliseconds on the 19-node fixture.
- Do not put gold labels into a tracer.
- Native tests only; do not require a warm Scubiee engine.
- Invented methods may be inspired by papers but must not be a straight reimplementation of today's `ast_propagate`.

---

## Research (what the literature actually says)

Coding agents fail at *completeness under a budget*, not at search. The useful papers split into four ideas:

1. **Diffuse, don't BFS.** HippoRAG / HippoRAG 2 (Gutiérrez et al., NeurIPS'24 / 2025) replace hop policies with Personalized PageRank. Damping ≈ 0.5 keeps mass near seeds. Inverse-frequency penalties stop ubiquitous entities (logger, `get`) from dominating. HippoRAG 2 also dual-seeds phrase nodes *and* passage nodes.

2. **Make the walk query-aware.** QASA (2026) and spreading-activation Graph-RAG show that query-blind traversal is the main precision leak: the question picks seeds, then structure walks everywhere. A per-neighbor semantic gate (even lexical cosine) prunes junk *during* expansion. SeedER's k-hop-with-filtering keeps only the top-b neighbors per hop.

3. **Slice, don't retrieve.** Weiser (1984) and Horwitz–Reps–Binkley system dependence graphs: a slice is the statements that *affect* or *are affected by* a criterion. Forward slice = callees/data-out; backward slice = callers. GraphCoder (2024) adds decay-with-distance on control/data edges. RepoGraph (2024) does line-level def/ref ego-graphs for SWE-bench. RANGER (2025) explores the graph with MCTS when the name is known and falls back to embeddings when it isn't.

4. **Minimal sufficient subgraph.** Information-bottleneck GraphRAG and COSMOS (ACL 2026) treat retrieval as "smallest connected subgraph that still explains the query." Path-consensus / Steiner bridges promote generic-named intermediates that sit on the route between the seed and a lexical island.

What current Scubiee `map` does: BM25+dense ranking plus 1-hop neighbors. What the first trace-lab hybrid does: best-first decay with a query-mix knob. Both still mix **structure** and **vocabulary** on every edge, which is why `User.lookup` (no query tokens, 3 hops) goes cold and why a log-query can still leak into `verify` via reverse hub edges.

## Logic (what we should invent)

The product question is: *from this seed, what else must the agent read?* That is closer to a **demand-driven resolver** than to search.

**ObligationTrace (new).** Treat the seed like a compiler. Unresolved names in the seed (`JwtService`, `extract_bearer`) are *obligations*. Satisfying them opens a node and emits new obligations (`decode`, `TOKEN_TTL`, `resolve`). Side-effect names (`log`, `track`, `get`) are *effects* and are followed only if the query names them. No query-mix on the main path — generic names are the point. Intent only changes which obligation kinds are live (FLOW vs CONFIG vs SITE).

**HubShadow (new).** Two PPRs: one personalized on the seed, one personalized on high-degree infrastructure. Heat = `relu(PPR_seed − λ PPR_hubs)`. Hubs that the query explicitly names are removed from the shadow set. This is contrastive gravity, not a hop cap.

**IntentSlice (new).** Classify the query, then mask relations:
- FLOW (`how does` / `work`) → forward `calls`+`uses`+`contains`
- CONFIG (`where is` / `configured`) → `uses` + query-similar calls, 2 hops
- SITE (`write log`) → only neighbors whose symbol/path overlaps the query
- ENTRY (`login`) → FLOW from the caller seed

**BridgeHeat (new).** Lexical islands (BM25) that are graph-reachable from the seed without crossing infrastructure become terminals. Nodes on shortest seed→island paths get heat even if their names are generic. Billing is a lexical island that is *not* reachable without the HTTP hub, so it stays cold.

**SpreadGate.** Spreading activation (accumulate, not max) with a lexical gate on every push. Tests whether HippoRAG-style diffusion beats best-first max.

**PPR-IDF.** Directed PPR, damping 0.5, transition mass penalized by target degree. The HippoRAG baseline in our own graph.

**AgreeFuse.** CombMNZ of Obligation + PPR-IDF + IntentSlice. Agreement is a relevance prior (Lee / Fox & Shaw): billing appears in one list, `decode` in two structural lists.

Success on the existing gold board:

| Case | What a winning novel method must do |
|---|---|
| auth-flow | Recover `verify`/`decode`/`resolve`/`lookup`; leave billing+logger cold |
| login-entry | Walk callees from `login` |
| token-expiry | Hit `TOKEN_TTL`; do **not** dump `User.lookup` |
| auth-log-write | Hit `log`; do **not** dump `verify`/`decode` |

---

## Files

- Create: `packages/trace_lab/novel.py` — all new tracers
- Create: `tests/test_trace_lab_novel.py` — gold assertions for new methods
- Modify: `packages/trace_lab/retrieve.py` — add `query_intent()`
- Modify: `packages/trace_lab/strategies.py` — register novel tracers in `default_tracers()`
- Modify: `docs/superpowers/plans/2026-09-04-trace-lab-novel-strategies.md` — this plan

---

### Task 1: Query intent + novel tracers

**Files:**
- Create: `packages/trace_lab/novel.py`
- Modify: `packages/trace_lab/retrieve.py`
- Modify: `packages/trace_lab/strategies.py`

- [ ] Add `query_intent(query) -> "flow"|"config"|"site"|"entry"`
- [ ] Implement `obligation_trace`, `hub_shadow`, `intent_slice`, `bridge_heat`, `spread_gate`, `ppr_idf`, `agree_fuse`
- [ ] Register them in `default_tracers()`

### Task 2: Tests + sim board

**Files:**
- Create: `tests/test_trace_lab_novel.py`

- [ ] Obligation recovers generic auth names and does not hot-rank billing
- [ ] Intent/obligation SITE query keeps logger and not `JwtService.verify`
- [ ] Token-expiry hits `TOKEN_TTL` without `User.lookup` in the forbidden-hot set
- [ ] HubShadow has fewer forbidden FPs than undirected BFS
- [ ] At least one novel method has higher mean F1 than `bm25_body`
- [ ] `python -m trace_lab` still prints the comparison table including the new names

### Task 3: Run and keep winners

- [ ] Run the sim, record the table in the plan's Results section
- [ ] If a novel method is dominated on every metric by `ast_propagate`, leave it registered anyway — the point of the board is to *see* the miss

---

## Results

First board after implementation (`python -m trace_lab`, 4 gold cases, 19 nodes):

```
strategy                 F1   recall   prec   nDCG   tokP   inv  FP!  FN
obligation            0.910    1.000  0.850  0.973  0.878     0    0   0
intent_slice          0.910    1.000  0.850  0.982  0.878     0    0   0
ast_propagate         0.897    0.958  0.854  0.977  0.879     0    0   1
hybrid                0.897    0.958  0.854  0.977  0.879     0    0   1
spread_gate           0.897    0.958  0.854  0.974  0.876     0    0   1
agree_fuse            0.889    1.000  0.825  0.962  0.859     0    0   0
graphify_propagate    0.695    0.646  0.817  0.823  0.861     0    0   6
bridge_heat           0.682    0.750  0.738  0.913  0.765     0    2   4
bm25_expanded         0.646    0.646  0.750  0.767  0.761     1    1   6
ppr_idf               0.572    0.417  1.000  0.872  1.000    14    0   9
hub_shadow            0.572    0.417  1.000  0.917  1.000     3    0   9
ast_undirected_bfs    0.560    1.000  0.411  0.895  0.466    13   11   0
tfidf                 0.459    0.458  0.475  0.661  0.578     6    4   8
bm25_body             0.427    0.583  0.380  0.651  0.416     8    6   7
```

Takeaways:

- **ObligationTrace wins.** Demand-driven name resolution recovers every must-node (including generic `decode` / `resolve` / `lookup`) with zero forbidden FPs. That is the method to productize next.
- **IntentSlice** matches obligation F1 and slightly better nDCG because the extra caller hop ranks `login` on auth-flow.
- **Query-mix propagate / hybrid** still miss one must-node (`User.lookup`, 3 hops, no query tokens). Mixing vocabulary into every edge is the wrong default for FLOW queries.
- **PPR-IDF and HubShadow** are surgically precise (prec 1.0, 0 forbidden FPs) but under-expand on this small graph (recall 0.42). Keep them as precision arms, not as the primary tracer. HubShadow does cut inversions vs raw PPR (14 → 3).
- **BridgeHeat** helps when lexical islands exist near the seed; billing still leaks on some cases (2 forbidden FPs).
- **AgreeFuse** keeps recall 1.0 but slightly dilutes precision. Useful as a fallback ensemble, not the primary.

17 pytest tests pass (`tests/test_trace_lab.py` + `tests/test_trace_lab_novel.py`).

---

## PolyTrace (flagship, 14-case board)

**New technology:** multi-channel tracing, not search. Channels are simulated LSP (defs/refs/registry/overrides), AST call/use edges, faction-allied graph hops, and TF-IDF confirm for CONFIG only.

Expanded fixture: 37 nodes, 14 gold cases covering generic names, lexical traps, hubs, dynamic `bind`→`handle` dispatch, inheritance, same-folder isolation, LSP references, and reverse billing/auth traps.

Second board (`python -m trace_lab --no-graphify`, 14 gold cases, 37 nodes):

```
strategy                    F1  recall    prec    nDCG    tokP   inv  FP!   FN
polytrace                1.000   1.000   1.000   0.998   1.000     0    0    0
obligation               0.895   0.898   0.929   0.978   0.942     0    0    4
ast_propagate            0.891   0.875   0.944   0.973   0.951     0    0    5
bm25_body                0.567   0.708   0.517   0.781   0.514     8    6   15
```

PolyTrace is **1.000 mean F1 and 1.000 must-recall** with 0 forbidden FPs and 0 FNs. Obligation drops on the new traps (registry dispatch, HTTP ally on charge, refs-only TTL). That is the overfitting check: the previous winner does not hold the 95% gate on a 14-case board.

27+ pytest tests pass (`test_trace_lab.py` + `test_trace_lab_novel.py` + `test_polytrace.py`).

