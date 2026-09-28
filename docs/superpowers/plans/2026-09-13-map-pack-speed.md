# Map + Multi-Seed Pack Speed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut warm first-`map` and lean multi-seed `pack_context` latency sharply without regressing composite_v1 / multi_seed_v1 quality gates.

**Architecture:** Keep production tracers (`composite_v1`, `merge_seed_heatmaps` agreement+corridor). Win time by (1) stage instrumentation, (2) adaptive secondary-seed traces (full poly only when seed1 island does not already cover seed2/3), (3) shared repo runtime + parallel only for true full polys, (4) first-call embedder/DML warm + optional query→map cache. Agent policy: prefer 1 seed unless map shows distinct modules.

**Tech Stack:** Python, `pipeline/context_trace.py`, `trace_lab/multi_seed.py`, `trace_lab/composite_v1.py`, FastEmbed/ORT DirectML, existing bakeoff scripts.

**Spec:** Design approved in chat 2026-09-13 (research: FastCode 2-hop scout, Haystack parallel multi-query, Proximity approx cache, ORT DirectML warm).

## Global Constraints

- Do **not** replace `composite_v1` with BM25-only or naive max-merge.
- Do **not** keep embedder forever when no MCP clients (disconnect unload stays).
- Quality gate: re-run composite ship gate + multi-seed bakeoff fixtures; hard/F1 must not regress.
- Latency targets (warm, post Phase B/C):
  - `map` p95 steady **&lt; 250ms**; first-after-warm **&lt; 1.5s**
  - lean 1-seed pack p95 **&lt; 5s**
  - lean 3-seed pack p95 **&lt; 8s** (from ~15–20s)
- Surface `timing` + updated `sla` on pack/map_context responses.

## File map

| File | Responsibility |
|------|----------------|
| `packages/trace_lab/multi_seed.py` | Light secondary heatmap; coverage predicate; timing-friendly helpers |
| `packages/pipeline/context_trace.py` | `run_map_context` adaptive poly + stage timers; SLA targets |
| `packages/pipeline/mcp_response_lean.py` | Pass through `timing` / `sla` fields |
| `tests/test_multi_seed_v1.py` | Adaptive coverage + light heatmap unit tests |
| `tests/test_pack_expand_parallel.py` | Timing keys present under parallel |
| `scripts/live_tool_timing.py` | Extend with pack 1-seed / 3-seed arms |
| `docs/architecture/scubiee-reliability-issues.md` | R7 status update |

---

### Task 1: Stage timers in `run_map_context`

**Files:** `packages/pipeline/context_trace.py`, `tests/test_multi_seed_v1.py`

- [x] Add `timing: {load_repo_ms, poly_ms[], merge_ms, cards_ms, adaptive_skips}` to `run_map_context` return (and propagate via pack).
- [x] Unit test: keys exist on dual-seed map_context smoke (can monkeypatch poly to no-op).

### Task 2: Light secondary heatmap + coverage

**Files:** `packages/trace_lab/multi_seed.py`, tests

- [x] `seed_covered_by_heatmap(hm, seed_id, min_score=...)` — True if seed node (or same-file hot density) already in island.
- [x] `light_seed_heatmap(seed_id, graph, *, max_hops=2)` — hop-decay scores for wiring neighbors (reuse `_WIRE` / BFS).
- [x] Unit tests: covered seed → True; light heatmap includes seed + neighbor.

### Task 3: Adaptive multi-seed in `run_map_context`

**Files:** `packages/pipeline/context_trace.py`

- [x] Always full `poly` for seed1.
- [x] For seed2/seed3: if covered by seed1 heatmap → `light_seed_heatmap`; else full `poly`.
- [x] Parallelize only remaining full polys (`ThreadPoolExecutor`).
- [x] Env escape: `CTX_MULTI_SEED_ADAPTIVE=0` forces all full (A/B).
- [x] Record `adaptive_skips` in `multi_seed.extra` + `timing`.
- [x] Update multi-seed SLA target_ms to **8000** with honest hint.

### Task 4: Live timing script + doc

**Files:** `scripts/live_tool_timing.py`, reliability doc, release note `v0_3_76` if shipping

- [x] Add pack lean 1-seed and 3-seed timing arms.
- [x] Log verification row in `scubiee-reliability-issues.md` R7.
- [x] Bump package note when ready to ship.

### Task 5: Phase C (follow-up — after B green) → superseded by ten-second warm plan

See `docs/superpowers/plans/2026-09-13-ten-second-warm-ms-steady.md` (0.3.79).

- [x] Dummy DML encode on engine ready / MCP attach (attach warm pipeline).
- [x] Optional proximity query→map cache (`map_result_cache`).
- [ ] First-map p95 gate script — `scripts/warm_contract_acceptance.py`

### Task 6: Quality verification

- [x] `pytest tests/test_multi_seed_v1.py tests/test_reliability_master_plan.py -q`
- [ ] Existing composite / multi-seed bakeoff scripts (if fixtures present)
- [ ] Manual: same 3-seed pack query as reliability session — expect &lt; 8s warm with `adaptive_skips` ≥ 0

---

## Research anchors (do not re-litigate)

- FastCode: metadata / 2-hop scout before heavy reason ([arxiv 2603.01012](https://arxiv.org/html/2603.01012))
- Haystack MultiQueryEmbeddingRetriever: parallel queries + fuse
- Proximity: approximate retrieval cache ([arxiv 2503.05530](https://arxiv.org/html/2503.05530v1))
- ORT DirectML: first-run shader warm; reuse session

## Rollback

`CTX_MULTI_SEED_ADAPTIVE=0` restores prior full-poly-per-seed behavior.
