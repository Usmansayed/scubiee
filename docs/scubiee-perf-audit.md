# Scubiee comprehensive performance & response-time audit

Build **0.3.132** (workspace = engine = uv-tool; install parity `differ: 0
missing: 0`). Windows, engine `:8765`, ~7.8k chunks / ~16k graph nodes / 573
python files. Deps: mcp 1.30, faiss-cpu 1.15.1, fastembed 0.8.1,
onnxruntime-directml 1.24.4, numpy 2.5.3, pydantic 2.13.5, networkx 3.7.

Method: measure each scenario through the **real process boundary** (MCP stdio
bridge as Cursor/Kiro attach; HTTP on :8765; the `scubiee` CLI). For every test:
scenario, measured, expected/reasonable, acceptable (Y/N). Anything unreasonably
slow is treated as a perf bug and investigated (§ Investigations).

## Architecture (from the codebase)

**Processes.** Four cooperating processes:
- **Engine** (`pipeline.server` HTTP on :8765, spawned via WMI outside any bridge
  job — issue 2). Holds the warm binder (chunks + FAISS + BM25 + graph) and the
  embedder (FastEmbed/ORT on DirectML). Serves `/v1/search`, `/health`,
  `/v1/status`, `/v1/dirty`, etc.
- **Keeper** (`pipeline.sync_loop.BackgroundSyncLoop`, a thread in the engine
  process). Polls disk every ~1s (`poll_repo_changes` → `root_probe`), runs
  incremental sync, publishes generations, and off-loads two heavy jobs to child
  processes: the **graph catch-up** (`graph_merge_worker`, issue 6) and the
  **AST bundle revalidate** (`refresh_ast_bundle_if_stale`, PERF-1).
- **Watchdog** (`pipeline.watchdog`, sidecar process). Restarts a dead/hung
  engine; force-heals only with client demand.
- **MCP bridge + worker** (`pipeline.mcp_bridge` → `pipeline.mcp_locate`). The
  IDE speaks JSON-RPC to a stable bridge; the bridge proxies to a worker that
  serves the 8 locate tools. The worker resolves seeds against a disk AST bundle
  (`context_trace._load_repo`).

**Retrieval channels.** `map`/`search` = `D_channel_best` (BM25 + dense + graph
fusion) over the live index. `pack_context` = a composite-graph heatmap seeded on
an AST node (needs the AST bundle). Two corpora that must agree (BUG-A).

**Latency-bearing paths & caches.**
- Embedder warm-up (cold ORT/DML): one-time ~8–40s, managed by the warm contract.
- map result cache (generation-keyed, issue 1): repeat map ≈ cache hit.
- AST bundle (`trace_repo_v3.pkl`) + per-file parse cache
  (`.scubiee/cache/parse_v1`, PERF-1); revalidated in a background child.
- Hot-lane save → publish (append-only, issue 4); graph catch-up deferred to a
  child (issue 6).
- Idle standby: engine stops ~10s after the last client leaves; `ensure` wakes it.

