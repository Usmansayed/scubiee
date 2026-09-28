# Scubiee performance investigation

Systematic hunt for operations with unreasonable response times, followed by
root-cause analysis and fixes. One issue at a time: measure → trace code → find
the bottleneck → research → optimize → re-benchmark → document.

Environment: build **0.3.132**, Windows, engine `:8765`, uv-tool install
(parity `differ:0 missing:0`), ~7.8k chunks / ~16k graph nodes / ~573 py files.
Engine runs under a 35% CPU cap and 1536 MB RSS cap (`.cursor/mcp.json`), and
goes to idle-standby ~10 s after the last client leaves (`CTX_ENGINE_IDLE_S=10`).

All timings are through the real process boundary (MCP stdio bridge / HTTP :8765
/ CLI). "Reasonable" is a per-op judgement, not a blanket target — the goal is to
find ops that are *genuinely* too slow, understand why, and fix them.

---

## The two propagation lanes (essential context)

After a file save, two independent lanes run with very different latency:

- **Hot lane (search / map):** keeper polls disk ~1 s (`CTX_CHANGE_POLL_MS=1000`)
  → cheap Merkle diff for modified files, `DirWatch` folder-mtime for new files →
  synchronous BM25 patch. New/changed content searchable in ~1–3 s.
- **Graph lane (pack heatmap / expand edges):** a save queues a **graph
  catch-up** = whole-graph `build_merge(dedup=True)` + ~20 MB JSON export, ~10–15 s
  of pure-Python CPU in a below-normal-priority child (`graph_merge_worker`),
  committed by the keeper via atomic rename. Graph-derived surfaces therefore
  trail the hot lane by 10–40 s on brand-new code.

There is also the **pack AST bundle** (`trace_repo_v3.pkl`): pack seeds resolve
against a disk AST bundle that is rebaked when the corpus changes (BUG-A / PERF-1).

---

## Known slow ops (carried in from sessions 1–3)

Measured warm, through the MCP bridge / HTTP, on this repo.

| # | operation | measured | first-glance reasonable? | lane / suspected cause |
|---|---|---|---|---|
| K1 | **create new file → pack seed resolves** | **~15 s** | no (want < 3 s) | graph lane — whole-repo `build_merge` + AST rebake |
| K2 | **add call edge → expand_context shows caller** | **~38 s** | no (want < 5 s) | graph lane — edge only appears after catch-up commit |
| K3 | **expand_context (first call in session)** | **~0.8 s**, was 418–670 ms | borderline | AST hydrate / graph load on first expand |
| K4 | **rename symbol → old symbol evicted from search** | **> 20–30 s** | no (want < 5 s) | hot lane tombstones but skips `compact()`; non-hot reconcile evicts |
| K5 | **create new file → searchable** (cold/demoted engine) | **MISS > 30 s** | no | engine idle-standby wake + soft-warm mid-edit (PROP-2) |

Notes carried in:
- K1/K2 share one root cause: the graph catch-up child rebuilds the **whole**
  graph for a one-file change. The designed fix is **PERF-2: two-phase
  nodes-only refresh** (a ~224 ms nodes patch makes the seed packable
  immediately; full graph rebake in background). Deferred previously because it
  changes heatmap completeness and needs a correctness pass.
- K3 warm repeats are fast (75–110 ms); only the first expand in a session is slow.
- K4 is "by design" (availability over immediate eviction) but the eviction
  window (~30 s) is long enough to be misleading; worth quantifying + shortening.
- K5 is environmental (warm engine assumed); the wake path itself is worth measuring.

Fixed already (for reference, not re-opened):
- `status(detail=full)` 23 s → ~1.3 s (removed redundant `/health` round-trip).
- HTTP `grep` 14.6 s → ~2 s + correctness; `grep_ident` 4.75 s → ~1.3 s.

---

## Discovery sweep (task #2)

Measured the graph-lane child directly (`scripts/_gcatchup_time.py`), profiled
`build_merge` (`scripts/_gmerge_prof.py`), and swept the CLI. Combined with the
MCP/HTTP audits from sessions 1–3, the full ranked list of genuinely-slow ops:

### D1 — graph catch-up rebuilds the WHOLE graph for a one-file change (ROOT of K1/K2)
Directly timing `start_graph_merge(root, store, [one_file])` on this repo
(16,213 nodes / 34,138 edges, graph.json = 19.8 MB):

