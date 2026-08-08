# Retrieval orchestration — decide / implement / defer

**Date:** 2026-08-03  
**Context:** ChatGPT advice (GRASP, A-RAG, VecTree, confidence, graph expand) vs current Context Engine stage.

## Correct our stack (ChatGPT diagram was wrong)

```text
Query
  → (optional blind English polish — no repo cheats)
  → CodeRankEmbed query vec (FastEmbed + DML/CUDA/CPU)
  → Conductor fusion:
       BM25  ⊕  dense(FAISS+TurboQuant)  ⊕  Graphify affinity
  → min-rank + neighbor expand + D lexical/path rerank
  → hits (disk text is source of truth)
```

- **TurboQuant** = vector compression for FAISS, **not** an LLM.  
- We do **not** have a separate LLM DedRanker in the hot path.  
- Graphify is **fused in parallel**, not a post-stage after FAISS only.

## Aim at this stage

1. Soft/agent queries work without cheating query rewrite.  
2. Keep search **~sub-300ms warm** on laptop DML.  
3. Avoid laptop-melting / dual-DML / full GraphRAG rebuilds.  
4. Prefer **policy** (when to expand) over new embed models.

## Map advice → our code → decision

| Advice | Already have? | Decision |
|--------|---------------|----------|
| **GRASP** — plan which retriever | `query_state` / `path_likeness` / `retrieve_R_complex` (SOFT→Hippo, SYMBOL→D) | **IMPLEMENT now:** wire `engine.search` → `R_complex` (was stuck on `D_rerank`) |
| **Confidence stop** | `channel_peakiness`, gated floor | **Thin slice later;** measure first — early-stop dense-only risks soft misses |
| **A-RAG tools** | MCP `search_code` / `status` / `sync` | **Defer:** split `keyword_search` / `graph_expand` after planner proves value |
| **VecTree hierarchy** | AST chunks + symbols already | **Defer:** big index reshape; current chunk+D enough for stage |
| **Adaptive chunk size** | `max_chars` / fast mode | **Defer** |
| **Better adaptive graph hops** | fixed `neighbor_files` + Hippo dual-seed | **Partial via R_complex Hippo on SOFT;** deeper adaptive hops later |
| **Full GraphRAG** | — | **Do not implement** |

## Implement this PR slice

1. `WarmSearchEngine.search` calls `retrieve_R_complex` (env override `CTX_RETRIEVE=D|R_complex`).  
2. Record `query_state` + retrieve source in `_last_timings`.  
3. A/B bench: soft queries + hard queries — quality top-5 + latency D vs R_complex.

## Success criteria

- Soft suite quality ≥ baseline D (ideally >).  
- Hard suite quality not regressed.  
- Soft latency acceptable (Hippo may cost more; must stay <~500ms avg warm if possible).

## A/B results (2026-08-03, packages index, DML warm)

| Suite | D_rerank | R_complex | Δ |
|-------|----------|-----------|---|
| Soft quality | 8/10 | 8/10 | 0 |
| Soft avg ms | ~485* | ~135 | faster (warm bias on 2nd) |
| Hard quality | 4/4 | 4/4 | 0 |
| Hard avg ms | ~54 | ~90 | +36ms (graphify floor cost) |

\*First suite pays more cold-path variance; treat latency as directional.

**Misses (both modes):**  
1. “notice repo changed without scanning…” → Graphify `detect.py`/`watch.py` seeds dominate; Merkle/root_probe not recovered.  
2. “search usable while index catching up…” → generic BM25/dense index modules; not `hot_patch`.

**Conclusion:** Wiring R_complex is still correct (real SOFT→Hippo path). Quality win needs better soft seeds / confidence retry — not Full GraphRAG.

## Slice 2 — `R_plan` (implement + test)

1. **BM25-lead** when `query_state=SYMBOL` and `path_likeness ≥ 0.55` (`retrieve_D_bm25_lead`).
2. Else `R_complex`; if SOFT and top-1/top-2 score margin flat → **keyword/bigram BM25 probe** (query tokens only) → merge pool → D rerank.
3. Engine default: `CTX_RETRIEVE=R_plan` (override `D|R_complex|X_soft`).

### A/B results (slice 2)

| Suite | D | R_complex | R_plan |
|-------|---|-----------|--------|
| Soft quality | 8/10 | 8/10 | **9/10** |
| Soft avg ms | ~439 | ~123 | ~166 |
| Hard quality | 4/4 | 4/4 | 4/4 |
| Hard avg ms | ~51 | ~85 | ~85 |

**Remaining soft miss:** “notice repo changed without scanning…” → Graphify `detect`/`watch` dominate; BM25 probes also rank `detect.py` first (no merkle/root_probe lexical hit from plain English). Not fixed without synonym/seed work.

Raw: `out/bench_retrieve_planner_ab.json`.
