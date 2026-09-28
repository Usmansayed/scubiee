# Scubiee performance log

Treat "too slow" as a bug. Per issue: measure → profile where the time goes →
understand the flow → research → optimize → re-measure → document.
Windows, engine `:8765`, uv-tool install 0.3.132. Nothing committed.

---

## PERF-1 — pack after editing a file takes ~27s to resolve the new symbol

**Observed.** After the BUG-A fix, `scripts/ast_revalidate_live_probe.py` showed a
freshly-created file's symbol became pack-resolvable at **27.3s** (map found it at
1.7s). Correct now, but 27s is far too slow — the whole point is a fast
locate→pack loop.

### Measure / decompose

`scripts/perf_pack_after_edit.py` (phases from the moment a new file is written):

```
map_seed        7.7s   (map returns the new file as a seed — incl. its hot sync)
rebake_logged  26.3s   (keeper's ast revalidate FINISHED; it reported ms=22899)
pack_ok        65.5s   (pack first resolved the seed)
rebake_reported_ms = 22899.8
```

Two separate problems:

1. **The rebake itself is ~23s.** A one-file edit triggers a full AST
   re-extraction + graph/LSP/graphify rebuild of the *entire* repo.
2. **A feedback loop inflates it further.** The keeper log shows two back-to-back
   rebakes (23.9s then 22.9s). Each rebake takes ~23s; meanwhile more edits (the
   probe file, this perf-log doc, graph catch-ups) move the corpus fingerprint, so
   `refresh_ast_bundle_if_stale` finds it stale again and rebakes a second time.
   Pack only resolves after a rebake lands on a fingerprint that stays put.

Profile of one forced rebake (`_load_repo(force_bake=True)`, 573 files / 6630
nodes, **32.7s** with the graphify layer):

```
extract_nodes            221 ms   (cheap — just the node table)
corpus_fingerprint       186 ms
build_ast_graph        12,224 ms   ast.walk 12.4s cum, _collect_imports 7.7s
build_lsp_index        11,364 ms   compile 5.2s, _refs_from_ast 4.1s
load_store_graphify…    5,098 ms   _map_symbol 4.1s
```

The dominant cost is rebuilding `build_ast_graph` + `build_lsp_index` +
graphify **for all 573 files** on every one-file change. Node extraction itself
is negligible (221ms).

### Investigation

`context_trace._load_repo` (force path) calls `extract_nodes` → `build_ast_graph`
→ `build_lsp_index` → `load_store_graphify_graph`, all whole-repo. There is no
incremental path: a single changed file re-parses and re-walks every file's AST.
The bundle is one monolithic pickle keyed on a whole-corpus fingerprint, so any
edit invalidates all of it.

### Research

Every code-intelligence indexer surveyed does **per-file parse-result caching
keyed on file hash** — only reparse changed files, feed cached results into the
cross-file resolver (codegraph `--update`, RagCode incremental, Memory Bank,
tokennuke). Content rephrased for compliance. Scubiee cached the *node table*
(`trace_nodes_v2.pkl`) but not the expensive graph/LSP derivation, and re-read +
re-parsed every file's AST twice per rebake.

### Optimization (in-process, verified)

Three safe, correctness-preserving changes to the AST rebake
(`_load_repo(force_bake)`), profiled on this repo (573 files / 6630 nodes):

1. **Shared per-file parse cache** (`trace_lab/corpus.read_and_parse`) keyed on
   `(path, mtime_ns, size)`. `build_ast_graph` and `build_lsp_index` both
   read+parsed every file — now they share one parse; unchanged files across
   rebakes skip parsing entirely.
2. **Targeted import walk** (`ast_graph._iter_import_stmts`) replaces
   `ast.walk(tree)` in `_collect_imports` — descends only statement bodies
   (module/func/class/try) instead of every expression node. Verified identical
   output to `ast.walk` on all 573 files (0 mismatches).
3. **`_map_symbol` file index** (`graphify_layer._nodes_by_file`) — it rescanned
   all 6630 nodes on each of ~20k calls (O(nodes×calls), ~4.3s / 132M compares);
   now grouped by file once.

Isolated `_load_repo(force_bake)` timing:

| stage | before | after |
|---|---|---|
| cold (empty caches) | 32.7s | **14.5s** |
| warm (parse cache hot) | — | **9.0s** |

2.3x cold, 3.6x warm. All trace/ast/graphify/pack tests that pass on HEAD still
pass; the 6 failures in this suite are pre-existing (verified on a clean HEAD
worktree — multi_seed ×3, polytrace ×2, locate_quality_combo).

### Further changes tried

- **Disk-backed parse cache** (`trace_lab.corpus.read_and_parse` +
  `set_parse_cache_root`, `.scubiee/cache/parse_v1/`) so the freshly-spawned
  revalidate child inherits warm parses. Measured: child rebake 22.4s → 20.0s
  across two consecutive fresh interpreters — small, because parsing is only
  ~5.5s of the child's cost; the graph/LSP/graphify **derivation** dominates.
- **In-process revalidate** (bake on the keeper thread instead of a child) —
  reverted. In isolation it was 9-14s, but live it ran **concurrently** with
  search and graph catch-ups and ballooned to 29s while contending for the GIL.
  Child-spawn (GIL-isolated) is the correct architecture; kept it.
- **Faster revalidate cadence** (`CTX_AST_REVALIDATE_S` 20s → 5s) so the rebake
  fires promptly once the corpus settles instead of waiting a fixed 20s.

### Result