**MCP tools (8):** gate, status, map, pack_context, expand_context,
collect_hot_context, workspace, expand.
**HTTP POST:** /v1/open, /v1/search, /v1/dirty, /v1/sync, /v1/publish, /v1/grep,
/v1/outline, /v1/read_span, /v1/follow_imports, /v1/graph_neighbors,
/v1/query_graph, /v1/grep_ident, /v1/client/*, /v1/session/end, /v1/shutdown.
**HTTP GET:** /health, /v1/status, /v1/settings, /v1/resources, /dashboard.
**CLI:** ~40 subcommands (index, status, gate, search, map, pack, expand, engine,
connect, setup, wipe, …).

## Scenario matrix

| dimension | values |
|---|---|
| state | cold engine (fresh restart), warm engine, idle-standby→wake |
| repetition | first call, warm call, repeated calls (cache) |
| after-op | pack after map; search after edit; map after edit (propagation) |
| cache | map cache hit/miss; AST bundle fresh/stale; parse cache cold/warm |
| input size | small file, large file, whole-repo query |
| async | graph catch-up, AST revalidate, deferred vector save |

## Results

Measured via `scripts/perf_audit.py` (HTTP + MCP stdio + propagation) against a
warm engine, plus targeted re-measurement of the two slow ops in isolation.
"Budget" is the reasonable ceiling for the op; "acceptable" is measured ≤ budget.

### HTTP GET

| scenario | measured | budget | acceptable | note |
|---|---|---|---|---|
| GET /health (first) | 316–365 ms | 50 ms | N* | first-call noise; **~17 ms** on repeat (verified) |
| GET /health (repeat) | ~17 ms | 50 ms | Y | |
| GET /v1/status | 360–685 ms | 300 ms | ~ | live status work; borderline, first-call heavy |
| GET /v1/settings | 2–26 ms | 200 ms | Y | |
| GET /v1/resources | 64–67 ms | 300 ms | Y | |
| GET /dashboard | 1–42 ms | 200 ms | Y | |

### HTTP search / structural

| scenario | measured | budget | acceptable | note |
|---|---|---|---|---|
| POST /v1/search first | 225–408 ms | 3000 ms | Y | |
| POST /v1/search repeat | 222–744 ms | 800 ms | Y | |
| POST /v1/search large (top_k=20) | 302–496 ms | 1500 ms | Y | |
| **POST /v1/grep** | **14624 ms → ~2000 ms** | 1500 ms | fixed (see PERF-2) | was 0 hits (wrong); now 8 hits, correct |
| **POST /v1/grep_ident** | **4752 ms → ~1300 ms** | 1500 ms | Y (fixed) | see PERF-2 |
| POST /v1/outline | 26–253 ms | 800 ms | Y | |
| POST /v1/read_span | 28–87 ms | 500 ms | Y | |
| POST /v1/graph_neighbors | 42–70 ms | 1500 ms | Y | |
| POST /v1/query_graph | 89–127 ms | 3000 ms | Y | |
| POST /v1/follow_imports | 53–58 ms | 1500 ms | Y | |

### MCP tools (warm session)

| scenario | measured | budget | acceptable | note |
|---|---|---|---|---|
| gate (attach) | 1300–1680 ms | 2000 ms | Y | |
| status full | 1019–1795 ms | 1500 ms | ~ | first-call spike; single-shot |
| map first (cold topic) | 1277–1572 ms | 3000 ms | Y | |
| map repeat (cache) | 118–324 ms | 800 ms | Y | generation-keyed cache hit |
| pack first | 869–1783 ms | 2500 ms | Y | builds composite edges |
| pack repeat | 85–377 ms | 500 ms | Y | |
| pack include_bodies | 88–107 ms | 1500 ms | Y | |
| expand_context (callers/callees/config/all) | 63–105 ms | 600 ms | Y | |
| expand_context effects | 832 ms | 600 ms | ~ | first-call; others <110 ms |
| collect_hot_context | 108–127 ms | 600 ms | Y | |
| workspace show | 67–97 ms | 500 ms | Y | |
| expand file:lines | 54–68 ms | 500 ms | Y | |

### Propagation / async

| scenario | measured | budget | acceptable | note |
|---|---|---|---|---|
| save small file → searchable | 2406–2457 ms | 5000 ms | Y | hot-lane BM25 patch |

\* first-call warmup, not a steady-state regression.

**Verdict:** the whole surface is within reasonable budgets except **grep** /
**grep_ident**, which were investigated as PERF-2 below. Everything else is
first-call warmup noise (health/status/effects spike once, then run fast) or
comfortably inside budget. Repeated/cached ops are all sub-400 ms.

---

## Investigation PERF-2 — grep / grep_ident (14.6 s + wrong result → ~2 s + correct)

**Symptom.** `POST /v1/grep` took **14.6 s** and `POST /v1/grep_ident` **4.75 s**
on the warm engine — 10× and 3× their budgets. Worse, on inspection **grep
returned 0 hits for a symbol that exists** (`def build_merge` in
`packages/graphify/build.py`), silently flagged `truncated: true` /
`scan_incomplete`. So this was a correctness bug wearing a perf costume.

**Method.** `ripgrep` is not on PATH (`shutil.which("rg") → None`), so
`grep_scan` always falls to the pure-Python fallback. Profiled it in isolation
(`scripts/prof_grep.py`, cProfile) over the live repo (2302 walked files):

```
iter_glob_files(**/*): 2300 files in 2127 ms
grep_scan: 4.22 s total
  iter_glob_files            3.76 s  (89%)
    is_junk_rel  ×8795        2.14 s
      load_scubiee_ignore ×8795   0.84 s   ← re-loads + re-stats ignore per file
      fast_stat/_stat            0.72 s
    _path_or_ancestor_matches ×61565  0.82 s
    pathlib relative_to/__eq__/...    heavy churn
