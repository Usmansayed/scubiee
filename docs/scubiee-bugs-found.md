# Scubiee MCP — bug status (verified on the real Kiro MCP)

Build **0.3.132**, project `ce_3536ac8e8e83bb8e4d888db37847729c`, Windows, engine `:8765`.
Status verified by calling the actual `@scubiee/*` Kiro MCP tools (session
`kiro@conn-200830`), not a harness. This file tracks only what is **still open**;
fixed items are listed compactly at the bottom for history.

## Current verdict

All 8 MCP tools (gate, status, map, pack_context, expand_context,
collect_hot_context, workspace, expand) work correctly with reasonable warm
response times. No open **correctness** bug in the tool surface. One graph-coverage
gap is open (cross-file call edges on incremental catch-up), plus the known
latency characteristics of the graph lane. Everything else previously logged is
fixed and re-verified live.

---

## OPEN

### OPEN-1 — cross-file `calls` edge from a newly-changed file is missed by the single-file graph catch-up
**Severity:** medium (graph coverage, not a crash; hot lane unaffected).

**Repro (real MCP + direct catch-up):** add a function that really calls an
existing indexed symbol (`zz_edgetest_caller_fn` → `sweep_stale_temps(Path("."))`),
dirty the file, let the incremental graph catch-up run, inspect the merged graph:
- ✅ node created, ✅ `zz_edgetest → graph_merge_worker (imports_from)`,
  ✅ `zz_edgetest → zz_edgetest_caller_fn (contains)`
- ❌ **0 edges out of `zz_edgetest_caller_fn`** — the `calls` edge to
  `sweep_stale_temps` never formed. `expand_context(callers)` on
  `sweep_stale_temps` does **not** list the new caller.

**Root cause (hypothesis):** the catch-up re-extracts only the one changed file,
so cross-file call-target resolution (binding the callee to its definition in
another file) has no scope to resolve against — the module-level `imports_from`
edge is created but the function-level `calls` edge is not. Would presumably form
on a full rebuild.

**Impact:** after editing a file to add a call to an existing symbol,
`expand_context(callers)` on that symbol may omit the new caller until a full
rebuild. Search / map / pack (hot lane) are unaffected.

**Fix direction (not yet done):** teach the single-file catch-up to resolve call
targets against the existing graph's symbol table (the import edge already proves
the link is known at module level). Needs: reproduce on a full rebuild to confirm
it's the incremental path, then edge-count diff before/after.

### OPEN-2 — graph-lane freshness lags the hot lane after a save (partly by design)
**Severity:** low (expected trade-off; tools stay honest).

After a save, `map`/`search`/`pack seed` reflect the change in **~1–3 s** (hot
BM25+dense lane). `expand_context` edges lag because (a) `CTX_KEEPER_DEFER_WHILE_CLIENTS=1`
defers keeper sync while an IDE/MCP client is connected, and (b) the graph
catch-up is debounced. During the gap `expand_context` returns *empty*
(`empty_reason:"no_edges"`) — never wrong edges — and `status` reports
`index_fresh:false` / `agent_ready:"stale"`. When the catch-up runs it is ~4.3 s.
Not a bug; documented so the behavior is known. Lever: `CTX_KEEPER_DEFER_WHILE_CLIENTS=0`
(trades session CPU for faster graph freshness). Deeper latency work (incremental
AST bake / two-phase refresh) is tracked in `docs/scubiee-perf-investigation.md`.

---

## FIXED — verified live on the real Kiro MCP (2026-09-28)

| id | issue | verification |
|---|---|---|
| BUG-2 | `status(detail=full)` took ~23 s (redundant `/health` round-trip) | now **~1.5 s** warm; single health call |
| BUG-1 | `pack_context include_bodies=1` dumped whole classes (loc not clamped) | seed `loc:156-275` + `full_loc:156-2108`, body capped — clamp works |
| BUG-B | wrong `project_id` returned bare `"0"` | now `ok:false, bad_project_id:true, next_action:"gate(...)"` + hint |
| BUG-C | inconsistent error envelope on missing/empty query | `ok:false error:"query required"` + hint |
| OBS-1 | `warm_deadline_ms` showed stale 30000 not configured value | now `warm_deadline_ms:90000, warm_deadline_source:"env"` |
| OBS-4 / BETA-12 | `expand_context direction=config` ambiguous empty | now returns a specific `empty_reason` (`already_expanded` / `no_edges`) |
| OBS-2 | leftover `sync_live_*` / `zz_*` probe dirs in the ledger | none on disk; ledger clean |

Error paths (all clean, actionable envelopes): empty query → `query required`;
unknown node → `node_unresolved`; bad expand handle → `unknown handle …`; wrong
project_id → `bad_project_id`.

Performance fixes this cycle (details + before/after in
`docs/scubiee-perf-investigation.md`): graph catch-up 6.1 s → ~4.3 s
(`MinHash.update_batch` + `normalize_id` cache), `build_lsp_index` 4.0 s → 0.9 s
(register-call short-circuit), HTTP grep 14.6 s → ~2 s (+ correctness), grep_ident
4.75 s → ~1.3 s.

## Warm response times (real Kiro MCP, server-reported `elapsed_ms`, re-measured 2026-09-28)

| tool / config | time |
|---|---|
| gate, status(gate/summary) | instant |
| status(full) | ~1.5 s |
| map cold topic | **289–615 ms** |
| map cache repeat | **14 ms** (`cache:"last"`) |
| pack_context lean single-seed | **112 ms** |
| pack_context multi-seed / include_bodies | 0.08–0.9 s |
| expand_context (any direction) | **1.8–33 ms** |
| collect_hot_context / expand / workspace | fast (<0.2 s) |

## Sync reflection latency — how fast each tool sees a change (measured, warm engine)

Method: modify an already-indexed file (new symbol), POST `/v1/dirty`, poll each
surface until the change appears.

| change → tool | latency | notes |
|---|---|---|
| modify → `/v1/search` sees new symbol | **343 ms** | hot BM25 lane, polled at 250 ms |
| modify → `map` sees new symbol (rank 1) | **~1–2 s** | hot BM25+dense lane |
| modify → old symbol evicted from map | **immediate** on this run | dense warm ⇒ hot patch was `patchable`, old chunk tombstoned |
| new file → searchable in map | ~1–3 s | `DirWatch` + hot patch |
| save → `expand_context` edges (graph lane) | **deferred + ~4.3 s catch-up** | `CTX_KEEPER_DEFER_WHILE_CLIENTS=1` holds it while a client is connected; returns empty (`no_edges`) + `status.index_fresh:false` until it commits. See OPEN-1/OPEN-2. |

Bottom line: **hot-lane tools (search/map/pack seed) reflect a change in ~0.3–3 s.
Graph-edge tools (expand_context) lag — deferred while a client is connected, then
~4 s — and stay honest (empty, not stale) meanwhile.** Note: eviction of an old
symbol on modify is prompt when dense is warm; it can lag if the embedder is
demoted (the patch then falls back to the slower full reconcile).
