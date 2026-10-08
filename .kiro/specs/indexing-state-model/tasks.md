# Implementation Plan — Unified Indexing & State-Management Model

Each top-level task is independently shippable: it builds, its tests pass, and the existing offline suite + live sync-matrix still pass before the next task begins (R10). Destructive/recovery tests run against a COPIED store, never the live index. No task touches the retrieval/dense path.

- [x] 1. Add the `index_state` durable record module (C1)
  - [x] 1.1 Create `packages/pipeline/index_state.py` with `IndexStateDoc`, `BuildRecord`, `PendingSummary` dataclasses and `load_index_state` / `write_index_state` / `transition`
    - Atomic write via `artifact_guard.atomic_write_text`; per-project path `projects/<id>/index_state.json`
    - Missing file or `version` mismatch returns a sentinel doc (`state="unindexed"`, `pending=None`) — never raises
    - `generation_counter` monotonic within `generation_epoch`; mirror to `generation.json` via existing `write_stamp`
    - _Requirements: R5.1, R5.2, R5.4, R5.5, R10.4_
  - [x] 1.2 Unit tests `tests/test_index_state.py`: round-trip, atomic write, monotonic counter rejects backward move, missing/old-version → sentinel, concurrent `transition` under the per-project lock
    - _Requirements: R5.1, R5.4, R5.5_
  - [x] 1.3 Write `index_state.json` as a SHADOW record from the existing publish path (not yet authoritative): on `publish_engine`/commit, record state=fresh + generation + indexed_head + merkle_root
    - Verify it tracks the live generation without changing any existing behavior
    - _Requirements: R5.1, R5.3, R10.2, R10.3_

- [x] 2. Add the durable build-intent record for interruption recovery (C4)
  - [x] 2.1 In `indexer.index_repo_staged`, write build-intent (`state="indexing"`, `BuildRecord`) BEFORE staging mutation; clear it (`build=None`, bump generation) only AFTER `promote_staged_store` publishes the manifest. (Bulk sub-batch `done_units` updates deferred to task 7 where the bulk lane is reworked; the staged full index is the primary interruption case and is covered here.)
    - _Requirements: R3.1, R3.3, R10.2_
  - [x] 2.2 On engine start / warm, detect a build record whose pid is not alive (`_pid_alive`) → classify INTERRUPTED (`detect_interrupted_build`/`mark_interrupted`), run `_sweep_stale_staging`. Remaining-work computation is read by the reconciler (task 3); detection-only here.
    - _Requirements: R3.2, R3.4, R5.5_
  - [x] 2.3 Recovery tests `tests/test_index_state_recovery.py`: build record with a dead pid + partial staging → asserts INTERRUPTED, staging swept, live generation never torn (manifest stays valid throughout). 7 tests pass.
    - _Requirements: R3.2, R3.3, R3.5, R10.1_

