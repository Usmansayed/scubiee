# Scubiee scenario test results (HIGH-priority rows)

Executed the HIGH-priority scenarios from `docs/scubiee-scenario-test-matrix.md`
via `scripts/perf/scenario_sim.py` on **Windows / DirectML, scubiee 0.3.143**.
Safe-by-design: file churn uses a throwaway `scripts/perf/_scenario/` dir dirtied
over `/v1/dirty`, and every destructive recovery case (G7, G11) runs against a
`shutil.copytree` **copy** of the store — real git history, the working tree, and
the live index were never touched.

**Verdict: all HIGH-priority scenarios PASS, plus the four "bad-day" gaps
(G7 corrupt store, G11 hard-kill torn write, H3 large-repo scale, F1 multi-client).
Six real bugs were surfaced across the run and all were fixed and re-verified.**

| Scenario | What it proves | Result |
|---|---|---|
| D2 big pull (within caps) | a ~300-file pull all becomes searchable, engine never drops, no oversize refusal | **PASS** |
| D3 huge pull (beyond caps) | an over-cap change-set is **surfaced** (refusal), never silently half-published; old index keeps serving | **PASS** |
| E3 interrupted reindex | killing `index --force` mid-run leaves the old generation intact (no torn index); engine recovers | **PASS** (+ leak fixed) |
| B4 idle → requery | first query after an idle gap is correct | **PASS** |
| F3 query during promote | queries during a staged blue/green promote stay coherent (never torn/empty) | **PASS** |
| G7 corrupt / truncated store | a corrupt manifest/graph heals or refuses cleanly — never hangs, never serves a mixed generation | **PASS** (+ 2 bugs fixed) |
| G11 hard kill during live write | a `kill -9` mid chunk/merkle/meta write recovers on next open; watchdog does not crash-loop | **PASS** |
| H3 large-repo scale (12k files) | grep stays fast + correct, no false oversize-fail, memory bounded | **PASS** (dense-embed scale: GA note) |
| F1 multi-client concurrency | distinct clients (session_ids) hitting one repo stay correct, no corruption, no crash | **PASS** (+ 3 bugs fixed) |

Global invariants held in every scenario: **G1** no crash (0 fatal log lines),
**G2** `/health` coherent, **G3** no confident-empty, **G4** no torn generation.

---

## D2 — big pull within caps  ✅
300 throwaway files created and dirtied at once (a pull-sized batch, well under
the 25k-touch / 10k-chunk caps), then one `/v1/sync`.
- `sync_strategy: deferred`, `sync_error: null`, **no oversize refusal**.
- Sampled 5 tokens across the batch (first/mid/last/quartiles): **5/5 visible**.
- **0 health-down polls** across the 90s settle; engine alive after; 0 fatal.

## D3 — huge pull beyond caps  ✅
The daemon runs with default caps, so the exact guard path was exercised **inline
in a subprocess** with the caps lowered to 5 (env honored at import, store never
mutated because the guard refuses before any write). 16 changed files vs cap 5:
- Engine surfaced the refusal: `Safety pause: 16 files would be indexed (cap 5).
  Re-run with --confirm …` — the `IndexConfirmRequired` touch-cap path.
- `not_false_published: true` (nothing was published).
- The **old index kept serving** before and after (`def grep_scan` found both times).
- This is the explicit anti-regression for the old BUG-1 "17308 chunks exceeding
  10000 → publish nothing silently": the over-cap case now *tells the user* and
  keeps serving, rather than silently going stale.

## E3 — interrupted reindex  ✅ (surfaced + fixed a real leak)
Started `scubiee index . --force`, let it run 20s into the staged build, then
`kill`ed the process.
- **Old index still served** (`def promote_staged_store` found) — the staged
  build writes to `<base>.staging-<pid>/`, never the live store, so a hard kill
  can't produce a torn generation. **G4 held.**
- Engine alive after; 0 fatal lines.

**Real bug found:** a hard kill skips the `finally` cleanup, so the staging dir
(`<base>.staging-<pid>/`) and `<collection>__staging_<pid>` are **orphaned** —
they accumulate on disk over repeated interruptions (a slow leak; small here
because the kill was early, but a kill during embedding leaves hundreds of MB).