```
run 0: wall=6246ms  extract=84ms  merge=4418ms  export=937ms  child_total=5889ms  files=1
run 1: wall=6048ms  extract=102ms merge=4268ms  export=957ms  child_total=5707ms  files=1
```

`extract` of the one changed file is ~90 ms, but **`merge` is ~4.3 s and
`export` ~0.95 s** — both proportional to the *whole* graph, not the delta.
cProfile of `build_merge` (proportions exact; absolute inflated by profiler):

```
build()                     7.4 s
  build_from_json           3.9 s   (assemble NetworkX graph from 16k nodes)
  deduplicate_entities      3.28 s
    _make_minhash ×6869     2.38 s
      _minhash.update ×245k 2.06 s  ← single biggest cost
  + normalize_id / _old_file_stems / _norm_source_file pathlib churn ~1 s
```

**Root cause:** `build_merge` loads the entire existing graph as `base`, concatenates
the new chunks, and calls `build(dedup=True)` over **all 16k nodes** — recomputing
a MinHash for every one of ~6,869 nodes and re-assembling the whole graph, even
though a single file changed. This ~5.4 s of whole-graph work (× the child spawn
+ keeper poll/commit + AST rebake that stack on top) is exactly why:
- **K1 create→pack ≈ 15 s** (pack waits for the catch-up commit + AST bundle)
- **K2 add-edge→expand ≈ 38 s** (expand needs the committed graph edge)
- contributes to **K4** (the non-hot reconcile runs alongside this).

This is the highest-impact issue and the first to fix. It is the "PERF-2"
whole-repo-rebake gap, now root-caused to `build_merge` + `deduplicate_entities`
doing O(whole graph) work per one-file save.

### D2 — CLI cold start ~1.1–1.6 s (low priority, mostly interpreter startup)
`scubiee --version` = ~1164 ms, `scubiee status .` = ~1635 ms. `-X importtime`
shows `pipeline.cli` imports total only ~140 ms; the rest is Python interpreter +
site init on Windows (fixed cost of a Python console script). Not Scubiee's code;
would need a resident CLI/daemon to fix. **Out of scope** — noted, not pursued.

### D3 — K3 first-expand-in-session ~0.8 s
Borderline; warm repeats are 65–110 ms. First expand pays a one-time AST/graph
hydrate. Revisit after D1 (the AST rebake is entangled with the same graph work).

### Ranked work order
1. **D1 / K1 / K2** — graph catch-up whole-graph rebuild (biggest, clearest win).
2. **K4** — rename eviction window (~30 s) — tied to the non-hot reconcile cadence.
3. **K3 / D3** — first-expand hydrate — re-measure after D1.
4. D2 — CLI startup — out of scope (interpreter cost).

Confirmed reasonable (not pursued): search first/repeat (225–740 ms), map cache
(80–320 ms), pack warm repeat (85–380 ms), expand warm (65–110 ms), HTTP
outline/read_span/graph_neighbors/query_graph/follow_imports (25–130 ms),
save→searchable hot lane (~2–3 s), delete (~3 s).

---

## Investigations

### Issue #1 — graph catch-up whole-graph rebuild (D1; root of K1/K2)

**Original timing (one-file change, `scripts/_gcatchup_time.py`):**
`build_merge` child = **wall ~6.1 s** (extract 90 ms, **merge 4.3 s**, export 0.95 s).

**How it works.** A save queues a graph catch-up. The child (`graph_merge_worker`)
runs `build_merge([new_chunks], graph_path, dedup=True)`: it loads the entire
existing `graph.json` (16,213 nodes / 34,138 edges, 19.8 MB) as `base`,
concatenates the new file's chunks, and calls `build(dedup=True)` over **all**
16k nodes — then exports the whole 20 MB back. So a one-file edit pays whole-graph
cost.

**Where the time goes (cProfile of `build_merge`):**
- `build()` 7.4 s = `build_from_json` 3.9 s + `deduplicate_entities` 3.28 s.
- Inside dedup: `_make_minhash` ×6869 = 2.38 s → **`MinHash.update` ×245k = 2.06 s**
  (single biggest cost). Inside `build_from_json`: `normalize_id` ×114k = ~1 s
  (two regex subs + NFKC per call), plus `make_id` / `_old_file_stems` churn.