Core AST rebake (`_load_repo(force_bake)`, isolated, 573 files):
**32.7s → 14.5s cold / 9.0s warm** (2.3x / 3.6x). Verified correct: the targeted
import walk matches `ast.walk` on all 573 files (0 mismatches); all trace/ast/
graphify/pack tests that pass on HEAD still pass; `tests/test_ast_bundle_revalidate.py`
(7) green.

Live pack-after-edit end-to-end: **65s → ~28s** on a settled engine. The residual
~22s is the child rebake under the live config (`CTX_TRACE_GRAPHIFY=1`, 16k-node
`graph.json`): the whole-repo graph + LSP + graphify **derivation** — not
parsing, which is now cached. Cutting this further needs a genuinely
**incremental** graph update (re-derive only the changed file's edges and patch
the bundle) rather than a whole-repo rebuild. That is a larger, higher-risk change
to `build_ast_graph` / `build_lsp_index` / `graphify_layer`; deferred as PERF-2 so
it can be designed and tested on its own rather than rushed. The map→pack loop is
correct throughout (BUG-A) and materially faster; the 28s is the pack of a *newly
created* file's seed — an already-indexed file packs in <150ms.

**Status: improved 2.3x (rebake) / ~2.3x (end-to-end); deeper incremental
rebuild tracked as PERF-2.**

### PERF-2 (recommended next, designed not yet built) — two-phase refresh

The residual latency is entirely "make a *newly created* file's seed packable",
bounded by the whole-repo graph derivation. But pack *seed resolution* only needs
`rt.nodes`, and `extract_nodes(root)` is **224ms** (measured; it resolves
`graph_merge_worker.py::start_graph_merge` correctly). Only the ranking *heatmap*
needs `rt.graph`.

Design: split the revalidate into (1) a **fast nodes-only patch** (~0.2s) that
refreshes `rt.nodes` so a new seed resolves and packs immediately (its heatmap is
just sparser — the seed card is always valid, neighbors fill in later), and (2)
the **full graph/LSP/graphify rebake** in the background for complete ranking.
This turns the common "pack the file I just made" case from ~22s to sub-second,
with graceful degradation instead of a wrong answer.

Not built now because it changes heatmap completeness during the catch-up window
and needs its own correctness pass (verify `heatmap_to_cards` + `rt.poly` render
an edgeless fresh seed cleanly, and that a partial `rt.graph` + fresh `rt.nodes`
never mismatch). Deferred deliberately per the correctness-first constraint.

### Other operations scanned (all reasonable — not bugs)

Warm engine, via the real MCP bridge:

| op | latency |
|---|---|
| gate (warm) | ~1.0s |
| status full | ~1.2s / cached |
| map cold-topic | 0.4–1.7s |
| map repeat | 167ms (cache=last) |
| pack first (builds composite edges) | 0.8s |
| pack subsequent | ~100ms |
| expand_context (any direction) | 60–100ms |
| collect_hot_context | ~105ms |
| workspace show/pin | 60–300ms |
| graph catch-up (child, one file) | ~7s (off the keeper — issue 6, non-blocking) |

Cold-attach gate (~2–7s) and first map (~8–14s on a truly fresh engine) are the
one-time embedder/ORT warm-up the warm contract already manages — not per-op
regressions. Nothing else is unreasonably slow.

### Optimizations that landed
- `trace_lab/corpus.py`: shared per-file parse cache (`read_and_parse`,
  `_store_parse`), disk-backed layer (`set_parse_cache_root`, `_disk_parse_path`).
- `trace_lab/ast_graph.py`: `_iter_import_stmts` (targeted import walk) replaces
  `ast.walk` in `_collect_imports`; both builders use `read_and_parse`.
- `trace_lab/lsp_index.py`: uses `read_and_parse`.
- `trace_lab/graphify_layer.py`: `_nodes_by_file` index for `_map_symbol`.
- `pipeline/sync_loop.py`: revalidate cadence 20s → 5s.
- `pipeline/context_trace.py`: `set_parse_cache_root` wired into `_load_repo`.

### Final verification

Isolated rebake, stable across two fresh-interpreter runs:
**32.7s → 15.5s cold / 10.9s warm** (2.1x / 3.0x).

Regression: the touched suites (trace, ast_graph, lsp, graphify, pack, locate,
corpus, ast_bundle, attach_warm, root_probe, live_reindexing, fast_stat, gate) →
**360 passed, 5 failed**. All 5 failures are pre-existing: a clean `HEAD` worktree
run of the same grouping produced **11 failures** including the same
`test_locate_worker_prewarm` / polytrace / mcp_exploration retry ones (they are
order-dependent on shared global state and vary by run order — my tree had fewer
failures than HEAD, not more). `tests/test_ast_bundle_revalidate.py` (7) green.
The targeted import walk was verified byte-identical to `ast.walk` on all 573
files. Install parity `differ: 0  missing: 0`. Nothing committed.

## Summary

| operation | before | after |
|---|---|---|
| AST rebake (isolated, 573 files) | 32.7s | 15.5s cold / 10.9s warm |
| pack a **newly created** file's seed (live, settled) | 65s → 28s | bounded by rebake; PERF-2 (two-phase) would take it sub-second |
| pack an already-indexed seed | — | <150ms (unchanged, already fast) |
| map / expand / collect / workspace | — | 60ms–1.7s (reasonable, unchanged) |

Correctness held throughout (map→pack still resolves edited files — BUG-A). The
one remaining slow path (first pack of a brand-new file) has a designed,
lower-risk fix (PERF-2, two-phase refresh) deferred for its own correctness pass.