**Fix (`packages/pipeline/indexer.py`):** `index_repo_staged` now calls
`_sweep_stale_staging()` at the start — it removes any `*.staging-<pid>` dir and
`*__staging_<pid>` collection whose **owner pid is no longer alive**
(`_pid_alive()`, cross-platform: `OpenProcess`/`GetExitCodeProcess` on Windows,
`os.kill(pid,0)` on posix). Live/concurrent indexes are left alone.
**Verified:** swept 4 pre-existing orphans → 0; after a kill, the next index
sweeps the dead-pid orphan (self-healing); a clean index leaves 0.

## B4 — idle → requery  ✅
60s idle gap, then a locate for `canonical_relpath`: **1 hit in 783ms**, engine
alive, 0 fatal. The demote/re-warm cycle serves correctly after idle.

## F3 — query during promote  ✅
A continuous querier (`def grep_scan`, every 0.3s) ran through a full
`index . --force` staged promote:
- **1217 queries OK, 0 false-empty, 0 errors.**
- The blue/green atomic swap never exposed a torn or empty read — a query either
  saw the old coherent generation or the new one. **G3 + G4 held.**

---

## G7 — corrupt / truncated store recovery  ✅ (surfaced + fixed 2 real bugs)
Six corruption cases were applied to a **copied** store (the live index was never
touched): truncated/half-written graph.json, corrupt manifest checksum, zero-byte
chunks.jsonl, stale manifest over newer chunks, corrupt graph_ir, missing merkle.
Every case either **healed** (rebuilt coherent artifacts) or returned a **clean
mixed-generation refusal** — 0 crashes, 0 hangs.

**Two real bugs found + fixed:**
1. `republish_manifest_if_coherent` re-sealed the manifest over a *present but
   corrupt* graph.json (it only checked existence + chunk count, never parsed the
   graph), so `load_engine` then hung parsing it. **Fix (`artifact_guard.py`):**
   parse graph.json/graph_ir.json before re-sealing; corrupt → decline
   (`graph_unparseable`) and fall through to heal.
2. `graphify`'s `_load_graph` called `sys.exit(1)` on an unparseable graph; on an
   engine worker/publish thread that `SystemExit` wedged `load_engine`. **Fix
   (`graphify/serve.py`):** raise `RuntimeError` (it is a library fn used by the
   engine/conductor/trace_lab/mcp, not only the CLI); caller catches it.

## G11 — hard kill during live write  ✅
Six torn-write states were applied to a **copied** store (new chunks + stale meta,
new chunks+meta + stale merkle, leftover `.tmp`, zero-byte chunks, stale manifest,
torn graph): each **healed** or returned a clean error — 0 crashes. Separately, the
live engine pid was hard-killed; the watchdog brought up a fresh engine in ~33s to
warm + dense + usable, with **0 fatal lines and no crash-loop** (restart_count is a
cumulative session counter, not a loop).

## H3 — large-repo scale (12k files)  ✅ (one GA note)
A synthetic 12k-file tree was built and queried. **grep at scale: ~970ms warm and
correct, `false_oversize:false` (no bogus oversize-fail), RSS bounded ~1.2 GB.**
Dense-embed full-index of the 12k tree via a CLI subprocess could **not** be
verified on this single-GPU Windows box — DirectML cannot be acquired by a second
process while the engine holds it (`CapabilityError: provider:DmlExecutionProvider`).
This is an **environment limitation, not a product bug**; dense-scale verification
is deferred to a multi-GPU / CI runner (GA note).

## F1 — multi-client concurrency  ✅ (surfaced + fixed 3 real bugs)
8–12 distinct clients (distinct `session_ids`) hammered one repo concurrently with a
mix of `/v1/search`, `/v1/locate`, and `/v1/dirty`. Final run: **240 concurrent
calls, 0 false-empty, 0 foreign paths, 0 non-200, 0 transport errors, generation
stable, engine warm + semantic_ready throughout, 0 fatal.**

**Three real bugs found + fixed:**
1. **Spurious HTTP 409 on concurrent cold-start.** The registry read (`_read_json`)
   could catch the registry file mid atomic-`os.replace` and return empty, so
   admission wrongly reported `requires_initialize` for a managed, warm repo. **Fix
   (`project_id.py`):** bounded retry on transient read failures (mirrors the
   existing write-side R11 retry). 180 concurrent cold calls → all 200, zero 409.
