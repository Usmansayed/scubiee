# Scubiee performance & sync timings — live measurement

Measured against the **live 0.3.144 engine** on Windows + DirectML (DML), real
MCP surface, after `scubiee setup --repair` restored `DmlExecutionProvider`
(ORT 1.24.4). Engine: `http://127.0.0.1:8765`, project
`ce_b867ad869c948914bf7c8e8640a2a5e3`, ~8925 chunks.

Two measurement planes:
- **Transport** (`/health`, backs the `gate`/`status` tools): raw HTTP timing.
- **Tool compute** (`map find`/`focus`): in-process via `scripts/_qa_profile.py`
  and `scripts/perf/_sync_timing.py`, which call `map_v3_server.tool_map`
  directly on a persistent engine connection (excludes stdio-bridge/process
  startup, so these are engine+keeper latencies, not client spawn cost).

## Tool response times

| Signal | Cold first call | Warm steady-state | After 65s idle (connected) |
|--------|-----------------|-------------------|----------------------------|
| `gate` / `status` (`/health`) | n/a (up at ~9s) | **p50 2ms, p99 92ms** | p50 2ms (unchanged) |
| `map find` | **2321ms** (first query after warm) | **~200–600ms** (p50 ~220ms quiet, ~500–600ms under concurrent sync load) | **310ms** (≈steady) |
| `map focus` | 92ms | **79–92ms** | ~90ms |

Notes:
- The first `find` after a fresh warm pays a **one-time ~2.1s** cost (query-embed
  path warmup + AST/file cache fill). Subsequent finds are ~220ms on a quiet
  engine; expect ~500–600ms when the engine is concurrently indexing/syncing
  (the dense search contends with background embed work). `focus` has no dense
  step so it is fast from the first call.
- `find` warm latency is dominated by the engine dense search (`_http` ≈
  175–200ms/call); the map-server assembly around it is small.
- `graph`/`related` fold into `find` on the shipped `{find, focus}` surface.

## Cold start (engine was fully stopped)

Clean restart, milestones anchored at `engine start`:

| Milestone | Time |
|-----------|------|
| `/health ok` (process up) | **9.1s** |
| `soft_search_ready` (BM25 + warm index usable) | **9.1s** |
| `dense_ready` (DML model loaded, full dense retrieval) | **24.5s** |

So an agent attaching to a cold engine gets a **usable soft response at ~9s**
and **full dense at ~24.5s**. The DML model load is the bulk of the gap.

### Cold-start fix — dense no longer trails soft by ~15s

Investigation showed the embedder build itself is **only ~2.5s** (ORT/DirectML
session create). The ~15s dense-behind-soft gap was **not** the model load — it
was a scheduling/GIL-contention bug:

1. The eager dense prewarm was scheduled **after** `_reconcile_offline` and
   `_start_keeper`, which trigger a ~26s **AST-bundle revalidation** +
   graph-catch-up. The prewarm's ORT session build queued behind that work.
2. That AST rebake's in-process merge/export is Python-heavy and GIL-bound, so
   even once prewarm started it was starved by the rebake thread.

Fixes (`ce_service.py` + `sync_loop.py`):
- **Kick the eager prewarm right after `warm_state = "ready"`** — before the
  keeper, offline reconcile, and AST work — so the DML session build (which
  releases the GIL during native ORT work) overlaps instead of waiting. Default
  delay dropped 0.5s → 0.1s.
- **Gate the AST revalidation on embedder-loaded**: `_start_ast_revalidate`
  returns early while a prewarm is in flight (`prewarm_busy_stamp_active()` and
  not `embedder_is_loaded()`), so the ~20s rebake no longer starves the embedder
  during the cold window. The bundle is served stale meanwhile (already the
  request-path behavior) and rebakes on the next keeper tick once dense is warm.
  Opt out `CTX_AST_REVALIDATE_GATE_ON_EMBED=0`.

Result (same cold-start measurement, DML):

| | before | after |
|---|--------|-------|
| soft ready | ~9s | ~4–15s (varies with startup drift) |
| **dense ready** | **~24.5s** | **~13.7s** (clean) / ~17.7s (with drift) |
| **dense behind soft** | **~15s** | **~2.6–9.5s** |

The embedder build logs `FastEmbed ready in ~1.6–2.6s` and now starts right
after soft-ready. The residual gap between the prewarm kick and the session
build is diffuse GIL contention from the keeper's first graph tick; the large
26s AST block is eliminated. Opt-outs: `CTX_EAGER_PREWARM=0`,
`CTX_AST_REVALIDATE_GATE_ON_EMBED=0`.

## Response after idle

The idle policy (confirmed in `mcp_install.py` / `lifecycle_runtime.py`):
- **While any client is connected, the engine stays warm indefinitely** — the
  embedder stays resident; there is no mid-session warm-down.
- The disconnect timers (`CTX_ENGINE_IDLE_S` / `CTX_DISCONNECT_DEBOUNCE_S`,
  install default **120s**) only start after the **last** client disconnects;
  then the engine stops and unloads the embedder (the ~2-min-after-editor-close
  shutdown). The MCP worker also runs a cheap idle re-warm pulse.