```

Two root causes:
1. **Per-file ignore-rule reload.** `iter_glob_files` called
   `is_junk_rel(rel, root=root)` with no preloaded rules, so
   `should_index_rel → load_scubiee_ignore` re-resolved the root and re-stat'd
   `.scubieeignore` **once per file** (8795×). This is the exact class of bug the
   code already fixed in `merkle.sanitize_file_hashes` (issue 4).
2. **Global line budget starved by data files.** With the catch-all `**/*` glob,
   `.json` files (762 files / 263k lines — *more than all `.py`*, mostly under
   `docs/superpowers/`) sorted **before** real source. The scan's 250k-line
   global budget was exhausted after 321k lines of JSON, **before reaching
   `packages/graphify/build.py`** (file #1420 of 2302) → 0 hits, silent
   `scan_incomplete`.

**Fixes (all in `packages/pipeline/capability.py`).**
- `iter_glob_files`: load `.scubieeignore` **once** and thread `rules=` into
  `is_junk_rel`; derive rel paths with string slicing instead of thousands of
  `Path.relative_to` allocations.
- `grep_scan`: raise the global line budget (250k → 2M, the deadline is the real
  safety valve) and add a **per-file cap** (`CTX_GREP_MAX_LINES_PER_FILE`=60k) so
  one giant JSON/log can't starve the scan — it skips the rest of that one file
  and keeps going. This is what makes the scan **reach real source** and return
  correct hits.
- `path_glob_match`: fast suffix path for the very common `*.ext` / `**/*.ext`
  globs (an `endswith` instead of compiling+running a regex per walked file);
  `grep_ident` uses `*.py`.

**After (steady-state, engine idle).**

| op | before | after | correctness |
|---|---|---|---|
| grep `**/*` | 14624 ms, **0 hits (wrong)** | **~1.7–2.4 s, 8 hits, not truncated** | fixed |
| grep_ident `*.py` | 4752 ms | **~1.2–1.8 s** | 1 hit, 1 span |

Isolated `grep_scan`: 4.22 s → 1.63 s (and now returns the *correct* 8 hits
instead of aborting at 0). `iter_glob_files`: 3.76 s → 0.81 s.

**Residual & trade-off.** grep still sits ~2 s (idle) and spikes to 5–7 s while
the keeper is mid-catch-up, because it is a pure-Python full-disk scan of ~555k
lines under a 35% engine CPU cap contending with the keeper thread. The clean
structural fix is **ripgrep** — `grep_scan` already prefers `rg` when present
(`_grep_via_rg`), which would drop this to ~50 ms. Recommend documenting `rg` as
an optional dependency. A behavior-changing alternative (skip `.json`/`.log` on
catch-all globs) was **rejected**: a user grepping a literal inside a JSON under
`**/*` would silently miss it — correctness over speed.

**Regression test.** `tests/test_grep_budget.py` (3 tests): grep must reach
source past a 120k-line data file; `*.py` glob finds the symbol; ignored dirs
(`.venv`) are skipped. All pass. Full grep/glob/capability/ignore/merkle suite:
252 pass, 6 skipped, 0 new failures.

## Not-a-bug (verified fast, documented for completeness)
- **health/status/effects first-call spikes** — one-time; repeats are 17 ms /
  240 ms / <110 ms. The harness measures each op once, so the first-touch of a
  lazily-initialized path shows up as "slow". Not a steady-state regression.
- **search / map / pack** — all within budget cold; cached repeats sub-400 ms
  (map generation cache, issue 1; pack span cache).
- **save → searchable ~2.4 s** — hot-lane BM25 patch; well inside the 5 s budget.

## Deferred (documented, not implemented this pass)
- **PERF-1 pack-of-newly-created-file** (~22–28 s): bounded by the whole-repo AST
  rebake; the designed fix is the two-phase nodes-only refresh (224 ms nodes
  patch makes the seed packable immediately, graph rebake in background). Needs
  its own heatmap-completeness correctness pass — see `docs/scubiee-perf-log.md`.
- **ripgrep as optional dep** — would make grep/grep_ident ~50 ms; the fallback
  is now correct and ~6× faster, so this is an optimization not a fix.