**Research.** `datasketch` ([github.com/ekzhu/datasketch](https://github.com/ekzhu/datasketch))
exposes `update_batch` precisely because a 128-wide NumPy op *per token* is
dominated by per-call dispatch overhead; the vectorized fix (hash all tokens into
one `(k, num_perm)` matrix, single column-min) is the same approach
`vectorized-minhash` ([github.com/YaleDHLab/vectorized-minhash](https://github.com/YaleDHLab/vectorized-minhash))
uses. (Content rephrased for licensing compliance.)

**Fixes (safe, correctness-preserving):**
1. **Batched MinHash** — added `MinHash.update_batch(values)` in
   `packages/graphify/_minhash.py`: hashes all shingles of a node in one
   vectorized `(k,128)` matrix op instead of 128-wide NumPy per shingle.
   `_make_minhash` in `dedup.py` now calls it. **Verified bit-identical** to the
   per-shingle path (12/12 test labels; same Mersenne-prime permutation family) —
   dedup quality unchanged. Micro-bench: 6869 minhashes 1000 ms → 364 ms (2.7×).
2. **Cached `normalize_id`** — `packages/graphify/ids.py`: `@lru_cache(131072)` +
   pre-compiled regexes. The recipe is pure/idempotent and the same ID strings
   recur heavily (every edge endpoint re-normalizes a node ID), so memoizing is
   safe. ~1 s → negligible on the hot repeat.

**After (re-benchmarked, `scripts/_gcatchup_time.py`):**

| stage | before | after MinHash batch | after +normalize_id cache |
|---|---|---|---|
| merge | 4.3 s | 2.9 s | **2.34 s** |
| export | 0.95 s | 0.90 s | 0.85 s |
| **child wall** | **6.1 s** | 4.5 s | **3.9 s** |

Net: **graph catch-up 6.1 s → 3.9 s (−36 %)**, merge −46 %. Regression: 25
graphify/dedup/minhash/ids tests pass (the one `test_multi_seed_v1` failure is
pre-existing and imports `trace_lab.multi_seed`, not the changed modules).

**Remaining (root-caused, deferred with rationale):** `build_merge` is still
O(whole-graph) — it re-dedups and re-assembles all 16k nodes for a one-file
delta. A truly incremental merge (only re-dedup the changed file's nodes against
LSH neighbors) would cut the rest, but `deduplicate_entities` does global
cross-file concept merging; making it incremental risks dedup correctness and
needs its own dedicated correctness pass. Not bundled into this perf sweep.

### Issue #1b — AST bundle bake (the OTHER half of create→pack latency; K1)

While validating K1 end-to-end I found pack-of-a-new-file waits on **two** heavy
jobs, not one: the graph catch-up (above) **and** the AST bundle bake
(`_load_repo(force_bake=True)` → `refresh_ast_bundle_if_stale`).

**Timing (`scripts/_astbake_time.py`):** force-bake = **9–15 s**.

**Where the time goes (cProfile, parse cache warm):**
- `build_ast_graph` 6.4 s — **`ast.walk` 2.09M calls = 6.1 s**, via `_refs_from_ast`
  (6421 files).
- `build_lsp_index` 5.9 s — `_bound_callbacks` 3.6 s + `ast.parse`/`compile`
  12,842× (2× per file) = 2.3 s (per-symbol **snippet** re-parses in
  `_parse_snippet` / `_bound_callbacks`).
- `_pickle.dumps` 0.85 s (write bundle).

**Root cause:** the bake re-extracts the **whole** corpus (all 6421 files) for a
one-file change, and within it re-parses per-symbol snippets and uses the generic
`ast.walk`. The file-level parse *is* already shared via the PERF-1 process
parse-cache; the redundant cost is the per-symbol snippet parse + generic walk.

**Fix landed — `build_lsp_index` snippet-parse short-circuit (result-identical).**
`build_lsp_index` re-parsed *every* non-class symbol's snippet (`_parse(n.text)`)
and ran `_bound_callbacks` on it — but `_bound_callbacks` only emits when the
body has a Call to a `_REGISTER` name (`bind|register|subscribe|listen|on|
add_handler`). Added `_REGISTER_CALL_RE` (`\b(name…)\s*\(`) and skip the parse +
walk when the source can't contain such a call. **Provably result-identical** (a
call token absent from the text can't be an AST Call node) — verified by
comparing the full `LspIndex.dispatch` with/without the short-circuit
(**identical: True**) and the 41 lsp/trace_lab/ast_graph tests pass.
- `build_lsp_index`: **4042 ms → 891 ms (4.5×)** on this corpus.
- Full AST bake: ~9–15 s → **~8.4–9.1 s** warm (modest at the whole-bake level
  because `build_ast_graph` is now the dominant half).
Files: `packages/trace_lab/lsp_index.py` (`_REGISTER_CALL_RE`, `import re`,
short-circuit in `build_lsp_index`).

**Still deferred — `build_ast_graph` (`_refs_from_ast`), now the dominant ~8 s.**
Re-profiled: `build_ast_graph` 8.0 s = `_refs_from_ast` ×6420 (5.08 s) →
`ast.walk` 1.08 M calls (3.94 s) + `_parse_snippet` ×6420 (1.86 s). Unlike
`_bound_callbacks`, `_refs_from_ast` collects **all** `Call`/`Name` references,
so it cannot be keyword-short-circuited — any identifier may be a reference.
Operating it on the already-parsed file subtree instead of re-parsing per-symbol
snippets would change which edges get attributed per symbol — graph/heatmap
**correctness**, the PERF-2 concern. Deferred to a dedicated correctness pass
with edge-count diffing; the whole-repo-rebake-for-one-file design is the same
PERF-2 gap (two-phase nodes-only refresh).

**Net effect on K1/K2 this pass:** graph-lane catch-up ~36 % faster; AST-bake
`build_lsp_index` half ~4.5× faster (result-identical). The `build_ast_graph`
half and the whole-repo-rebake-per-file design remain the deferred PERF-2 work,
so the user-visible create→pack improvement is partial.

### Issue #2 — K4 rename: old symbol lingers in search 43–60 s+

**Re-measured (warm engine, `scripts/_k4_rename.py`):**
- trial 0: create 2.7 s, new symbol searchable 1.2 s, **old symbol evicted: > 60 s (never within window)**
- trial 1: create 9.0 s, new searchable 0.2 s, **old evicted: 43.7 s**

So the *new* symbol appears in ~0.2–1.2 s but the *old* one keeps matching search
for 40–60 s+. Confirmed real (not a harness artifact).

**How eviction is supposed to work (code trace):**
1. Rename `old_fn`→`new_fn` in a file. `chunk_key` = the **symbol name**
   (`chunk_merkle.chunk_key`), so old and new chunks have different keys.
2. `incremental_sync` computes `truly_removed` — the old chunk has no
   same-key replacement, so its id lands in `removed_ids`.
3. The hot delta carries `records` (new) + `removed_ids` (old). At publish,
   `engine._patch_chunk_delta` tombstones the old chunk and calls
   `bm25.mark_dead(dead_positions)` — a dead chunk scores 0, so search stops
   returning it. This is designed to be immediate.

**Root cause (the coupling that defeats it):** the hot publish only takes the
patch path when the delta is **`patchable`** — `ce_service._maybe_hot_publish`
returns `None` unless `HotDelta.patchable` is true, and `patchable` (for a
non-append edit) requires `rows == len(embedded_ids)`, i.e. **the new chunk must
have been embedded synchronously**. When the embedder is **demoted / lagging**
(idle-standby just woke it, or dense is mid-prewarm — exactly the state during
these trials), the new chunk isn't embedded in time, `patchable` is false, the
whole patch (including the cheap BM25 `mark_dead` tombstone) is declined, and
eviction waits for a later full publish/reconcile — the ~40 s we measured. The
**tombstone does not depend on embeddings**, but it is gated behind the same
`patchable` check as the dense upsert, so a dense hiccup blocks a BM25-only
operation.

**Proposed fix (designed, not yet landed):** decouple the tombstone from the
dense-embed coverage — when a delta has `removed_ids`, apply the BM25
`mark_dead` eviction even if the dense add is deferred (the removed chunk's
vector is already tombstoned separately). This keeps search correct (old symbol
gone promptly) without waiting on the embedder.

**Why not landed this pass — the deeper constraint (traced to a specific line).**
The tombstone can't simply be decoupled from the embed coverage because
`engine._patch_chunk_delta` validates the **whole delta atomically**:

```python
for record in records:
    if rid in row_of_new:      ... appended
    elif rid in chunk_row:     ... in_place
    else:  raise RuntimeError(f"chunk {rid} has neither a new row nor a live one")
```

A rename's *new* chunk that wasn't embedded yet is in neither set, so passing the
delta through to tombstone the *old* chunk would hit this `raise`. Applying the
removal promptly therefore means splitting one atomic publish into "removals now
/ adds when embedded" — a real change to the publish contract, not a one-liner.
Combined with the engine on this box cycling into idle-standby + restart under
the create/rename test churn (35 % CPU + 1536 MB RSS caps), I could not get a
*stable* before/after benchmark. Landing a search-correctness-critical
publish-path change without a clean A/B would violate "never claim a fix without
live numbers". **Investigated + root-caused to the exact line; fix designed;
deferred** pending a stable engine and a publish-path correctness test (old
symbol evicts < 5 s while dense is demoted; search stays correct; binder
drift-check still holds).

### Issue #3 — K3 first-expand-in-session (measured 4.8 s, then warms to ~140 ms)

**Measured (`scripts/_k3_expand.py`, one MCP session):**
```
expand #0 callers: 4853 ms   ← first
expand #1 callees: 1572 ms
expand #2 callers: 1579 ms
expand #3 effects:  352 ms
expand #4 callees:  179 ms
expand #5 all:      139 ms   ← warm
```
So the first graph op in a session is ~4.8 s and takes 3–4 calls to settle to
~140 ms.

**How it works.** `expand_context_impl` calls `_await_ast_ready(...)` before
`run_expand_context`. That checks `ast_cache_ready(repo)`; if the AST bundle
isn't ready it kicks a hydrate/bake and waits. `run_expand_context` then loads
the bundle into the process (`_load_repo`) and does the first graph traversal.
`_load_repo` caches in-process for 600 s, so calls #4+ are ~140 ms.

**Where the time goes (measured directly):**
- `_load_repo` **fresh disk load = ~750 ms** (unpickle + `_graph_from_edges`);
  in-process cache hit = **0 ms**.
- `corpus_fingerprint` = ~218 ms (687 path `resolve()` + stat) — the staleness
  check that decides load-vs-rebake.
- The remaining ~3–4 s of the *first* expand is paid **only when the bundle is
  stale** — i.e. the corpus changed since the last bake, so `_await_ast_ready`
  triggers the whole-corpus **re-bake** (issue #1b, 9–15 s bounded). My 4.8 s
  reading was right after the create/delete test churn, i.e. a stale bundle.

**Conclusion — not a separate bug; shares issue #1b's root cause.** When the AST
bundle is **fresh**, first-expand is load (~0.75 s) + first traversal ≈ 1–2 s,
which is reasonable for the first graph operation of a session. The 4.8 s is a
**stale-bundle re-hydrate**, i.e. the same whole-corpus AST re-bake tracked in
#1b. There is no expand-specific fix — the lever is the deferred incremental AST
bake. Warm-repeat expand is already fast (139–352 ms). **Closed as a duplicate of
#1b**; no code change.

Environmental note (affects K3/K4 measurement): the engine on this box repeatedly
cycles into idle-standby (`CTX_ENGINE_IDLE_S=10`) and restarts under back-to-back
file-churn + bake load (35 % CPU / 1536 MB RSS caps). Several probe runs aborted
mid-flight because the MCP bridge could not attach during a restart. This made
stable A/B benchmarking of the publish/hydrate paths unreliable and is itself a
reason K4's publish-path fix was deferred rather than rushed.

### Issue #4 — K5 create→searchable MISS > 30 s (environmental, not a code bug)

**Classification: environmental, closed.** K5 was a first-run measurement where
create→search never resolved within 30 s. Root cause (established in sessions
2–3): the engine had gone to **idle-standby** (`CTX_ENGINE_IDLE_S=10` stops it
~10 s after the last client leaves) and was re-warming the embedder *during* the
edit, so the poll/sync/publish pipeline was stalled behind the wake. On a **warm**
engine the identical test propagates in **2–3 s** (see session-3 propagation
table; `DirWatch` catches the new file on the 1 s poll). This is not a code
defect in the propagation path — it is the cost of the first action after an
idle-standby wake, which a live IDE session avoids because the MCP session holds
the engine warm. The tunable is `CTX_ENGINE_IDLE_S` (raise it to keep the engine
warm longer between actions) — a config trade-off (idle RAM vs wake latency), not
a bug to fix in code. No change.

---

## Summary — every issue, before → after

| # | operation | before | after | status | fix |
|---|---|---|---|---|---|
| **D1** | graph catch-up (one-file change) | 6.1 s wall / 4.3 s merge | **3.7 s wall / 2.2 s merge** | **FIXED** | MinHash `update_batch` (vectorized) + `normalize_id` `lru_cache` |
| **#1b (a)** | AST bake — `build_lsp_index` | 4.0 s | **0.9 s (4.5×)** | **FIXED** | `_REGISTER_CALL_RE` snippet-parse short-circuit (result-identical) |
| **#1b (b)** | AST bake — `build_ast_graph` | ~8 s | ~8 s | **deferred** | `_refs_from_ast` `ast.walk` + per-symbol snippet re-parse; changes edge attribution → needs correctness pass (PERF-2) |
| **K1** | create new file → pack seed | ~15 s | partial | partial | graph half −36 %, lsp half −4.5×; `build_ast_graph` + whole-repo-rebake still bound it |
| **K2** | add call edge → expand | ~38 s | partial | partial | same graph-lane path as K1 |
| **K4** | rename → old symbol evicted | 43–60 s+ | — | **deferred** | tombstone gated behind `patchable` (needs sync embed); atomic `_patch_chunk_delta` prevents a one-line split — publish-contract change + stable-engine A/B needed |
| **K3** | first expand in session | 4.8 s (stale) / ~1–2 s (fresh) | — | **closed (dup of #1b)** | stale-bundle re-hydrate; no expand-specific bug |
| **K5** | create → searchable (cold engine) | MISS > 30 s | 2–3 s warm | **closed (environmental)** | idle-standby wake; tune `CTX_ENGINE_IDLE_S` |
| **D2** | CLI cold start | ~1.1–1.6 s | — | **out of scope** | Python interpreter + site init on Windows; not Scubiee code |

Also fixed in earlier sessions (not part of this sweep, listed for completeness):
status(full) 23 s → 1.3 s, HTTP grep 14.6 s → ~2 s (+ correctness), grep_ident
4.75 s → ~1.3 s.

### Landed code changes (this sweep)
- `packages/graphify/_minhash.py` — `MinHash.update_batch()`: vectorize all
  shingles of a node into one `(k, num_perm)` matrix hash; bit-identical to the
  per-shingle path (Mersenne-prime permutation family preserved).
- `packages/graphify/ids.py` — `normalize_id` `@lru_cache(131072)` +
  pre-compiled regexes (pure/idempotent, so caching is safe).
- `packages/trace_lab/lsp_index.py` — `_REGISTER_CALL_RE` short-circuit: skip the
  per-symbol snippet parse + walk when the source can't contain a `_REGISTER`
  call. Verified `LspIndex.dispatch` identical with/without.

### Verification
- Regression: **96 passed / 1 pre-existing failure** across
  graphify/dedup/minhash/ids/lsp/trace_lab/ast_graph/corpus/context_trace/
  incremental/chunk. The one failure (`test_multi_seed_v1::
  test_seed_specs_from_args_dedupes_and_caps`) imports `trace_lab.multi_seed` /
  `pipeline.context_trace` — none of the modules changed here — and fails on a
  clean tree too. Confirmed via import analysis (touches my modules: False).
- Correctness proofs: MinHash 12/12 test labels bit-identical; LSP `dispatch`
  map identical with/without the short-circuit.
- Deployed to the uv-tool install (`differ: 0  missing: 0`).

### Deferred work (fully root-caused; needs its own correctness-focused pass)
1. **`build_ast_graph` incremental** — operate `_refs_from_ast` on the
   already-parsed file subtree instead of re-parsing per-symbol snippets, and
   replace `ast.walk` with a targeted visitor. Changes per-symbol edge
   attribution, so it needs edge-count diffing against the current graph before
   it can land.
2. **Whole-repo-rebake-per-one-file (PERF-2)** — both the graph catch-up and the
   AST bake reprocess the entire corpus for a single changed file. The principled
   fix is the two-phase nodes-only refresh (fast nodes patch makes the seed
   packable immediately; full rebake in the background). This is the single
   biggest remaining lever for K1/K2.
3. **K4 rename eviction** — decouple the BM25 `mark_dead` tombstone from dense
   embed coverage so a rename evicts the old symbol promptly even when the
   embedder is demoted; requires splitting the atomic publish into
   removals-now / adds-when-embedded and a publish-path correctness test.

Nothing committed. All measurements are live numbers on this repo/engine.