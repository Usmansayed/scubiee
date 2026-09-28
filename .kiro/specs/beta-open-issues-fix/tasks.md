# Implementation Plan

## Overview

Fix order: OPEN-B → OPEN-D → OPEN-C → OPEN-E/F → OPEN-A → OPEN-G → OPEN-H/J → OPEN-I/K. OPEN-L is DEFERRED (tasks 9, 20.3, 20.5 are optional `[ ]*` and not queued).
Methodology: exploration tests on UNFIXED code first (Properties 1, 3–8 bug conditions, plus the design's "to verify" items), preservation tests on UNFIXED code (Property 2), then one fix at a time with fix-check + preservation-check.

Definition of done: sync-uv-install.ps1 (PYTHONPATH cleared) + reload MCP + live battery after patches; unit tests alone are not green.

Ground rules for every task:
- Code locate/read goes through the Scubiee MCP ladder only (`map` → `pack_context` lean → `expand_context` / `collect_hot_context`), `project_id=ce_3536ac8e8e83bb8e4d888db37847729c`, `root=c:\Users\usman\Downloads\context-engine`. Edit/Write/Shell stay native. Spec files, docs, and non-code config (`.cursor/mcp.json`, `.kiro/settings/mcp.json`) may be read directly.
- Tests: `python -m pytest -p no:logfire -q -p no:cacheprovider <paths>` (the conda base logfire plugin is broken).
- After any code change: `Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue; powershell -File scripts/sync-uv-install.ps1` (expect `differ: 0 missing: 0`, `ignore.py` present), then reload Scubiee MCP in the IDE.
- Minimal focused patches. No drive-by refactors. No commits.
- Property-based tests use seeded generators, not Hypothesis: a module-level `random.Random(<fixed seed>)` builds the cases, fed through `pytest.mark.parametrize` (print the seed and case id on failure so counterexamples reproduce). Same invariants as the design's properties. Do NOT install Hypothesis.

Acceptance battery reference (run from repo root, PowerShell, `PYTHONPATH` cleared, uv-tool install). Checkpoints below refer to these labels. Record measured timings and `ok` flags for every step.
- AB-0: `scripts/sync-uv-install.ps1` → `differ: 0 missing: 0`, `ignore.py` present; reload MCP.
- AB-1: MCP `gate` → `index_skip` + `index_write_hint`; MCP `status(detail=full)` → `pack_ready=true`, `ast_hydrated=true`, `warm_wait.done=true`, `warm_deadline_ms == CTX_WARM_DEADLINE_MS` (90000), `warm_deadline_source`.
- AB-2: `python scripts/attach_pack_race.py --sessions 2 --packs 3` → `ok=true`, first pack `n_heat>0`.
- AB-3: `$env:CTX_PROBE_SLA_S='8'; $env:CTX_PROBE_TRIALS='5'; python scripts/live_sync_probe.py` → ≥4/5 within 8 s, none routinely >10 s; plus one idle single round (~4.5 s, `publish=patch`). `engine.log`: no binder-drift storm, cleanup does not force full reload + `vec_open` >3 s on the next save, no `[sync] no chunk delta … ms=10` for gone probe paths, `/v1/dirty` latency <200 ms.
- AB-4: `python scripts/engine_kill_recover_probe.py --hold-bridge --budget-s 120` → `ok=true`.
- AB-5: live MCP ladder after reload: `map` → `pack_context` lean → `expand_context` callers → `collect_hot_context` (no `ast_warming` thrash, at most one bounded retry on fresh attach); `expand_context direction=config` on a node with no config edges → `empty_reason="no_edges"`; `pack_context include_bodies=1` on `BackgroundSyncLoop` → `loc` clamped + `full_loc`, text unchanged (cap unset); first map after attach → timings sum ≥80% of `elapsed_ms`.
- AB-6: `Select-String "$env:USERPROFILE\.scubiee\engine.log" -Pattern "newcomer scan failed"` → none repeating; `-Pattern "\[warm-stage\]"` → 6 stages on cold start; ensure→`embedder_loaded` wall ms; peak Scubiee RSS; process tree = one bridge→locate→engine chain per IDE + watchdog.
- AB-7 (always LAST): `python scripts/mcp_host_sim.py --lane a --live --skip-idle --settle-s 35` → `ok=true` incl. `pack_first`; then reload MCP (host-sim kills IDE bridges).

## Tasks

- [x] 0. Refresh the Kiro workspace MCP entry and capture the unfixed baseline
  - [x] 0.1 Refresh `.kiro/settings/mcp.json` to match the Cursor Scubiee entry (APPROVED by the user)
    - Back up first: copy `.kiro/settings/mcp.json` to `.kiro/settings/mcp.json.bak-open-b` (reversible; restore by copying back)
    - Current state: `command` = `C:/Users/usman/Downloads/context-engine/.venv-cli-test/Scripts/scubiee-mcp-bridge.EXE`, `args: []`, 17 env keys, no `CTX_WARM_DEADLINE_MS`
    - Source of truth: the Cursor entry `mcpServers.scubiee` in the workspace `.cursor/mcp.json` (`%USERPROFILE%\.cursor\mcp.json` does not exist on this host). Fallback if it is missing at execution time: derive from `uv tool dir` → `<uv tool dir>\scubiee\Scripts\pythonw.exe`
    - Rewrite `mcpServers.scubiee` in `.kiro/settings/mcp.json`:
      - `command`: copy exactly from Cursor (currently `C:/Users/usman/AppData/Roaming/uv/tools/scubiee/Scripts/pythonw.exe`, the uv-tool interpreter's `pythonw`)
      - `args`: copy exactly from Cursor (currently `["-u", "-m", "pipeline.mcp_bridge"]`)
      - `env`: copy every Cursor env key and value (currently 33 keys, including `CTX_WARM_DEADLINE_MS=90000` and `CTX_MCP_BRIDGE_SPAWN_JSON` pointing at the same `pythonw -u -m pipeline.mcp_locate`), then set `CTX_MCP_CLIENT` back to Kiro's value `kiro`
      - Shared keys take the Cursor value. Today that changes `CTX_MCP_BRIDGE_MODE` auto→shared, `CTX_ENGINE_IDLE_S` 25→10, `CTX_ENGINE_TRANSITION_DEBOUNCE_S` 25→5; record these in the fix log
      - Keep Kiro-only keys as they are: `disabled`, `autoApprove`, `alwaysAllow`, and any Kiro-only env key. Do not add the Cursor-only `windowsHide` field. Do not touch other servers in either file
    - Validate the JSON parses (`Get-Content … | ConvertFrom-Json`) before asking the user to reload
    - The user reloads Scubiee MCP in Kiro. Then MCP `status(detail=full)`: confirm the bridge/locate run from the uv-tool install (`…\uv\tools\scubiee\…`) and read `warm_deadline_ms`. Expected 90000; it may still show 30000 until task 10 if the reader bug persists. Record whatever is observed as a baseline data point
    - _Requirements: 2.1_
  - [x] 0.2 Capture baseline on unfixed code (for before/after comparisons)
    - Run AB-0, AB-1, AB-2, AB-3, AB-4 and the AB-6 log/RSS/process-tree checks on the UNFIXED code. Do not run AB-7 yet.
    - Record: `status.warm_deadline_ms`, probe pass rate + per-trial `search_ms`, `publish_call_ms`/`vec_open_ms` after cleanup, binder-drift count, `no chunk delta` durations, `/v1/dirty` latency, first-map `elapsed_ms` vs `embed_ms + retrieve_ms`, peak warm RSS, process tree.
    - Keep the numbers in a scratch note for the fix log (task 22). Do not edit product code.
    - _Requirements: 1.1, 1.5–1.10, 1.14, 1.16–1.18_

- [x] 1. Write bug condition exploration test for the warm deadline (OPEN-B)
  - **Property 1: Bug Condition** - Warm deadline is one effective value
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that show the two deadline readers disagree with the install pin
  - **Scoped PBT Approach**: generate env values for `CTX_WARM_DEADLINE_MS` (unset, valid ints, invalid strings, values <1000)
  - New file `tests/test_open_b_warm_deadline.py`
  - Bug condition: `isBugCondition(StatusCall{env})` = `effectiveDeadline(env) != 30000 AND reported.warm_deadline_ms == 30000`, or two surfaces disagree for the same env
  - Assert (expectedBehavior): `warm_contract.warm_deadline_ms()`, `runtime_controller.warm_deadline_ms()`, `ReadySnapshot.as_status_fields()["warm_deadline_ms"]`, `warm_status_fields()["warm_deadline_ms"]`, `start_attach_warm_pipeline(...)["deadline_ms"]` (fakes, no live HTTP) all equal `effective_warm_deadline_ms(env)`: `max(1000, int(env))` when set and valid, else 90000
  - Assert `warm_deadline_source` is `"env"` when set, `"default"` otherwise
  - Concrete case: env unset → readers return 30000 (counterexample); env=90000 → confirm which surface already reports 90000
  - Run on UNFIXED code. **EXPECTED OUTCOME**: FAILS. Document counterexamples (e.g. "env unset: runtime_controller.warm_deadline_ms() == 30000, install pin 90000")
  - _Requirements: 1.1, 1.2, 2.1, 2.2_

- [x] 2. Write preservation property tests (BEFORE implementing any fix)
  - **Property 2: Preservation** - Non-buggy inputs behave as before
  - **IMPORTANT**: Follow observation-first methodology. Run each case on UNFIXED code, record the observed output as a golden, then assert it
  - New file `tests/test_open_preservation.py` (goldens under `tests/fixtures/open_preservation/` if needed)
  - Status shape (3.6): observe the key set of `as_status_fields()` / `warm_status_fields()` and the `warm_wait` fields (`done`, `stage`, `wait_for`, `soft_ready`, `dense_ready`, `pack_ready`, `elapsed_s`, `retry_after_s`, `note`) and the stage order `engine_down → soft_loading → dense_loading → pack_ast_loading → ready`. Property: for generated readiness tuples, the fixed key set is a superset and the stage for each tuple is unchanged
  - Deadline with env already pinned (non-bug input): env=90000 surfaces that report 90000 today keep reporting 90000
  - Idle hot save (3.7): single existing-file `probe_write` on an idle ledger through `drain_due` with fake `_sync_paths` → `publish=patch`, same stage sequence, `_hot_vdb_cache` reused
  - Kill switches (3.9): `CTX_HOT_PUBLISH=0` → full publish path, same as observed
  - Ledger scheduling (3.8, 3.10, 3.11): generated interleavings of `mark(hot|disk_poll|graph_catchup)`, `begin`, `complete`, `drain_due` over a small path set where no newcomer tick overlaps an in-flight entry and no batch is deletion-only → every path reaches `published`, graph catch-up runs only outside the quiet window and clears `graph_pending`
  - Hydrated expand/collect (3.12): `run_expand_context` callers/effects on fixture nodes with non-empty deltas → deltas equal observed goldens; `empty_reason` absent; existing `test_expand_after_pack`, `test_pack_expand_parallel`, `test_expand_caller_ranking` pass
  - Pack contract (3.1): observe the exact `ast_warming` payload (`should_retry`, `retry_after_s`, `ast_wait_ms`, other keys) when `ast_hydrated()` is false
  - Error paths (3.14): empty/`_` seed and unknown expand handle → same `ok=false` payloads
  - Body clamp (3.5): `include_bodies=1` pack item for a class node → `loc` clamped, `full_loc` present, `text` byte-identical (cap env unset)
  - Live chain safety (3.18): generated process tables containing a live IDE → bridge → locate → engine chain plus watchdog → `reap_orphaned_mcp_processes` / `sweep_orphan_scubiee_frontends` kill nothing in that chain
  - HTTP contract (3.15): `/health`, `/v1/dirty`, search handler response shapes recorded with a fake runtime
  - Run the existing suite once and record the currently passing set (3.19)
  - Run on UNFIXED code. **EXPECTED OUTCOME**: all new preservation tests PASS
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14, 3.15, 3.16, 3.17, 3.18, 3.19_

- [ ] 3. Write bug condition exploration test for the newcomer scan (OPEN-D)
  - **Property 3: Bug Condition** - Newcomer scan runs and never disturbs in-flight entries
  - **CRITICAL**: MUST FAIL on unfixed code. **DO NOT fix code or test when it fails**
  - New file `tests/test_open_d_newcomer.py`
  - Case A (signature): `_start_newcomer_scan(now=...)`, join the scan thread, capture stderr → unfixed contains `newcomer scan failed … missing 1 required keyword-only argument: 'now'`
  - Case B (in-flight reset, property): generated ledgers where some paths are `queued`/`due`/`processing`/`overlay_ready` with hot reasons (`probe_write`, `write`); monkeypatch `root_probe` to report them as added; call `_enqueue_newcomers(now=...)` directly. Assert every in-flight entry keeps its state, reason and `due_at`. Unfixed counterexample: `a.py` goes `processing/probe_write` → `queued/disk_poll`
  - Case C (throttle/quiet): with a hot entry due or `now - _last_hot_mark_at < CTX_NEWCOMER_QUIET_S`, the `_run` kick must not start a scan; at most one scan per `CTX_NEWCOMER_SCAN_S`
  - To verify (measure only, no assertion): wall time of the `collect_index_relpaths` walk on this repo and whether a concurrent hot save stretches while it runs (GIL contention). Record the numbers
  - Run on UNFIXED code. **EXPECTED OUTCOME**: Cases A–C FAIL. Document counterexamples
  - _Requirements: 1.3, 1.4, 2.3, 2.4_

- [ ] 4. Write bug condition exploration tests for hot sync under churn (OPEN-C)
  - **Property 4: Bug Condition** - Hot lane under add/delete churn
  - **CRITICAL**: MUST FAIL on unfixed code. **DO NOT fix code or test when it fails**
  - New file `tests/test_open_c_hot_churn.py`
  - (a) Deletion-only hot batch: ledger with two missing `probe_write` paths (`f1.py`, `__init__.py`) → `drain_due` with fake `_sync_paths` returning `chunks_removed=2`, `hot_delta=None`. Assert no full publish inside the hot window and the paths are masked from search. Unfixed: `_notify_refresh` full publish
  - (b) vdb cache drop: seed `_hot_vdb_cache` with a fake vdb + matching fingerprint, run `_sync_paths(hot=False)` with `incremental_sync` monkeypatched. Assert the cache survives (or is refreshed). Unfixed: cache is `None`. Also check whether non-hot `incremental_sync` accepts an external `vdb=` (design fallback depends on it)
  - (d) Gone paths: `graph_catchup` entry for a path missing on disk and absent from the store, processed after the quiet window → assert `incremental_sync` is NOT called. Unfixed: it is called
  - (e) Hot-first deferral: non-hot batch due while a hot entry is `queued` → assert it is deferred by `hot_debounce_ms + 250 ms`
  - (f) `/v1/dirty`: with a fake `ce.sync_loop` for the same repo, assert `admit()` is not called. Unfixed: admission runs per request
  - To verify (measure, live, uses temporary logging behind `CTX_DEBUG_SYNC=1`, removed or kept gated afterwards):
    - Binder drift source (c): during one AB-3 run, log `(base_chunk_count, len(chunks), last_writer, pending_publish, last payload status)` at every `hot patch declined`
    - `/v1/dirty` admission cost (e): time `admit_request` with the keeper idle and during a full publish; log `admit_ms`
  - If a "to verify" hypothesis is refuted, stop and send that item back to root-cause analysis in design.md before patching
  - Run on UNFIXED code. **EXPECTED OUTCOME**: (a), (b), (d), (e), (f) FAIL. Document counterexamples and the measured drift/admission numbers
  - _Requirements: 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10_

- [ ] 5. Write bug condition exploration tests for expand/collect readiness and empty reasons (OPEN-E, OPEN-F)
  - **Property 5: Bug Condition** - Expand/collect readiness and empty reasons
  - **CRITICAL**: MUST FAIL on unfixed code. **DO NOT fix code or test when it fails**
  - New file `tests/test_open_ef_expand.py`
  - Case A: `run_expand_context(direction="config")` on a fixture node with no config edges → assert `empty_reason == "no_edges"`. Unfixed: `ok=true, delta=[]`, no reason
  - Case B: prior-filter empties the delta → `empty_reason == "already_expanded"`; unresolved node → `ok=false`, `error` kept, `empty_reason == "node_unresolved"`
  - Case C: MCP `expand_context` and `collect_hot_context` tool bodies with `ast_hydrated()` false and a hydrate that completes after ~1 s → assert they wait (bounded by `CTX_MCP_PACK_AST_WAIT_S`) and succeed. With hydrate never completing → `ok=false, error="ast_warming", empty_reason="ast_not_ready", should_retry=true, retry_after_s, ast_wait_ms`. Unfixed: returns in <50 ms
  - Property: generated expand inputs over the fixture graph → `delta == []` ⇔ `empty_reason` present
  - Run on UNFIXED code. **EXPECTED OUTCOME**: FAILS. Document counterexamples
  - _Requirements: 1.11, 1.12, 1.13, 2.11, 2.12, 2.13_

- [ ] 6. Write bug condition exploration tests for warm stages and first-map attribution (OPEN-A, OPEN-G)
  - **Property 6: Bug Condition** - Warm and first-map time is attributed
  - **CRITICAL**: MUST FAIL on unfixed code. **DO NOT fix code or test when it fails**
  - New file `tests/test_open_ag_timings.py`
  - Case A: a cold-start simulation with fakes emits no `[warm-stage]` lines → assert 6 stages (`engine_up`, `soft`, `embed_plan`, `embed_load`, `dense_ready`, `pack_ready`) with monotonic `t_ms`. Unfixed: none
  - Case B: soft ready, dense not ready → `warm_wait.done == false`, stage in `{soft_loading, dense_loading}`, note says soft-only, deadline from the unified reader
  - Case C: map with a monkeypatched slow `admit_request` (2 s) → assert named timing stages sum ≥80% of `elapsed_ms`. Unfixed: <20%
  - To verify (live, measure only): the gap after `[embed] plan` during one cold start. Count `prewarm_embedder_async` re-entries while running, `/v1/client/touch` / `register_client` → `ensure_embed_keepalive_loop` re-arms, FAISS/`load_engine` re-opens during prewarm, concurrent locate-worker AST hydrates, and newcomer walks. Record which ones occur
  - Run on UNFIXED code. **EXPECTED OUTCOME**: Cases A and C FAIL; record Case B observation. Document counterexamples and thrash counts
  - _Requirements: 1.14, 1.15, 1.16, 2.14, 2.15, 2.16_

- [ ] 7. Write bug condition exploration tests for process trees and warm concurrency (OPEN-H, OPEN-J)
  - **Property 7: Bug Condition** - One chain per IDE session
  - **CRITICAL**: MUST FAIL on unfixed code. **DO NOT fix code or test when it fails**
  - New file `tests/test_open_hj_process_tree.py` (fake process tables; never touch real processes)
  - Case A (PID reuse): a locate whose `ppid` is alive but whose parent `create_time` is after the locate's → assert it is classified orphaned. Unfixed: skipped
  - Case B: two `mcp_locate` children under one bridge → assert only the newest is kept
  - Case C: two engine processes → assert only the `:8765` owner is kept; watchdog untouched
  - Property: generated tables (pids, ppids, create_times, cmdlines) → the kill set equals exactly the provably orphaned/duplicate set and never includes the live chain or watchdog
  - Case D: two workers call the heavy-warm section concurrently → at most `CTX_WARM_HEAVY_CONCURRENCY` (default 1) run at once. Unfixed: both run
  - To verify: read the `mcp_bridge` child respawn path (via the Scubiee ladder) and confirm whether the previous `Popen` is terminated before respawn. Record peak Scubiee RSS during one cold warm and the live process tree (baseline from 0.2 is acceptable)
  - Run on UNFIXED code. **EXPECTED OUTCOME**: Cases A–D FAIL. Document counterexamples
  - _Requirements: 1.17, 1.18, 2.17, 2.18_

- [ ] 8. Record bug condition for tests and HTTP pack (OPEN-I, OPEN-K)
  - **Property 8: Bug Condition** - Tests and HTTP pack decision
  - Run the four tests on UNFIXED code: `tests/test_lifecycle_ownership.py::test_attach_mcp_session_is_nonblocking`, `tests/test_attach_warm_pipeline.py::test_start_attach_warm_pipeline_returns_immediately`, `tests/test_live_reindexing.py::test_final_check_forces_held_publish`, `tests/test_watchdog.py::test_watchdog_child_stays_alive_then_exits_clean` (run the watchdog test 5× to measure flake rate)
  - Expected counterexamples (design): `warm_calls == []`; 1.70 s > 0.5 s from synchronous `_probe_health`; `publish_delivered False` with 1 upsert; watchdog timing flake
  - Needle search `scripts/` for literal `/v1/pack` (Scubiee `grep`) and record hits
  - Confirm `server.Handler.do_POST` has no `/v1/pack` route (404) and that `docs/production-ready-0.3.131.md` has no MCP-only note
  - **EXPECTED OUTCOME**: first three tests FAIL, watchdog flakes or passes; decision undocumented. Document results
  - _Requirements: 1.19, 1.20, 2.19, 2.20_

- [ ]* 9. Write bug condition exploration test for the optional class body cap (OPEN-L, DEFERRED)
  - **Property 9: Bug Condition** - Optional class body cap
  - Deferred by the user: optional and not queued. Run only if OPEN-L is re-queued
  - **CRITICAL**: MUST FAIL on unfixed code. **DO NOT fix code or test when it fails**
  - New file `tests/test_open_l_body_cap.py`
  - With `CTX_MCP_PACK_CLASS_BODY_MAX_LINES=N` (generated N), an `include_bodies=1` pack item from a class node (fixture shaped like `BackgroundSyncLoop`) → assert `lines(text) <= N`, `text_truncated=true`, `full_loc` present. Unfixed: full class text
  - With the env unset → text byte-identical to the Property 2 golden
  - **EXPECTED OUTCOME**: capped case FAILS; unset case passes
  - _Requirements: 1.21, 2.21, 3.5_

- [ ] 10. Fix OPEN-B: unify the warm deadline reader

  - [x] 10.1 Implement the fix
    - `packages/pipeline/warm_contract.py`: keep `warm_deadline_ms()` as the only reader; `DEFAULT_WARM_DEADLINE_MS = 90_000`
    - `packages/pipeline/runtime_controller.py`: `warm_deadline_ms()` delegates to `warm_contract.warm_deadline_ms` (name kept for existing importers)
    - Add `warm_deadline_source: "env" | "default"` next to `warm_deadline_ms` in `as_status_fields` and `warm_status_fields` (additive)
    - `packages/pipeline/mcp_lifecycle.py`: call sites only, if any read a separate default (attach health deadline)
    - _Bug_Condition: isBugCondition(StatusCall{env}) where effectiveDeadline(env) != 30000 AND reported == 30000, or surfaces disagree_
    - _Expected_Behavior: all deadline fields == effective_warm_deadline_ms(env) (Property 1)_
    - _Preservation: status keys superset, warm_wait fields and stage order unchanged (3.6)_
    - _Requirements: 2.1, 2.2, 3.6_

  - [x] 10.2 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Warm deadline is one effective value
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - **EXPECTED OUTCOME**: Test PASSES
    - _Requirements: 2.1, 2.2_

  - [x] 10.3 Verify preservation tests still pass
    - **Property 2: Preservation** - Non-buggy inputs behave as before
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - **EXPECTED OUTCOME**: Tests PASS

  - [ ] 10.4 Sync install and check live status
    - AB-0, then MCP `status(detail=full)`: `warm_deadline_ms == 90000`, `warm_deadline_source` present
    - _Requirements: 2.1_

- [ ] 11. Fix OPEN-D: newcomer scan call and hot-path isolation

  - [ ] 11.1 Implement the fix
    - `packages/pipeline/sync_loop.py` `_start_newcomer_scan._scan`: call `self._enqueue_newcomers(now=time.monotonic())`
    - `_enqueue_newcomers`: skip paths whose ledger state is in `{"queued","due","processing","overlay_ready"}` and any hot-reason entry (same filter as `poll_repo_changes`)
    - `_run`: skip the kick while `_hot_work_pending(now)` (hot entry queued/due/processing, or within `CTX_NEWCOMER_QUIET_S`, default 10 s) or `self._syncing`; interval from `CTX_NEWCOMER_SCAN_S` (default 60)
    - Walk stays on its own thread via `root_probe(discover_newcomers=True)` (keeps junk + `.scubieeignore` filtering). Add `time.sleep(0)` yields in the walk only if task 3's measurement showed GIL contention
    - _Bug_Condition: NewcomerTick where scan raises TypeError, mutates an in-flight entry, or holds the keeper during a hot save_
    - _Expected_Behavior: noException AND inFlightEntriesUnchanged AND respectsThrottleAndQuiet (Property 3)_
    - _Preservation: newcomers still discovered, junk skipped, ignores honored (3.10); idle hot save unchanged (3.7)_
    - _Requirements: 2.3, 2.4, 3.7, 3.10_

  - [ ] 11.2 Verify bug condition exploration test now passes
    - **Property 3: Expected Behavior** - Newcomer scan runs and never disturbs in-flight entries
    - **IMPORTANT**: Re-run the SAME tests from task 3 - do NOT write new tests
    - **EXPECTED OUTCOME**: Tests PASS
    - _Requirements: 2.3, 2.4_

  - [ ] 11.3 Verify preservation tests still pass
    - **Property 2: Preservation** - Non-buggy inputs behave as before
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - **EXPECTED OUTCOME**: Tests PASS

- [ ] 12. Checkpoint - OPEN-B + OPEN-D on the live install
  - sync-uv-install.ps1 (PYTHONPATH cleared) + reload MCP + live battery after patches; unit tests alone are not green
  - AB-0, AB-1, AB-2, AB-3, AB-6 (newcomer line only)
  - Pass criteria: AB-1 deadline 90000; AB-2 ok; no repeating `newcomer scan failed`; AB-3 pass rate not worse than the 0.2 baseline (the naive fix gave 0/5 — that must not happen). The full ≥4/5 bar is expected only after OPEN-C
  - Report measured timings and `ok` flags. Ask the user if questions arise
  - _Requirements: 2.1, 2.3, 2.4, 3.1_

- [ ] 13. Fix OPEN-C: hot sync under add/delete churn

  - [ ] 13.1 Skip reconcile for gone, unindexed paths
    - `sync_loop.drain_due`: before Tier-1, split out paths missing on disk with `counts.get(path, 0) == 0` from `_estimate_dirty_chunks` (returned as a set) and reason in `{graph_catchup, disk_poll, retry}`; complete them `published=True` without `incremental_sync`
    - `_hold_graph_catchups`: drop `graph_catchup` entries whose path no longer exists
    - _Bug_Condition: SyncEvent where batch.allPathsGoneAndUnindexed AND jobRunsOnKeeper_
    - _Requirements: 2.8, 3.11_

  - [ ] 13.2 Keep the hot vdb cache across keeper-owned non-hot syncs
    - `_sync_paths(hot=False)`: when `self._hot_vdb()` returns a valid cached vdb, pass it to `incremental_sync(..., vdb=vdb)` and refresh `self._hot_vdb_cache = (vdb, _vdb_fingerprint(vdb))`; drop only if the vdb was not passed or the sync raised
    - If task 4(b) showed non-hot `incremental_sync` rejects an external vdb: keep the drop and add a background reopen that runs only when no hot entry is due
    - Kill switch `CTX_HOT_VDB_CACHE=0` keeps current behavior
    - _Bug_Condition: prevWriterNonHot AND nextHotSave.vec_open_ms > 3000_
    - _Requirements: 2.6, 3.8, 3.9_

  - [ ] 13.3 Mask deletions in the hot window, publish later
    - `drain_due`: when every Tier-1 path is missing and a hot entry is pending or was marked within `graph_catchup_quiet_s`, call new `RuntimeManager.mask_deleted_paths(paths)` (`ce_service.py`, via the `on_refresh` side channel used by `_hot_publish_runtime`) → `WarmSearchEngine._masked_files` (`engine.py`)
    - Search result assembly drops hits in `_masked_files` (pin the exact site via the Scubiee ladder); mask cleared when a new binder is published
    - Defer the batch with non-hot reason `deletion_catchup` to the end of the quiet window; it then runs the normal full publish
    - Kill switch `CTX_HOT_DELETE_MASK=0` keeps current behavior
    - _Bug_Condition: SyncEvent where batch.isDeletionOnly AND publishKind == "full" inside the hot window_
    - _Requirements: 2.5, 3.8, 3.9_

  - [ ] 13.4 Prevent binder drift
    - Before a hot publish, if `self._pending_publish is not None` or the last non-hot payload ended `dense_pending`/`publish_failed`, call `drain_publish(force=True)` first
    - On decline, log `base_chunk_count`, live count and last writer (keep the log; it is cheap)
    - Adjust per the drift source measured in task 4 if it differs from the design hypothesis
    - _Bug_Condition: binder.count != disk.chunkCount AND hotPatchAttempted_
    - _Requirements: 2.7_

  - [ ] 13.5 Hot-first deferral of non-hot batches
    - After `_split_explicit_writes`, if `writes` is empty but a hot-reason entry is `queued` (not yet due), defer the non-hot paths by `hot_debounce_ms + 250 ms`
    - _Requirements: 2.5, 2.8_

  - [ ] 13.6 `/v1/dirty` fast path
    - `packages/pipeline/server.py` `Handler.do_POST`: for `/v1/dirty` and `/v1/note_locate`, when `ce.sync_loop` is running and `Path(root).resolve() == ce.sync_loop.repo`, skip `admit()` and call `ce.mark_dirty` directly. Same response shape; all other routes keep admission
    - Security note: no auth change; the route was already unauthenticated loopback, and the fast path only applies to the already-admitted active repo
    - _Bug_Condition: DirtyPost where keeperBusy AND dirtyLatencyMs > 500_
    - _Expected_Behavior: latencyMs <= 200_
    - _Requirements: 2.9, 3.15_
    - Combined annotations for 13.1–13.6:
    - _Bug_Condition: isBugCondition(SyncEvent | DirtyPost) from design_
    - _Expected_Behavior: expectedBehavior SyncEvent/DirtyPost (Property 4)_
    - _Preservation: 3.7 idle patch ≈4.5 s, 3.8 no stale hits + flush-before-reload, 3.9 kill switches, 3.11 catch-up after quiet window, 3.15 HTTP contract_
    - _Requirements: 2.5, 2.6, 2.7, 2.8, 2.9, 2.10_

  - [ ] 13.7 Verify bug condition exploration tests now pass
    - **Property 4: Expected Behavior** - Hot lane under add/delete churn
    - **IMPORTANT**: Re-run the SAME tests from task 4 - do NOT write new tests
    - **EXPECTED OUTCOME**: Tests PASS
    - _Requirements: 2.5, 2.6, 2.7, 2.8, 2.9_

  - [ ] 13.8 Verify preservation tests still pass
    - **Property 2: Preservation** - Non-buggy inputs behave as before
    - **IMPORTANT**: Re-run the SAME tests from task 2 plus tasks 1 and 3 - do NOT write new tests
    - **EXPECTED OUTCOME**: Tests PASS

- [ ] 14. Checkpoint - hot lane at the owner bar
  - sync-uv-install.ps1 (PYTHONPATH cleared) + reload MCP + live battery after patches; unit tests alone are not green
  - AB-0, AB-1, AB-2, AB-3 (5 trials + idle single round), AB-4, AB-6 (newcomer line)
  - Pass criteria: AB-3 ≥4/5 within 8 s, none routinely >10 s, idle round ~4.5 s `publish=patch`; engine.log shows no binder-drift storm, cleanup does not force full reload + `vec_open` >3 s, no 10 s `no chunk delta` on gone paths, `/v1/dirty` <200 ms; AB-4 `ok=true`
  - Report per-trial `search_ms`, `publish_call_ms`, `vec_open_ms`, `/v1/dirty` latency vs baseline. Document any irreducible cases. Ask the user if questions arise
  - _Requirements: 2.5–2.10, 3.3, 3.7, 3.8_

- [ ] 15. Fix OPEN-E/F: expand/collect readiness and empty_reason

  - [ ] 15.1 Implement the fix
    - `packages/pipeline/mcp_locate.py`: extract the inline hydrate wait from the `pack_context` tool body into module-level `_await_ast_ready(tool, repo) -> dict | None`; pack calls it with identical behavior; payload gains `empty_reason: "ast_not_ready"`
    - `expand_context` and `collect_hot_context` tool bodies call `_await_ast_ready` first (flag check only when hydrated)
    - `packages/pipeline/context_trace.py` `run_expand_context`: unresolved → `ok=false`, keep `error`, add `empty_reason: "node_unresolved"`; empty delta → `"already_expanded"` if pre-prior-filter candidates were non-empty, else `"no_edges"`; key absent on non-empty deltas
    - Ensure `mcp_response_lean` keeps `empty_reason`
    - _Bug_Condition: ExpandCall/CollectCall where NOT astReady AND returnsImmediately, or delta == [] without empty_reason_
    - _Expected_Behavior: Property 5_
    - _Preservation: 3.1 pack contract identical apart from added empty_reason; 3.12 hydrated deltas/bodies identical, no added latency; 3.14 error paths_
    - _Requirements: 2.11, 2.12, 2.13, 3.1, 3.12, 3.14_

  - [ ] 15.2 Verify bug condition exploration tests now pass
    - **Property 5: Expected Behavior** - Expand/collect readiness and empty reasons
    - **IMPORTANT**: Re-run the SAME tests from task 5 - do NOT write new tests
    - **EXPECTED OUTCOME**: Tests PASS
    - _Requirements: 2.11, 2.12, 2.13_

  - [ ] 15.3 Verify preservation tests still pass
    - **Property 2: Preservation** - Non-buggy inputs behave as before
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - **EXPECTED OUTCOME**: Tests PASS

- [ ] 16. Fix OPEN-A: warm stage clock and measured thrash

  - [ ] 16.1 Implement the fix
    - `packages/pipeline/engine.py` / `warm_autoload.py`: add `_warm_stage(name)` → `[warm-stage] name=<n> t_ms=<since engine start> dt_ms=<since previous>`, once per stage per process, at engine HTTP up, soft binder ready, `[embed] plan`, embedder loaded, `prime_dense_ready`; `mcp_lifecycle`: AST hydrated / `pack_ready`
    - Log re-entries as `[warm-stage] rekick …` (`prewarm_embedder_async` while running, `load_engine`/FAISS opens during prewarm)
    - Fix only the thrash task 6 measured: expected gate on `register_client` → `ensure_embed_keepalive_loop` re-arms while `prewarm_busy_stamp_active` (same gate `/v1/client/touch` uses); newcomer walk during warm is already gated by 11.1 plus `in_prewarm()`
    - `runtime_controller`: `warm_wait` note "soft search only; dense loading — do not treat as ready" while `embedder_loaded` is false; `retry_after_s`/deadline from the unified reader. No field semantics change; dense is never skipped
    - _Bug_Condition: ColdStart where NOT perStageWallMsLogged(); StatusCall where softReady AND NOT denseReady AND agentSignalsReady_
    - _Expected_Behavior: stageLinesLogged == 6; NOT denseReady IMPLIES warm_wait.done == false (Property 6)_
    - _Preservation: 3.6 status shape/stage order; 3.16 dense + embedder load fully; 3.17 idle stop_
    - _Requirements: 2.14, 2.15, 3.6, 3.16, 3.17_

  - [ ] 16.2 Verify bug condition exploration tests now pass
    - **Property 6: Expected Behavior** - Warm and first-map time is attributed (Cases A, B)
    - **IMPORTANT**: Re-run the SAME tests from task 6 - do NOT write new tests
    - **EXPECTED OUTCOME**: Cases A, B PASS (Case C passes after task 17)
    - _Requirements: 2.14, 2.15_

  - [ ] 16.3 Verify preservation tests still pass
    - **Property 2: Preservation** - Non-buggy inputs behave as before
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - **EXPECTED OUTCOME**: Tests PASS

- [ ] 17. Fix OPEN-G: first-map timing attribution

  - [ ] 17.1 Implement the fix
    - `packages/pipeline/locate.py` `_search_hits`: time `tool_search_code` as `http_ms`; merge server-reported `server_ms` and `admit_ms` into `LAST_SEARCH_META["timings"]`
    - `packages/pipeline/server.py`: `/v1/search` payload gains `server_ms`, `admit_ms` (additive)
    - `packages/pipeline/mcp_locate.py` `map` tool body: `pre_ms` (prewarm join, locate-query record, session bind), `seed_ms` (suggested-seed / AST finalize), `post_ms`, `unattributed_ms`
    - Only if `admit_ms` dominates: reuse the 13.6 fast path for `/v1/search` when the runtime is active; `activate_repo` registry write at most once per `CTX_ADMIT_TOUCH_S` (default 30) per repo
    - _Bug_Condition: MapCall where attributedMs / elapsed_ms < 0.80_
    - _Expected_Behavior: sum(namedStages) >= 0.8 * elapsed_ms (Property 6)_
    - _Preservation: 3.13 ranking unchanged and not slower; 3.15 search contract (additive keys only)_
    - _Requirements: 2.16, 3.13, 3.15_

  - [ ] 17.2 Verify bug condition exploration test now passes
    - **Property 6: Expected Behavior** - Warm and first-map time is attributed (Case C)
    - **IMPORTANT**: Re-run the SAME tests from task 6 - do NOT write new tests
    - **EXPECTED OUTCOME**: All Property 6 tests PASS
    - _Requirements: 2.16_

  - [ ] 17.3 Verify preservation tests still pass
    - **Property 2: Preservation** - Non-buggy inputs behave as before
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - **EXPECTED OUTCOME**: Tests PASS

- [ ] 18. Checkpoint - signals and MCP surface on the live install
  - sync-uv-install.ps1 (PYTHONPATH cleared) + reload MCP + live battery after patches; unit tests alone are not green
  - AB-0, AB-1, AB-2, AB-4, AB-5, AB-6 (warm-stage lines + ensure→`embedder_loaded` wall ms; force one cold start via the normal idle stop or engine restart)
  - Pass criteria: AB-5 ladder succeeds with at most one bounded retry, `empty_reason="no_edges"` on config, `include_bodies` loc clamp + `full_loc` with text unchanged, first-map timings ≥80% attributed; 6 `[warm-stage]` lines; soft-only status shows `warm_wait.done=false`
  - Re-run AB-3 once to confirm no hot-lane regression from OPEN-A/G
  - Report timings and `ok` flags. Ask the user if questions arise
  - _Requirements: 2.11–2.16, 3.1, 3.5, 3.12, 3.13_

- [ ] 19. Fix OPEN-H/J: process tree hygiene and heavy-warm cap

  - [ ] 19.1 Implement the fix
    - `packages/pipeline/process_control.py`: `_frontend_parent_gone` and the `ppid` check in `reap_orphaned_mcp_processes` treat the parent as gone when dead OR `parent.create_time() > child.create_time()`; a locate is orphaned when its parent is not an `mcp_bridge` or known host-sim/probe harness
    - Reconcile: group `mcp_locate` by bridge parent, keep the newest; more than one engine → keep the `:8765` owner, `safe_terminate_pid` the rest; never the watchdog
    - `packages/pipeline/mcp_bridge.py`: on child respawn, terminate and wait for the previous `Popen` first (only if task 7 confirmed the gap)
    - `packages/pipeline/lifecycle_runtime.py`: `register_client` calls `sweep_orphan_scubiee_frontends(keep_pids={owner})` after `coalesce_mcp_clients`
    - `packages/pipeline/mcp_lifecycle.py`: machine-wide file lock `CTX_HOME/warm_heavy.lock` (N=`CTX_WARM_HEAVY_CONCURRENCY`, default 1) around `_kick_ast_bundle_hydrate` and `prewarm_pack_graph`; waiters are bounded by the pack AST wait and pack keeps `should_retry`
    - _Bug_Condition: ProcessEvent where chains > activeIdeSessions OR orphanLocateAlive OR duplicateEngine_
    - _Expected_Behavior: chains == activeIdeSessions AND NOT orphanLocate AND engines <= 1 (Property 7)_
    - _Preservation: 3.18 live IDE chains + watchdogs intact; 3.3 kill/recover + hold_bridge; 3.1 pack contract; 3.17 idle stop_
    - _Requirements: 2.17, 2.18, 3.1, 3.3, 3.17, 3.18_

  - [ ] 19.2 Verify bug condition exploration tests now pass
    - **Property 7: Expected Behavior** - One chain per IDE session
    - **IMPORTANT**: Re-run the SAME tests from task 7 - do NOT write new tests
    - **EXPECTED OUTCOME**: Tests PASS
    - _Requirements: 2.17, 2.18_

  - [ ] 19.3 Verify preservation tests still pass
    - **Property 2: Preservation** - Non-buggy inputs behave as before
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - **EXPECTED OUTCOME**: Tests PASS

  - [ ] 19.4 Measure on the live install
    - AB-0, then AB-4 followed by a normal IDE session; record the process tree (one bridge→locate→engine chain per IDE + watchdog) and peak Scubiee RSS during one cold warm (psutil sum over Scubiee processes) vs the 0.2 baseline
    - _Requirements: 2.17, 2.18_

- [ ] 20. Fix OPEN-I/K: HTTP pack decision, flaky tests (OPEN-L body cap deferred)

  - [ ] 20.1 OPEN-K: fix or quarantine the four tests
    - `tests/test_lifecycle_ownership.py::test_attach_mcp_session_is_nonblocking`: set `CTX_MCP_ATTACH_WARM=0`; add sibling assertion that the default `RuntimeController` branch returns `warm_started=True` without blocking
    - `tests/test_attach_warm_pipeline.py::test_start_attach_warm_pipeline_returns_immediately`: product fix in `packages/pipeline/runtime_controller.py` — `ensure(kind="attach")` returns a cached-state snapshot without `_probe_health`; the worker thread probes. Limit to the `"attach"` kind; `status` still probes (3.6)
    - `tests/test_live_reindexing.py::test_final_check_forces_held_publish`: mocked `_sync_paths` returns `chunks_upserted = loop.bulk_reindex_threshold + 1`; add counter-case that a small upsert is delivered immediately
    - `tests/test_watchdog.py::test_watchdog_child_stays_alive_then_exits_clean`: replace the fixed 8 s wait with poll-until-condition, budget `CTX_TEST_WATCHDOG_WAIT_S` (default 30)
    - Any test still not deterministic → `xfail`/skip with a recorded reason tied to a tracked item; never hide a real regression
    - _Requirements: 2.20, 3.6, 3.19_

  - [ ] 20.2 OPEN-I: document MCP-only; touch scripts only if one needs `/v1/pack`
    - Decision (user): document only. Pack is MCP-only; the MCP-only note itself is written in task 22
    - Only if the task 8 `scripts/` needle search found a script that needs `/v1/pack`: switch that script to the MCP stdio path (`mcp_host_sim/hosts/bridge_stdio.py::pack`) or `locate_cli`. Never add an HTTP route
    - If there were no hits, record "none" for task 22
    - _Requirements: 2.19, 3.15_

  - [ ]* 20.3 OPEN-L (DEFERRED, optional, not queued): class body cap
    - Deferred by the user. Do not run unless the user re-queues OPEN-L
    - `packages/pipeline/mcp_response_lean.py` (or pack body collection in `context_trace`): with `CTX_MCP_PACK_CLASS_BODY_MAX_LINES=N` set and node kind `class`, truncate `text` to N lines and add `text_truncated: true` (keep `full_loc`); unset = unchanged
    - _Bug_Condition: PackBodies where seedKind == "class" AND capEnv IS SET AND textNotCapped_
    - _Expected_Behavior: capSet IMPLIES lines(text) <= cap (Property 9)_
    - _Preservation: 3.5 loc clamp + full_loc; text byte-identical when unset_
    - _Requirements: 2.21, 3.5_

  - [ ] 20.4 Verify Property 8 now holds
    - **Property 8: Expected Behavior** - Tests and HTTP pack decision
    - **IMPORTANT**: Re-run the SAME four tests from task 8 (watchdog 5×) and the same `/v1/pack` needle search - do NOT write new tests
    - **EXPECTED OUTCOME**: four tests pass deterministically (or carry a recorded quarantine reason); no script POSTs `/v1/pack`. The doc decision is written in task 22
    - _Requirements: 2.19, 2.20_

  - [ ]* 20.5 Verify Property 9 now holds (OPEN-L DEFERRED; optional, only if 20.3 was done)
    - **Property 9: Expected Behavior** - Optional class body cap
    - **IMPORTANT**: Re-run the SAME test from task 9 - do NOT write a new test
    - **EXPECTED OUTCOME**: Test PASSES
    - _Requirements: 2.21_

  - [ ] 20.6 Verify preservation tests still pass
    - **Property 2: Preservation** - Non-buggy inputs behave as before
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - **EXPECTED OUTCOME**: Tests PASS

- [ ] 21. Checkpoint - full acceptance battery, host-sim last
  - sync-uv-install.ps1 (PYTHONPATH cleared) + reload MCP + live battery after patches; unit tests alone are not green
  - Run the full unit suite: `python -m pytest -p no:logfire -q -p no:cacheprovider tests` → all Property 1–8 tests pass (Property 9 is skipped while OPEN-L is deferred), the Property 2 suite passes, and the task 2 passing set still passes
  - AB-0 → AB-1 → AB-2 → AB-3 (5 trials at `CTX_PROBE_SLA_S=8 CTX_PROBE_TRIALS=5` + idle single round) → AB-4 → AB-5 → AB-6 → AB-7 LAST, then reload Scubiee MCP
  - Report measured timings and `ok` flags for every step next to the 0.2 baseline. Unit tests alone do not count as done. Ask the user if questions arise
  - _Requirements: 2.1–2.21, 3.1–3.19_

- [ ] 22. Fill the fix log and record the OPEN-I decision
  - `docs/beta-open-issues-kiro-fix-2026-09-26.md` → Fix log table: for each of OPEN-A…L fill Change (files + one line), Proof (test names + battery step with measured numbers from task 21 and baseline from 0.2), Status (`fixed` / `partial` / `quarantined` / `deferred`; OPEN-L = `deferred`). Also record the task 0.1 MCP entry rewrite (backup path, changed shared values). Document irreducible hot-sync cases, the floor RAM recommendation (OPEN-J) and "host-sim kills IDE MCP bridges; reload MCP afterwards" (OPEN-H)
  - `docs/production-ready-0.3.131.md`: record "pack is MCP-only; HTTP `/v1/pack` is intentionally absent" plus the script changes (or "none") from 20.2
  - No commits
  - _Requirements: 2.10, 2.17, 2.18, 2.19_

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["0.1"] },
    { "id": 1, "tasks": ["0.2"] },
    { "id": 2, "tasks": ["1", "2", "3", "4", "5", "6", "7", "8", "9"] },
    { "id": 3, "tasks": ["10.1"] },
    { "id": 4, "tasks": ["10.2"] },
    { "id": 5, "tasks": ["10.3"] },
    { "id": 6, "tasks": ["10.4"] },
    { "id": 7, "tasks": ["11.1"] },
    { "id": 8, "tasks": ["11.2"] },
    { "id": 9, "tasks": ["11.3"] },
    { "id": 10, "tasks": ["12"] },
    { "id": 11, "tasks": ["13.1"] },
    { "id": 12, "tasks": ["13.2"] },
    { "id": 13, "tasks": ["13.3"] },
    { "id": 14, "tasks": ["13.4"] },
    { "id": 15, "tasks": ["13.5"] },
    { "id": 16, "tasks": ["13.6"] },
    { "id": 17, "tasks": ["13.7"] },
    { "id": 18, "tasks": ["13.8"] },
    { "id": 19, "tasks": ["14"] },
    { "id": 20, "tasks": ["15.1"] },
    { "id": 21, "tasks": ["15.2"] },
    { "id": 22, "tasks": ["15.3"] },
    { "id": 23, "tasks": ["16.1"] },
    { "id": 24, "tasks": ["16.2"] },
    { "id": 25, "tasks": ["16.3"] },
    { "id": 26, "tasks": ["17.1"] },
    { "id": 27, "tasks": ["17.2"] },
    { "id": 28, "tasks": ["17.3"] },
    { "id": 29, "tasks": ["18"] },
    { "id": 30, "tasks": ["19.1"] },
    { "id": 31, "tasks": ["19.2"] },
    { "id": 32, "tasks": ["19.3"] },
    { "id": 33, "tasks": ["19.4"] },
    { "id": 34, "tasks": ["20.1"] },
    { "id": 35, "tasks": ["20.2"] },
    { "id": 36, "tasks": ["20.3"] },
    { "id": 37, "tasks": ["20.4"] },
    { "id": 38, "tasks": ["20.5"] },
    { "id": 39, "tasks": ["20.6"] },
    { "id": 40, "tasks": ["21"] },
    { "id": 41, "tasks": ["22"] }
  ]
}
```

Dependency edges encoded by the waves:
- 0 (0.1 → 0.2) runs before everything else.
- 1–8 depend on 0 and can run in parallel with each other; 9 is optional (OPEN-L deferred) and sits in the same wave.
- 10 depends on 1, 2. 11 depends on 2, 3, 10. 12 depends on 10, 11.
- 13 depends on 4, 12. 14 depends on 13.
- 15 depends on 5, 14. 16 depends on 6, 15. 17 depends on 6, 16. 18 depends on 15, 16, 17.
- 19 depends on 7, 18. 20 depends on 8, 19 (20.3 and 20.5 are optional; 20.5 also needs 9 and 20.3). 21 depends on 20. 22 depends on 21.
- Fix tasks (10–22) and their sub-tasks stay strictly sequential: they touch overlapping files (`sync_loop.py`, `mcp_locate.py`) and share the live engine.
- Live battery steps (AB-0…AB-7, and the live "to verify" measurements inside tasks 0.2, 3, 4, 6, 7) never run concurrently with each other, even inside the parallel wave 2. Only the offline unit/property test parts of tasks 1–8 run in parallel.

## Notes

- OPEN-L (optional class body cap) is deferred by the user: tasks 9, 20.3 and 20.5 stay optional (`[ ]*`) and are not queued. Property 9 is skipped in task 21; the fix log marks OPEN-L `deferred`.
- Property-based tests use a seeded `random.Random(<fixed seed>)` generator fed through `pytest.mark.parametrize` instead of Hypothesis. Print the seed and case id on failure. Do not install Hypothesis.
- Task 0.1 (rewriting the `scubiee` entry in `.kiro/settings/mcp.json`) is approved by the user. Back up to `.kiro/settings/mcp.json.bak-open-b` first.
- In the 0.1 rewrite, shared env keys take the Cursor value: `CTX_MCP_BRIDGE_MODE` auto→shared, `CTX_ENGINE_IDLE_S` 25→10, `CTX_ENGINE_TRANSITION_DEBOUNCE_S` 25→5. `CTX_MCP_CLIENT` stays `kiro`. Record these changes in the fix log (task 22).
- No commits.