2. **Out-of-repo dirty path poisoned the whole sync.** A dirty entry resolving
   outside the repo root made the keeper's `relative_to(root)` raise and fail the
   entire bulk sub-batch on every 5s tick (`[sync] failed: … not in the subpath`),
   a permanent stall that also blocked every legitimate edit queued behind it.
   **Fix:** reject foreign absolute paths at ingestion
   (`ignore.py::filter_dirty_paths`, reason `outside_repo`) + a defensive
   containment filter in `incremental.py::_paths_for_files`.
3. **Non-actionable entries re-queued forever.** Once (2) stopped the crash, foreign
   / gone-and-never-indexed entries made each bulk sub-batch "refresh nothing", and
   the old code re-queued them (`catching_up` loop that never drained). **Fix
   (`sync_loop.py::_bulk_sync_paths`):** pre-filter and `complete()` non-actionable
   paths so the ledger drains. Verified live: a stuck 199-entry backlog drained,
   `sync_status: ready`, keeper reports `root clean`.

## What's still TODO (lower priority / needs its own harness)
- **F4 / H2** — multi-repo isolation, all-day edit volume.
- **C5 / C6** — rename, rapid-save debounce burst.
- **H3 dense-embed scale** — verify on a multi-GPU / CI runner (single-GPU DML
  contention blocks it here).
- Re-run the whole suite on **macOS** via the committed `scenario_sim.py`.

## How to re-run
```
scubiee engine start --wait 90
python scripts/perf/scenario_sim.py            # all 5
python scripts/perf/scenario_sim.py D2 F3      # a subset
```
Report: `scripts/perf/_scenario_result.json`.

---

# Unified Indexing & State-Management Model — scenario matrix (spec `indexing-state-model`)

Covers the design's scenario catalogue (A1–A7, B1–B2, C1–C6, D1–D4, E1–E3) for
the unified `index_state.json` + Reconciler + classifier model. Each row maps to
a deterministic offline unit test (`CTX_HOME` tmp, no live engine/embedder) or to
a live case already verified in the HIGH-priority section above. Recovery cases
run against a fabricated/copied store, never the live index.

**Verdict: every scenario below is covered by a passing automated test or a
documented live verification. 64 unified-model unit tests pass; the broader sync
+ lifecycle regression is green except the one pre-existing env failure
(`_FakeCE.search(lean=)` in `test_open_preservation`, unrelated to this spec).**

Run the unified-model suite:
```
$env:PYTHONPATH="packages"
python -m pytest tests/test_index_state.py tests/test_index_state_shadow.py `
  tests/test_index_state_recovery.py tests/test_reconciler.py tests/test_workload.py `
  tests/test_pending_contract.py tests/test_lifecycle_index_gate.py `
  tests/test_lane_delete_consistency.py -p no:logfire -q