Measured on a persistent connection: after a 65s idle gap the health reported
`embedder_loaded=True dense_ready=True`, and the first `find` was **310ms** vs
**206ms** pre-idle — essentially steady-state, **no cold penalty**. A cold
first-call only happens after a full disconnect past the 120s debounce (then it
is the cold-start table above).

## Sync latency — time from change on disk to searchable

Persistent connection, live DML engine. Each probe writes a uniquely-named
function and polls `find` until the token appears (or disappears for deletes).

| Sync type | What it exercises | Time to searchable |
|-----------|-------------------|--------------------|
| **Hot save** (modify tracked file) | debounce → incremental parse/chunk → DML embed → patch publish | **~2.5s** (2.36 / 2.51 / 2.62s) |
| **Incremental** (brand-new file) | discovery → full add through pipeline | **~3s** (3.22 / 2.67s) |
| **Delete** | tombstone prune (no embed), deletes-first ordering | **1.5s** to drop from search |
| **Live rename** (engine on) | delete-half + add-half | new path **2.2s**, old path gone **4.2s** |

### Bulk / offline (80 files added while the engine was OFF)

Reopen reconcile + drain, from `engine start`:

| Milestone | Time |
|-----------|------|
| engine up | 1.9s |
| soft ready | 4.0s |
| dense ready | 24.2s |
| full 80-file batch searchable | **~65s total** (≈40s of drain after dense) |

Engine log confirmed the path end-to-end:
```
[reconcile:start] enqueued 80 drift + 0 ghost prune path(s) state=reconciling
[keeper] dirty sync refreshed=True upserted=80 removed=0 ms=20112.3
```
- `index_state` correctly went to **reconciling** on reopen (via the offline
  reconcile + `offline_ghost_prune` sweep), and all 80 embedded in a single ~20s
  bulk drain.
- `index_fresh` was **False during the drain** and flipped **True** when caught
  up — the honest "fully caught up" signal. `search_usable` held throughout.
- `pending` stayed empty: 80 tiny 3-line files estimate below the "substantial"
  (minutes-scale) threshold, so they drain silently while `index_state`
  reflects `reconciling`. This is the intended contract — `pending` is for
  minutes-scale work an agent should wait on; small batches just drain.

## Takeaways

- **Warm tool latency is production-grade**: `find` ~220ms quiet (~500–600ms under concurrent sync), `focus` <100ms,
  `gate`/`status` ~2ms. The only >1s tool cost is the one-time first-find after a
  cold warm (~2.3s), which is unavoidable query-embed warmup.
- **No idle penalty while connected** — the engine holds warm for the whole
  session; first-call-after-idle ≈ steady-state.
- **Live edits land in ~2.5–3s**, deletes in ~1.5s — fast enough that a map
  right after a save reflects the change.
- **Cold start / big offline batches** are gated by the DML model load (~24s to
  dense); soft search is usable at ~9s. An 80-file offline paste is fully
  searchable in ~65s with honest `index_fresh=False` while it drains.

## Graph catch-up — batched so bulk churn drains in one rebuild

A graph catch-up rewrites the **whole** `graph.json` once per merge: `extract`
the changed files, then `build_merge` runs `deduplicate_entities` + a full
`build_from_json` over **every** node (18.5k nodes / 37k edges on this repo).
Profiled in isolation on the real graph, a single-file catch-up is:

```
extract 1 file:          262ms
deduplicate_entities:   1287ms   (over all 18,565 nodes)
build_from_json:        2519ms   (rebuilds the whole NetworkX graph)
other:                   195ms
total:                  ~4002ms
```

The cost is **fixed per merge** — it scales with the whole graph, not the number
of changed files. The keeper previously sliced catch-up batches by the chunk cap
(`CTX_LIVE_MAX_CHUNKS=300`, tuned for the embed lane where cost *does* scale with
chunks). So a bulk churn of N files became N chunk-capped merges, each paying the
full ~4s rebuild, and `index_fresh` stayed False for N×4s.

Fix (`sync_loop.py`): when a drain is **catch-up-only** (every pending path is a
`graph_catchup`, no hot saves), widen the batch to `CTX_GRAPH_CATCHUP_MAX_FILES`
(default 2000) and ignore the chunk cap — merge all pending catch-ups in ONE
whole-graph rebuild. Hot saves and mixed batches keep the chunk-bounded cap so an
embed-heavy batch never balloons. Verified: 120 queued catch-up paths now form a
single batch (1 rebuild) vs the old chunk-capped 100-file slices (2+ rebuilds);
for the 80-file bulk-offline case this collapses ~N sequential 4s rebuilds into
one. Opt out: `CTX_GRAPH_CATCHUP_MAX_FILES=0`.

(The per-merge ~4s itself — dominated by `build_from_json` rebuilding the full
NetworkX graph — is a deeper follow-up; batching removes the N× multiplier that
was the actual "index_fresh stays False after bulk churn" pain.)

## How to re-run
```
# tool latency (warm, in-process):
PYTHONPATH=packages python scripts/_qa_profile.py

# single-change sync latency:
PYTHONPATH=packages python scripts/perf/_sync_timing.py hotsave|incremental|delete|rename

# bulk/offline reconcile:
PYTHONPATH=packages BULK_N=80 python scripts/perf/_bulk_offline_timing.py
```