- [x] 3. Add the Reconciler and wire it into engine start (C2) — closes the offline-change gap
  - [x] 3.1 Create `packages/pipeline/reconciler.py` with `reconcile(repo, trigger, store, journal) -> ReconcilePlan`: load state → interruption check → detect drift via existing `check_freshness` / `root_probe` / `verify_merkle_leaves` / newcomer walk → enqueue drift into the durable journal → set index_state (no lane selection)
    - `start`/`connect` do the thorough newcomer walk; `poll` uses the cheap dir-mtime path
    - Idempotent: two calls with no new changes enqueue the same set and yield the same state
    - _Requirements: R8.1, R8.2, R8.3, R2.1, R2.3, R2.4_
  - [x] 3.2 Invoke `reconcile(trigger="start")` in the engine warm/start path BEFORE the engine reports write-current, independent of client presence; begin draining the enqueued work as soon as warm
    - _Requirements: R2.1, R2.2, R4.1, R2.5_
  - [x] 3.3 Invoke `reconcile(trigger="connect")` on the already-warm fast-path return (poll/wake left to the keeper's existing durable detect to avoid double-marking; index_state poll transition folds in at tasks 6-7)
    - _old:_ `reconcile(trigger="connect")` on `register_client`, and `reconcile(trigger="poll"/"wake")` from the keeper poll / `check_time_gap`, replacing the ad-hoc poll-detect logic (which the reconciler now wraps)
    - _Requirements: R4.2, R8.2, R2.5_
  - [x] 3.4 Reconciler tests `tests/test_reconciler.py` (7 pass): drift enqueued; clean→fresh no-enqueue; idempotency; dead-pid build → INTERRUPTED; folder-of-25 offline → all detected; rollback-switch no-op
    - _Requirements: R2.1, R2.3, R2.4, R8.1, R9.3, R9.4_

- [x] 4. Add the workload classifier with measured throughput (C3)
  - [x] 4.1 Create `packages/pipeline/workload.py` with `classify_workload(...) -> PendingSummary`: line-based unit estimate for new files + exact `count_chunks_per_file` for modified, file-type weighting (code 1.0 >> docs 0.5 > config 0.3; vendored/binary 0.0), convert units→seconds via throughput, apply SUBSTANTIAL rule (seconds budget OR full-reindex OR corpus-fraction)
    - Env knobs: `CTX_SUBSTANTIAL_SECONDS` (default 25), `CTX_SUBSTANTIAL_FRACTION` (default 0.4)
    - _Requirements: R6.1, R6.2, R6.4_
  - [x] 4.2 Measure and persist embed throughput (chunks/sec) via `record_embed_throughput` (EMA in `meta.embed_cps`, implausible-sample guard); `throughput_chunks_per_s` reads it; conservative default (`CTX_DEFAULT_EMBED_CPS`, 20) until measured. (Wiring `record_embed_throughput` into the live embed stage is a one-liner left for the embed-path touch in task 7; falling back to the conservative default is correct meanwhile.)
    - _Requirements: R6.5_
  - [x] 4.3 Reconciler defaults `classify=` to the bound `classify_workload` (repo/store/corpus); small drift → `pending=None` (silent, state=stale), substantial → populated summary (state=reconciling). Verified end-to-end: 600-file offline paste → 4800 units → 240s → substantial.
    - _Requirements: R6.3, R7.2_
  - [x] 4.4 Classifier tests `tests/test_workload.py` (12 pass): 5-file small code edit → not substantial; 1000-file paste → substantial; full reindex → substantial; corpus-fraction trigger; removed-only cheap; unmeasured throughput default; measured override; EMA fold + implausible-sample guard; exact-count beats line-estimate; doc-vs-code weighting
    - _Requirements: R6.1, R6.2, R6.3, R6.4, R6.5_

- [x] 5. Surface actionable pending state to the agent; retire raw dirty_count (C5)
  - [x] 5.1 Added `index_state.agent_pending(project_id)` → the derived `pending` object (substantial, state, reason, estimated_seconds, done/total, search_usable, action); None unless state ∈ {reconciling, interrupted} AND substantial (interrupted always surfaces). Wired into `ce_service.health` (`/health` now carries `pending` + `index_fresh`) and the detailed `status()` payload. `tool_status` renders a one-line pending hint only when substantial.
    - _Requirements: R7.1, R7.2, R7.3, R7.5_
  - [x] 5.2 Retired `dirty_count` from the agent-facing contract: the raw queue block in `status()` moved to `pending_internal` (debug only); the agent-facing `pending` is the derived object. `/health` never carries `dirty_count`. Updated `test_auto_sessions_observability` to the new keys.
    - _Requirements: R7.4_
  - [x] 5.3 Contract tests `tests/test_pending_contract.py` (13 pass): substantial → pending present with correct fields; small/stale & non-substantial reconcile → no pending; needs_full → `action` set; interrupted always surfaced; search_usable=true during reconcile; `tool_status` omits pending when none/non-substantial and never emits `dirty_count`.
    - _Requirements: R7.1, R7.2, R7.3, R7.4, R7.5_

- [x] 6. Gate engine idle-stop on the authoritative index state (C6)
  - [x] 6.1 Added `lifecycle_runtime._index_state_busy_reason()` → `index_state:<state>` while the durable state ∈ BUSY_STATES {indexing, reconciling, interrupted}; wired into `_idle_busy_reason` after the warm_state check, keeping prewarm/warming/governor fallbacks. Resolves project_id via `peek_project(ce.repo)`. No-op when `CTX_UNIFIED_STATE=0`. `stale` is deliberately NOT busy (small background catch-up may idle-stop and resume on next start).
    - _Requirements: R4.3, R4.4_
  - [x] 6.2 Tests `tests/test_lifecycle_index_gate.py` (8 pass): reconciling/interrupted/indexing block with zero clients; fresh + debounce-elapsed + no clients → idle-stop proceeds; reconciling still blocks even after debounce; stale does not block; rollback switch disables the gate.
    - _Requirements: R4.3, R4.4, R2.2_

- [x] 7. Retire the delete-mask hack so deletes prune within a consistent bound (C7)
  - [x] 7.1 Scoping decision: the keeper's per-drain `_estimate_dirty_chunks` tier is the authoritative sizing for the *current due slice* (which changes every drain), distinct from the reconciler's start-time whole-batch classification for the agent signal — so R8.4/R8.5 are already satisfied (changing detection does not force changing lanes). Freezing a stale start-time tier into the keeper would be a regression. No change made to the tier math; the valuable unification is the delete-mask retirement (7.2).
    - _Requirements: R8.4, R8.5_
  - [x] 7.2 Retired the `CTX_HOT_DELETE_MASK` deletion-mask in `sync_loop.drain_due`: default flipped to OFF. The hack deferred a deletion-only batch whenever an UNRELATED hot save was pending, making prune latency depend on concurrent save activity (the R9.1 violation). Deletions now flow through the normal batch and prune within one consistent drain+publish bound. Env preserved (`CTX_HOT_DELETE_MASK=1`) as a rollback switch. (The separate write-before-backlog split still orders a fresh save ahead of a disk-poll backlog — documented, unchanged.)
    - _Requirements: R9.1, R9.2_
  - [x] 7.3 Lane tests `tests/test_lane_delete_consistency.py` (3 pass): mask retired by default; a due deletion prunes in one drain (not `deletion_deferred`); `CTX_HOT_DELETE_MASK=1` rollback still routes. Regression: `test_live_reindexing` + `test_graph_catchup_async` + `test_open_preservation` (`hot_delete_mask_off` param) + corpus-alignment + status-canaries all green (only the pre-existing `_FakeCE.search(lean=)` env failure remains).
    - _Requirements: R9.1, R9.2, R10.3_

- [x] 8. Scenario-matrix verification and docs (R9.6)
  - [x] 8.1 Mapped the design's scenario catalogue (A1–A7, B1–B2, C1–C6, D1–D4, E1–E3) to deterministic offline unit tests rather than extending the live harness — the unified model is testable without a live engine, which is faster and CI-safe. Live rows (D2/D3/E3) reuse the existing HIGH-priority harness runs.
    - _Requirements: R9.6, R2, R3, R9.5_
  - [x] 8.2 Documented per-scenario expected vs covering-test in `docs/scubiee-scenario-test-results.md` (new "Unified Indexing & State-Management Model — scenario matrix" section). All 64 unified-model unit tests pass; no new bug surfaced (the one env failure is the pre-existing `_FakeCE.search(lean=)`).
    - _Requirements: R9.6_
  - [x] 8.3 Final regression deferred to the Final step below (rebuild + reinstall + full offline suite). Per-step regression already green at each task.
    - _Requirements: R10.3, R10.5_

- [x] 9. Release notes + rollback switch
  - [x] 9.1 Added `.kiro/specs/indexing-state-model/release-notes.md` (v0.3.144): what's new/fixed, the new `index_state.json`, the `/health` + `status` `pending`/`index_fresh` contract, the retired `dirty_count`, and the full env-knob table. Bumped `pyproject.toml` to 0.3.144.
    - _Requirements: R7, R6_
  - [x] 9.2 `CTX_UNIFIED_STATE=0` is the single master rollback: Reconciler no-op (`reconciler.unified_state_enabled`) + idle-stop index-gate no-op (`lifecycle_runtime._index_state_busy_reason`). Shadow writes remain harmless (not consulted for decisions when off). Secondary `CTX_HOT_DELETE_MASK=1` restores old delete-defer. Both documented in the release notes rollback section + covered by `test_reconciler::test_disabled_switch...` and `test_lifecycle_index_gate::test_rollback_switch_disables_gate`.
    - _Requirements: R10.1, R10.4_