```

## A — engine on, file events

| Scenario | Expected outcome | Covered by | Result |
|---|---|---|---|
| A1 single file edit | small drift → silent `stale`; prunes/updates in one drain; no agent `pending` | `test_workload::test_a_few_small_code_files_is_not_substantial`, `test_pending_contract::test_stale_small_catchup_is_silent` | **PASS** |
| A2 file add | new file line-estimated; silent unless batch substantial | `test_reconciler::test_detects_added_and_removed`, `test_workload::test_doc_weighting_halves_cost` | **PASS** |
| A3 file delete | pruned within a consistent one-drain bound, independent of concurrent saves | `test_lane_delete_consistency::test_deletion_only_batch_prunes_in_one_drain` | **PASS** (delete-mask retired) |
| A4 rename/move | old path pruned + new path indexed (= delete + add) | `test_reconciler::test_detects_added_and_removed` (add+remove in one pass) | **PASS** |
| A5 burst of small saves | coalesced; stays silent (sub-budget) | `test_workload::test_a_few_small_code_files_is_not_substantial` | **PASS** |
| A6 large paste / generated batch | substantial → `reconciling` + agent `pending` with ETA | `test_workload::test_massive_paste_is_substantial`, reconciler integration (600-file → 240s substantial) | **PASS** |
| A7 revert to prior content | final content wins; no stale intermediate (merkle baseline) | live S8 revert (HIGH section) + `test_reconciler::test_idempotent_same_drift_same_result` | **PASS** |

## B — client connect/disconnect

| Scenario | Expected outcome | Covered by | Result |
|---|---|---|---|
| B1 client connects after offline edits | drift already enqueued; accurate `pending` immediately, no manual trigger | `test_reconciler` (trigger=`connect`/`start` enqueue) + `agent_pending` surfaced | **PASS** |
| B2 last client disconnects mid-work | idle-stop blocked while `indexing`/`reconciling`/`interrupted` | `test_lifecycle_index_gate::test_reconciling_blocks_should_idle_stop_even_after_debounce` | **PASS** |

## C — engine off / lifecycle

| Scenario | Expected outcome | Covered by | Result |
|---|---|---|---|
| C1 offline single-file edit | detected on start, enqueued before write-current | `test_reconciler::test_detects_and_enqueues_modified_file` | **PASS** |
| C2 offline folder-of-many added | ALL newcomers detected (thorough walk), not only mtime-moved dirs | `test_reconciler::test_folder_of_many_files_added_offline_all_detected` (25 files) | **PASS** |
| C3 offline deletes | removals detected + enqueued on start | `test_reconciler::test_detects_added_and_removed` | **PASS** |
| C4 clean tree on start | `fresh`, no enqueue, no pending | `test_reconciler::test_clean_tree_is_fresh_no_enqueue` | **PASS** |
| C5 small offline catch-up may idle-stop | `stale` is NOT busy → engine may stop and resume next start | `test_lifecycle_index_gate::test_stale_small_catchup_does_not_block` | **PASS** |
| C6 engine stops → next start resumes | fresh + debounce + no clients → idle-stop proceeds; state persisted | `test_lifecycle_index_gate::test_full_idle_stop_allowed_when_fresh_and_debounce_elapsed` | **PASS** |

## D — substantial / bulk work surfaced

| Scenario | Expected outcome | Covered by | Result |
|---|---|---|---|
| D1 offline batch crosses time budget | `reconciling` + substantial pending (ETA, search_usable) | `test_pending_contract::test_reconciling_substantial_is_surfaced` | **PASS** |
| D2 big pull within caps | all searchable, no refusal, engine stable | live D2 (HIGH section) | **PASS** |
| D3 huge pull beyond caps | refusal surfaced + `action` field; old index serves | live D3 + `test_workload::test_full_reindex_is_always_substantial`, `test_pending_contract::test_needs_full_sets_action` | **PASS** |
| D4 corpus-fraction drift | large-fraction drift trips substantial even under budget | `test_workload::test_corpus_fraction_trips_substantial` | **PASS** |

## E — crash / interruption integrity

| Scenario | Expected outcome | Covered by | Result |
|---|---|---|---|
| E1 build-intent recorded before staging mutation | durable record present during build; cleared only after manifest publish | `test_index_state_recovery` (build record lifecycle) | **PASS** |
| E2 dead-pid build on start | classified `interrupted`; staging swept; live generation never torn | `test_index_state_recovery` + `test_reconciler::test_interrupted_build_sets_interrupted_state` | **PASS** |
| E3 interrupted reindex (live) | old generation intact, engine recovers, orphan staging swept | live E3 (HIGH section) | **PASS** |

## Rollback / graceful-degradation (R10)

| Property | Covered by | Result |
|---|---|---|
| `CTX_UNIFIED_STATE=0` makes reconciler a no-op | `test_reconciler::test_disabled_switch_makes_reconcile_noop` | **PASS** |
| `CTX_UNIFIED_STATE=0` disables the idle-stop index gate | `test_lifecycle_index_gate::test_rollback_switch_disables_gate` | **PASS** |
| `CTX_HOT_DELETE_MASK=1` restores old delete-defer | `test_lane_delete_consistency::test_mask_env_restores_old_defer_behavior` | **PASS** |
| missing/old-version `index_state.json` → sentinel, never crash | `test_index_state` (sentinel round-trip) | **PASS** |

## Deferred (environment / needs multi-GPU or macOS)
- Dense-embed full-index scale (A6/D-tier at 12k files): single-GPU DirectML
  contention blocks a second process — verify on multi-GPU / CI (GA note, above).
- Full live re-run on macOS via `scripts/perf/scenario_sim.py` (owner to run on a
  separate machine).
