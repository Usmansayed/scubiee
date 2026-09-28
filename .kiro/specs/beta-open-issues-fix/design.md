# Beta Open Issues (OPEN-A…L) Bugfix Design

## Overview

Scubiee 0.3.131 has twelve open closed-beta issues (see `bugfix.md`). This design lists, for each one, the code that causes it, how sure we are of that cause, the smallest fix, the files it touches, and the preservation clauses (3.x) the fix must not break. All code locations below came from the Scubiee MCP ladder (map → pack_context → expand_context / collect_hot_context) in this repo.

Strategy, in the suggested order B → D → C → E/F → A → G → H/J → I/K (OPEN-L deferred):

- **Fix signals first.** OPEN-B (deadline label), OPEN-F (empty delta reason), OPEN-G (first-map attribution) and OPEN-A (warm stage timing) change what agents see, not how retrieval ranks results.
- **Then fix queue and ordering on the hot lane.** OPEN-D and OPEN-C are mostly ordering bugs: in-flight hot entries get reset, deletions take the full-publish path, the hot vector-collection cache is dropped, and reconcile jobs run for paths that are already gone. They are not throughput limits.
- **Then fix hygiene.** OPEN-H, J, I and K. OPEN-L is deferred.

No ranking change, no dense skip, no new HTTP surface (OPEN-I is a doc decision). Every behavior change is either a bug fix under the bug condition or sits behind an existing or new env kill switch.

### Evidence gathered while writing this design (live Kiro session, uv-tool 0.3.131)

| Observation | Source |
| --- | --- |
| `status.warm_deadline_ms=30000`, with `runtime_state=READY` and `warm_elapsed_ms=208227.8` | `mcp_scubiee_status(detail=full)` |
| `c:\Users\usman\Downloads\context-engine\.kiro\settings\mcp.json` has **no** `CTX_WARM_DEADLINE_MS`. Its env keys: `CTX_ENGINE_URL…CTX_MCP_CLIENT`, 17 total. Its `command` points at `.venv-cli-test\Scripts\scubiee-mcp-bridge.EXE`, **not** the uv-tool install | PowerShell `ConvertFrom-Json` of the file |
| `map` elapsed 18168 / 17458 / 10409 ms, while `embed_ms + retrieve_ms` < 1 s. Not only the first call: this happened while the keeper was `syncing` with many `graph_catchup` entries for `sync_live_*` paths | map responses + status `keeper.dirty` |
| `expand_context(node=warm_contract.py::ast_hydrated, direction=callers)` returns `ok=true, delta=[], count=0` with no reason, although `warm_status_fields` calls it | expand_context response |
| `test_start_attach_warm_pipeline_returns_immediately`: 1.70 s > 0.5 s. `test_attach_mcp_session_is_nonblocking`: `warm_calls == []`. `test_final_check_forces_held_publish`: `publish_delivered False`. The watchdog test passed on this run (flaky) | `python -m pytest -p no:logfire …` (conda base needs `-p no:logfire` because the logfire plugin is broken) |

## Glossary

- **Bug_Condition (C)**: an input or event, from one of the twelve OPEN-* families, that currently produces the defective behavior in `bugfix.md` 1.x.
- **Property (P)**: the expected behavior for C, from `bugfix.md` 2.x.
- **Preservation**: the behaviors in `bugfix.md` 3.x that must be identical before and after the fix.
- **F / F'**: the original (0.3.131 workspace `packages/`) code and the fixed code.
- **Keeper**: `BackgroundSyncLoop._run` thread (`ctx-keeper`) in `packages/pipeline/sync_loop.py`. It runs `poll_repo_changes` → newcomer kick → `keeper_tick` → `drain_due` → `drain_publish`.
- **Hot reason**: a `DirtyLedger` reason in `HOT_SYNC_REASONS` (`packages/pipeline/dirty_ledger.py`), e.g. `probe_write` or `write`. It selects the short debounce, the hot batch, and the append-only patch publish.
- **Hot patch**: `RuntimeManager._hot_publish_runtime` → `WarmSearchEngine.apply_chunk_delta` (`ce_service.py`, `engine.py`). It appends only. It declines, and full reload follows, when `base_chunk_count != len(self.chunks)` ("binder drift").
- **Hot vdb cache**: `BackgroundSyncLoop._hot_vdb_cache` / `_hot_vdb()`. It reuses the `VectorDatabase` across hot syncs, guarded by `_vdb_fingerprint`.
- **AST hydrate**: the in-process AST bundle load in `mcp_locate` (`context_trace.hydrate_ast_bundle`, flag `warm_contract.ast_hydrated()`). Pack waits for it up to `CTX_MCP_PACK_AST_WAIT_S` (default 10 s).
- **Warm deadline readers**: `warm_contract.warm_deadline_ms()` (default `DEFAULT_WARM_DEADLINE_MS = 30_000`) and `runtime_controller.warm_deadline_ms()` (hard-coded `"30000"`).

## Bug Details

### Bug Condition

The defect covers twelve independent families. One discriminated input type covers them all:

**Formal Specification:**
```
TYPE Event =
    StatusCall{env}                          -- OPEN-B / A (1.1, 1.2, 1.15)
  | NewcomerTick{now, ledger, keeperBusy}    -- OPEN-D (1.3, 1.4)
  | SyncEvent{batch, ledger, binder, disk}   -- OPEN-C (1.5–1.10)
  | DirtyPost{keeperBusy}                    -- OPEN-C (1.9)
  | ExpandCall{node, direction, astReady}    -- OPEN-E / F (1.11–1.13)
  | CollectCall{ids, astReady}               -- OPEN-E (1.11)
  | ColdStart{}                              -- OPEN-A (1.14)
  | MapCall{firstAfterAttach, keeperBusy}    -- OPEN-G (1.16)
  | ProcessEvent{tree}                       -- OPEN-H / J (1.17, 1.18)
  | HttpPack{}                               -- OPEN-I (1.19)
  | TestRun{name}                            -- OPEN-K (1.20)
  | PackBodies{seedKind, capEnv}             -- OPEN-L (1.21)

FUNCTION isBugCondition(e)
  INPUT: e of type Event
  OUTPUT: boolean
  CASE e OF
    StatusCall:    RETURN effectiveDeadline(e.env) != 30000
                          AND reported.warm_deadline_ms == 30000
                   OR  (softReady AND NOT denseReady AND agentSignalsReady(status))
    NewcomerTick:  RETURN scanRaisesTypeError()                       -- missing now=
                          OR (scanFixed AND scanMutatesInFlightEntry(e.ledger))
                          OR (scanFixed AND scanHoldsKeeperDuringHotSave())
    SyncEvent:     RETURN (e.batch.isDeletionOnly AND publishKind == "full")
                          OR (prevWriterNonHot AND nextHotSave.vec_open_ms > 3000)
                          OR (e.binder.count != e.disk.chunkCount AND hotPatchAttempted)
                          OR (e.batch.allPathsGoneAndUnindexed AND jobRunsOnKeeper)
    DirtyPost:     RETURN e.keeperBusy AND dirtyLatencyMs > 500
    ExpandCall:    RETURN (NOT e.astReady AND returnsImmediately)
                          OR (resultDelta == [] AND "empty_reason" NOT IN response)
    CollectCall:   RETURN NOT e.astReady AND returnsImmediately
    ColdStart:     RETURN NOT perStageWallMsLogged()
    MapCall:       RETURN attributedMs(timings) / elapsed_ms < 0.80
    ProcessEvent:  RETURN count(bridge→locate→engine chains) > activeIdeSessions
                          OR orphanLocateAlive() OR duplicateEngine()
    HttpPack:      RETURN scriptsDependOnHttpPack() OR NOT documentedMcpOnly()
    TestRun:       RETURN e.name IN FOUR_TESTS AND (fails OR flakes) AND NOT quarantinedWithReason
    PackBodies:    RETURN e.seedKind == "class" AND e.capEnv IS SET AND textNotCapped
  END CASE
END FUNCTION
```

### Examples

- **OPEN-B**: The MCP env for Cursor pins `CTX_WARM_DEADLINE_MS=90000` (`mcp_install.server_entry`). The Kiro workspace entry does not. Live Kiro `status` → `warm_deadline_ms: 30000`, from `ReadySnapshot.as_status_fields` → `runtime_controller.warm_deadline_ms()`. Expected: 90000.
- **OPEN-D**: Every ~30 s, `_run` → `_start_newcomer_scan(now=now)`. The scan thread calls `self._enqueue_newcomers()` without `now`, so it raises `TypeError` and logs `[keeper] newcomer scan failed: … missing 1 required keyword-only argument: 'now'`. Expected: the scan runs and logs nothing.
- **OPEN-C**: `live_sync_probe._cleanup_trial` does `rmtree` and then `/v1/dirty` `probe_write` for `f1.py` and `__init__.py`. These are missing hot-reason paths, so `_split_explicit_writes` backlogs them and the batch becomes deletion-only. `_is_hot_batch` is true, but the delta is not `append_only`, so the batch takes a full publish (6–8 s). The next save then pays `vec_open` ≈3870 ms. Expected: cleanup never forces the next save through a full reload plus a 3 s+ open.
- **OPEN-F**: `expand_context(ast_hydrated, callers)` → `delta=[]` with no `empty_reason`. Expected: `empty_reason:"no_edges"` (or `"already_expanded"` if prior filtering emptied it).
- **OPEN-G**: map `elapsed_ms=18167.8`, `embed_ms=253.6`, `retrieve_ms=109.5` → 2% attributed. Expected: ≥80% attributed.
- **OPEN-K**: `start_attach_warm_pipeline` took 1.70 s in a unit test because `RuntimeController.ensure` → `snapshot` → `_probe_health` does a synchronous HTTP probe to the live `:8765`.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors (bugfix.md 3.1–3.19):**
- Attach→pack race (`attach_pack_race.py`): the first pack is `ok` with `n_heat>0`. Pack keeps its hydrate wait and its `ast_warming`/`should_retry`/`retry_after_s`/`ast_wait_ms` contract (3.1).
- Host-sim `ok=true` including `pack_first` (3.2). Kill/recover with `hold_bridge` and prewarm grace (3.3). Install sync `differ:0 missing:0`, gate `index_skip`/`index_write_hint` (3.4).
- `loc` clamp plus `full_loc` for lean and `include_bodies` packs. Body text stays unless the OPEN-L cap is set (3.5).
- `status` keeps `pack_ready`, `ast_hydrated`, the `warm_wait` fields and the stage sequence `engine_down → soft_loading → dense_loading → pack_ast_loading → ready` (3.6).
- An idle single new-file save still reaches dense map in ≈4.5 s via the append-only patch (3.7). Deletions and modifications are reflected with no stale hits. Vector flush happens before any full reload, and missing vectors are re-embedded after a crash (3.8). `CTX_HOT_PUBLISH=0` and the other kill switches still fall back to full publish (3.9).
- The newcomer scan still finds new files, skips junk, and honors `.scubieeignore`/builtins (3.10). Graph catch-up still runs outside the quiet window and clears `graph_pending` (3.11).
- Hydrated expand/collect return identical deltas and bodies with no added latency (3.12). Map/pack ranking is unchanged and no slower (3.13). Error paths stay the same (3.14). HTTP `/health`, `/v1/dirty` and search keep their contracts. Pack stays MCP-only (3.15).
- Dense and the embedder still load fully (3.16). Idle stop via `CTX_ENGINE_IDLE_S` stays (3.17). Live IDE chains and watchdogs are never killed (3.18). Currently passing tests keep passing (3.19).

**Scope:**
Any event where `isBugCondition` is false must behave exactly as in F. In particular:
- Hot saves of existing or new files on an idle keeper.
- Map and pack on a warm, hydrated session.
- Expand and collect on a hydrated AST that return non-empty deltas.
- Status on a process whose env already carries the deadline and whose engine is dense-ready.
- Lifecycle for a single healthy IDE chain.

## Hypothesized Root Cause

Status legend: **Confirmed** means verified in code or by a live run this session. **To verify** means plausible from the code and must be proven by the exploratory test before patching.

1. **OPEN-B: two deadline readers with a 30 s default, and a host entry without the pin.** Confirmed.
   - `runtime_controller.warm_deadline_ms()` (L30–35) hard-codes `"30000"`. `warm_contract.warm_deadline_ms()` (L40–45) defaults to `DEFAULT_WARM_DEADLINE_MS = 30_000`. Both read `os.environ` of the calling process.
   - Status comes from `ReadySnapshot.as_status_fields` (`runtime_state` is present in the live output), so it uses the runtime_controller reader. `RuntimeController._remaining_s`, `_attach_worker`, `mcp_lifecycle._attach_warm_coordinator` (health deadline), `prewarm_locate_worker` and `start_attach_warm_pipeline` call one reader or the other.
   - The Kiro workspace `mcp.json` was written by a different writer: it has `CTX_MCP_CLIENT`, fewer keys, and a `.venv-cli-test` command. So the locate worker never sees `CTX_WARM_DEADLINE_MS`, and the 30 s default wins. The install pin (`mcp_install.server_entry`: `CTX_WARM_DEADLINE_MS=90000`) only helps hosts written by `merge_mcp_json`/`write_kiro_mcp`.
   - Side effect (feeds OPEN-A): `_attach_warm_coordinator` gives up on `/health` after 30 s instead of 90 s, then falls into its 120 s quiet loop.

2. **OPEN-D: missing `now=` plus unsafe re-marking.** Both parts confirmed.
   - `_start_newcomer_scan._scan` calls `self._enqueue_newcomers()`, but the signature is `_enqueue_newcomers(self, *, now: float)`.
   - The trap behind the earlier 0/5 is `_enqueue_newcomers`. It marks every `probe.added` path with `reason="disk_poll"` and does **not** filter in-flight ledger states. `poll_repo_changes` does filter `{"queued","due","processing","overlay_ready"}`. `DirtyLedger.mark` replaces any entry whose state is not `"queued"` with a fresh `DirtyEntry(reason="disk_poll", state="queued", due_at=now+1s)`.
   - A probe file is "added" to the Merkle until its sync commits. While its hot entry is `due`/`processing`, the scan resets it to a non-hot, 1 s-debounced queued entry. The file then syncs a second time on the slow path. The hot reason is lost, `_is_hot_batch` goes false, the full publish runs, and `_hot_vdb_cache` is dropped.
   - To verify: GIL contention from the ~7.5 s pure-Python walk (`collect_index_relpaths`) as a second, smaller factor.

3. **OPEN-C: deletions ride the hot lane into a full publish; non-hot writers drop the hot vdb cache; reconciles run for paths that are gone; `/v1/dirty` pays per-request admission.**
   - (a) Confirmed. `_split_explicit_writes` counts a hot reason as a "write" only if the file exists. `_additions_before_deletions` orders missing paths last. A cleanup-only batch is therefore deletion-only and still hot (`_is_hot_batch`). `incremental_sync` produces a non-`append_only` delta, so `_hot_publish_runtime` returns `None` and the full publish runs (6–8 s `publish_call_ms`).
   - (b) Confirmed. `_sync_paths(hot=False)` sets `self._hot_vdb_cache = None` unconditionally. Every graph catch-up, disk-poll backlog or retry forces the next hot save to open a fresh `VectorDatabase` and re-read `faiss.index` (≈3.9 s here).
   - (c) To verify. Binder drift (`live chunks N != delta base M`) happens when `chunks.jsonl` on disk and the live binder diverge. Candidates: a non-hot sync commits removals to disk while its publish failed (`publish_failed` → `dense_pending`) or was held (`_publish_or_hold` / `_pending_publish`); or a zero-chunk-delta reconcile rewrites `chunks.jsonl` without a publish (the `else: complete(published=True)` branch in `drain_due`). The next hot delta then computes `base_chunk_count` from disk.
   - (d) Confirmed from status. `drain_due` re-queues `graph_pending` as `graph_catchup` for trial paths that the cleanup deletes a few seconds later. After the quiet window those jobs run `incremental_sync` on the keeper for paths that are gone and unindexed. That is the whole-graph merge ("`[sync] no chunk delta … ms=10–12s`"), and any save marked during it waits.
   - (e) To verify. `/v1/dirty` is in `operational`, so `do_POST` → `admit(root, intentional=True)` → `RuntimeManager.admit_request` → `repo_lifecycle.activate_repo` → `_update(...)`. That is a registry write per request, plus `_project` / `git_common_dir` resolution and `_activate_runtime`. Under keeper and GIL load this costs seconds, though `mark_dirty` itself only takes a ledger lock.

4. **OPEN-E: the wait exists only in pack.** Confirmed from the docs and the tool surface. The bounded wait lives inline in the `pack_context` tool body inside `mcp_locate.create_mcp`. The `expand_context` / `collect_hot_context` bodies call `run_expand_context` / `run_collect_hot` directly and return `ast_warming` without waiting.

5. **OPEN-F: `run_expand_context` never records why the delta is empty.** Confirmed.
   - `context_trace.run_expand_context` (L3282–3529) returns `ok=True, delta=[]` after `struct + tracer + lexical`, the `prior` filter and `rank_expand_delta`. It does not record which of these emptied it.
   - Unresolved nodes return `{"ok": False, "error": "unknown node …"}` with no machine-readable reason.
   - The AST-not-ready state is only known at the MCP layer.

6. **OPEN-A: no stage clock, and a soft-ready flip that looks like ready.**
   - Confirmed. `RuntimeController.snapshot` sets `state=READY` and calls `mark_warm_ready()` on soft alone. That freezes `warm_elapsed_ms` and gives `warm_ready=true`, `runtime_state=READY`, `warm_phase=ready` while dense may still be loading. Only `warm_wait` distinguishes the two.
   - To verify, as the source of the multi-minute gap after `[embed] plan`: re-plan or FAISS re-open from `prewarm_embedder_async` being re-kicked by `/v1/client/touch` and `register_client` → `ensure_embed_keepalive_loop` storms; several locate workers (Cursor, Kiro and Copilot are all connected) each running AST hydrate in their own `_attach_warm_coordinator`; and the keeper / newcomer walk competing.

7. **OPEN-G: timings cover only the engine search internals.** Partly confirmed. `locate._search_hits` copies `out["timings"]` (`embed_ms`, `retrieve_ms`) from `tool_search_code`. The HTTP round trip is not timed. Neither is server-side admission (`admit_request` → `activate_repo`, as in 3e), MCP pre-work (`join_locate_worker_prewarm`, `_record_locate_query`, session bind), or the suggested-seed / AST finalize. This session shows 10–18 s maps under keeper load, not only on the first call.

8. **OPEN-H: coalescing is bookkeeping only, and the orphan test trusts a live PID.**
   - Confirmed. `lifecycle_runtime.coalesce_mcp_clients` only pops entries from `active_clients.json` and never ends a process.
   - To verify. `process_control.reap_orphaned_mcp_processes` and `sweep_orphan_scubiee_frontends` treat a locate or bridge as alive when `_pid_alive(ppid)` is true. On Windows PIDs get reused, so a dead IDE's PID can belong to another process. A bridge that respawned its child without ending the old one leaves two locate children under a live parent. Duplicate engines are only killed by an explicit `stop_engine_worker_processes`.

9. **OPEN-J: uncapped concurrent heavy warm.** To verify. Each connected host runs its own locate worker, and each hydrates the AST in-process (`_attach_warm_coordinator` uses a `ThreadPoolExecutor(max_workers=2)` for embed plus AST). The engine can be re-kicked (item 6). Duplicate processes from item 8 add to it.

10. **OPEN-I: no route, no doc.** Confirmed. `server.Handler.do_POST` has no `/v1/pack` and falls through to `404 {"error": "not found"}`. No script hitting `/v1/pack` surfaced in `map`; a literal check runs at implementation time.

11. **OPEN-K: stale tests and a probing `ensure`.**
    - `test_attach_mcp_session_is_nonblocking`: confirmed stale. `attach_mcp_session` now takes the `RuntimeController` branch because `attach_warm_enabled()` defaults on, so `warm_engine_for_mcp` is never called. The test does not set `CTX_MCP_ATTACH_WARM=0`.
    - `test_start_attach_warm_pipeline_returns_immediately`: confirmed as a real latency. `RuntimeController.ensure("attach")` → `snapshot()` → `_probe_health()` does a synchronous HTTP probe (1.7 s against the live engine).
    - `test_final_check_forces_held_publish`: confirmed stale. `_publish_or_hold` holds only when `chunks_upserted > bulk_reindex_threshold` (a deliberate hot-lane change), and the test upserts 1.
    - `test_watchdog_child_stays_alive_then_exits_clean`: timing flake, 8 s wait. Passed this run.

12. **OPEN-L: by design.** Bodies are collected untruncated for class seeds. `_slim_pack_item` / `_slim_loc_item` in `mcp_response_lean.py` clamp only `loc`.

## Correctness Properties

Property 1: Bug Condition - Warm deadline is one effective value (OPEN-B)

_For any_ process env E (with or without `CTX_WARM_DEADLINE_MS`), every deadline surface SHALL equal the same `effective_warm_deadline_ms(E)`. The surfaces are `status.warm_deadline_ms`, `warm_status_fields`, `as_status_fields`, `start_attach_warm_pipeline.deadline_ms`, `_remaining_s`/`warm_remaining_s` and the attach health deadline. That value SHALL be `int(E["CTX_WARM_DEADLINE_MS"])` (floor 1000) when set, and the shipped default (90000, the same as the install pin) otherwise.

**Validates: Requirements 2.1, 2.2, 2.15**

Property 2: Preservation - Non-buggy inputs behave as before

_For any_ event where isBugCondition is false (idle hot saves, warm map/pack, hydrated non-empty expand/collect, single-chain lifecycle, status on dense-ready engines, error paths), the fixed code SHALL produce the same observable result as the original. That covers ranking, deltas, bodies, `loc`/`full_loc`, the status and `warm_wait` fields and stage order, HTTP endpoint contracts, kill-switch fallbacks, durability ordering, idle stop, and the currently passing tests. Latency SHALL be within noise.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14, 3.15, 3.16, 3.17, 3.18, 3.19**

Property 3: Bug Condition - Newcomer scan runs and never disturbs in-flight entries (OPEN-D)

_For any_ ledger state L and newcomer result set N, a newcomer tick SHALL complete without an exception. It SHALL mark only paths in N whose ledger state is absent or in {`published`, `overlay_ready`-free terminal states}; it never touches `queued`, `due`, `processing` or `overlay_ready`. It SHALL NOT change the reason or `due_at` of any hot-reason entry. It SHALL NOT start while a hot entry is queued, due or processing, or within `CTX_NEWCOMER_QUIET_S` of the last hot mark. It SHALL run at most once per `CTX_NEWCOMER_SCAN_S`. It SHALL respect `filter_dirty_paths`.

**Validates: Requirements 2.3, 2.4**

Property 4: Bug Condition - Hot lane under add/delete churn (OPEN-C)

_For any_ dirty sequence that mixes hot saves with deletion-only batches and graph catch-ups for deleted paths, the following SHALL hold:
- (a) A deletion-only batch SHALL NOT run a full publish inside the hot window. Deleted paths SHALL be excluded from search results as soon as the deletion is observed.
- (b) A non-hot keeper sync SHALL leave the hot vdb cache valid, or refresh it, so the next hot save's `vec_open_ms` stays below the cold-open cost.
- (c) At each hot patch, `base_chunk_count` SHALL equal the live binder count. Otherwise the pending publish SHALL be delivered first.
- (d) A batch whose paths are all missing on disk and absent from the store SHALL complete without calling `incremental_sync`.
- (e) A non-hot batch SHALL be deferred while a hot entry is queued or due.
- (f) `/v1/dirty` for an active keeper repo SHALL return without per-request admission.

**Validates: Requirements 2.5, 2.6, 2.7, 2.8, 2.9, 2.10**

Property 5: Bug Condition - Expand/collect readiness and empty reasons (OPEN-E, OPEN-F)

_For any_ `expand_context` or `collect_hot_context` call, the tool SHALL first run the same bounded hydrate wait as pack (`CTX_MCP_PACK_AST_WAIT_S`) through one shared helper. If the AST is still not ready, it SHALL return `ok=false, error="ast_warming", empty_reason="ast_not_ready", should_retry=true, retry_after_s, ast_wait_ms`. For any `expand_context` result with an empty delta, the response SHALL carry `empty_reason` ∈ {`no_edges`, `already_expanded`, `node_unresolved`, `ast_not_ready`}. `direction=config` on a node with no config edges SHALL yield `no_edges`.

**Validates: Requirements 2.11, 2.12, 2.13**

Property 6: Bug Condition - Warm and first-map time is attributed (OPEN-A, OPEN-G)

_For any_ cold start, the engine log SHALL contain one `[warm-stage]` line per stage (engine_up, soft, embed_plan, embed_load, dense_ready, pack_ready), each with a monotonic wall-ms offset. `warm_wait.done` SHALL be false while `dense_ready` is false. _For any_ `map` call, the named timing stages SHALL sum to at least 80% of `elapsed_ms`.

**Validates: Requirements 2.14, 2.15, 2.16**

Property 7: Bug Condition - One chain per IDE session (OPEN-H, OPEN-J)

_For any_ process table after bridge start or a watchdog reconcile, the following SHALL hold:
- Every `mcp_locate` has a live `mcp_bridge` parent created before it, and every bridge has a live parent created before it. Anything else is terminated.
- Each bridge has at most one `mcp_locate` child: the newest one is kept.
- At most one engine exists: the `:8765` owner.
- At most `CTX_WARM_HEAVY_CONCURRENCY` (default 1) locate workers run AST hydrate at once, machine-wide.
- The watchdog and every live IDE chain are never terminated.

**Validates: Requirements 2.17, 2.18**

Property 8: Bug Condition - Tests and HTTP pack decision (OPEN-I, OPEN-K)

_For any_ run of the test suite, each of the four named tests SHALL pass deterministically, or carry a documented `xfail`/skip reason tied to a tracked item. No script in `scripts/` SHALL POST `/v1/pack`. The MCP-only decision SHALL be recorded in `docs/production-ready-0.3.131.md`.

**Validates: Requirements 2.19, 2.20**

Property 9: Bug Condition - Optional class body cap (OPEN-L)

_For any_ `pack_context(include_bodies=1)` whose collected body comes from a class node, the returned text SHALL satisfy two cases. With `CTX_MCP_PACK_CLASS_BODY_MAX_LINES=N` set, it SHALL be at most N lines and carry `text_truncated=true` and `full_loc`. With the env unset, it SHALL be byte-identical to F.

**Validates: Requirements 2.21, 3.5**

```
FUNCTION expectedBehavior(e, result)
  CASE e OF
    StatusCall:   RETURN ALL deadline fields == effective_warm_deadline_ms(e.env)
                         AND (NOT denseReady IMPLIES result.warm_wait.done == false
                              AND result.warm_wait.stage IN {"soft_loading","dense_loading"})
    NewcomerTick: RETURN noException AND inFlightEntriesUnchanged AND respectsThrottleAndQuiet
    SyncEvent:    RETURN (deletionOnly IMPLIES publishKind != "full" within hot window
                                         AND deletedPathsMasked)
                         AND nextHotSave.vec_open_ms < 1000
                         AND NOT bindersDrifted
                         AND (goneAndUnindexed IMPLIES noIncrementalSync)
    DirtyPost:    RETURN latencyMs <= 200                -- 200 ms: loopback plus ledger lock
    ExpandCall:   RETURN (NOT astReadyAfterWait IMPLIES ok=false AND should_retry AND empty_reason="ast_not_ready")
                         AND (delta == [] IMPLIES empty_reason IN REASONS)
    CollectCall:  RETURN NOT astReadyAfterWait IMPLIES ok=false AND should_retry
    ColdStart:    RETURN stageLinesLogged == 6
    MapCall:      RETURN sum(namedStages) >= 0.8 * elapsed_ms
    ProcessEvent: RETURN chains == activeIdeSessions AND NOT orphanLocate AND engines <= 1
    TestRun:      RETURN pass OR quarantinedWithReason
    PackBodies:   RETURN capSet IMPLIES lines(text) <= cap
  END CASE
END FUNCTION
```

## Fix Implementation

### Changes Required

Assuming the root cause analysis is correct (the "to verify" items are gated by the exploratory tests below):

**OPEN-B: `packages/pipeline/warm_contract.py`, `packages/pipeline/runtime_controller.py`, `packages/pipeline/mcp_lifecycle.py` (call sites only)**

1. **One reader.** Keep `warm_contract.warm_deadline_ms()` as the only reader. Change `DEFAULT_WARM_DEADLINE_MS` to `90_000` so hosts without the pin report the same value as the install pin.
2. **Delegate.** Replace the body of `runtime_controller.warm_deadline_ms()` with `from pipeline.warm_contract import warm_deadline_ms as _w; return _w()`. Keep the name so the existing importers in `mcp_lifecycle` keep working.
3. **Source field.** Add `warm_deadline_source: "env" | "default"` next to `warm_deadline_ms` in `as_status_fields` and `warm_status_fields`. This is an additive field; 3.6 keeps all existing keys.
4. **Refresh stale host entries (no code change).** Re-run `scubiee` install / `write_kiro_mcp` so the workspace `.kiro/settings/mcp.json` gets the full `server_entry` env and the uv-tool command. Flag to the user: the Kiro entry currently points at `.venv-cli-test`, so the acceptance battery would otherwise not exercise the uv-tool build.

Preserves 3.6: only the value changes, plus one new key.

**OPEN-D: `packages/pipeline/sync_loop.py`**

1. `_start_newcomer_scan._scan`: call `self._enqueue_newcomers(now=time.monotonic())`. Use a fresh clock value; the caller's `now` may be stale by the time the thread runs.
2. `_enqueue_newcomers`: apply the same in-flight filter as `poll_repo_changes` before marking. Skip paths whose ledger state is in `{"queued","due","processing","overlay_ready"}`, and skip any entry whose reason is hot.
3. Gate in `_run`: skip the kick while `_hot_work_pending(now)` is true (a hot-reason entry is queued, due or processing, or `now - _last_hot_mark_at < CTX_NEWCOMER_QUIET_S`, default 10 s) or `self._syncing` is true.
4. Make the 30 s interval `CTX_NEWCOMER_SCAN_S` (default 60).
5. The walk stays on its own thread and keeps `root_probe(discover_newcomers=True)`, which already applies junk and ignore filtering. Optional, if GIL contention is measured: yield with `time.sleep(0)` every N entries. That lives in `root_probe`/`collect_index_relpaths` only if the exploratory timing shows the walk still stretches hot saves.

Preserves 3.10: the filter only drops paths already in flight, so they are not lost.

**OPEN-C: `packages/pipeline/sync_loop.py`, `packages/pipeline/engine.py`, `packages/pipeline/ce_service.py`, `packages/pipeline/server.py`**

1. **Deletion-only batches inside the hot window: mask now, publish later.**
   - In `drain_due`, when every path in the Tier-1 batch is missing on disk, and a hot entry was marked within `graph_catchup_quiet_s` or is pending, call a new `RuntimeManager.mask_deleted_paths(paths)`. It uses the `on_refresh` side channel, the same object path as `_hot_publish_runtime`. It stores the paths in `WarmSearchEngine._masked_files`, a set.
   - Search result assembly drops hits whose file is in that set. The hook sits in the `WarmSearchEngine` search result path; its exact site gets pinned during implementation.
   - Then `dirty_ledger.defer(batch, now=quiet_until)` with a non-hot reason (`deletion_catchup`). Disk and binder stay in step, so no drift.
   - When the quiet window passes, the batch runs non-hot → full publish → a new engine object, and the mask is cleared.
   - Outside the hot window the behavior is unchanged. Kill switch: `CTX_HOT_DELETE_MASK=0`.
2. **Keep the hot vdb cache across keeper-owned non-hot syncs.**
   - In `_sync_paths(hot=False)`, when `self._hot_vdb()` returns a valid cached `VectorDatabase`, pass it to `incremental_sync(..., vdb=vdb)` instead of dropping it. Afterwards set `self._hot_vdb_cache = (vdb, _vdb_fingerprint(vdb))`: the keeper is the writer, so memory is coherent.
   - Drop the cache only when the vdb was not passed, or the sync raised.
   - The fingerprint guard still protects against writers outside the keeper (full index, compaction, CLI). If `incremental_sync` non-hot rejects an external `vdb`, which the exploratory test checks, fall back to the current drop plus a post-sync background reopen that runs only when no hot entry is due.
3. **Binder drift.**
   - Before a hot publish, if `self._pending_publish is not None`, or the last non-hot payload ended `dense_pending`/`publish_failed`, call `drain_publish(force=True)` first, so the full publish lands before the append.
   - Log `base_chunk_count`, the live count and the last writer on decline. The log is to confirm the hypothesis; the change is the ordering itself.
4. **Gone paths.** In `drain_due`, before Tier-1, split out paths that are missing on disk **and** have `counts.get(path, 0) == 0` in `_estimate_dirty_chunks` (exposed as a returned set) and whose reason is `graph_catchup`, `disk_poll` or `retry`. Complete them `published=True` with no `incremental_sync`. In `_hold_graph_catchups`, drop `graph_catchup` entries whose path no longer exists.
5. **Hot-first deferral.** After `_split_explicit_writes`, if `writes` is empty but a hot-reason entry exists in state `queued` (not yet due), defer the non-hot `paths` by `hot_debounce_ms + 250 ms`. This extends the existing "saves ahead of any backlog" rule to saves marked a few ms after the backlog became due.
6. **`/v1/dirty` fast path.** In `server.Handler.do_POST`, for `path in {"/v1/dirty", "/v1/note_locate"}`, when `ce.sync_loop` is running and `Path(root).resolve() == ce.sync_loop.repo`, skip `admit()` and call `ce.mark_dirty` directly. Response shape is unchanged (3.15). All other routes keep admission.

Preserves 3.7: an idle single save still goes hot patch → deferred flush. 3.8: deletions are masked immediately and published in the quiet window; flush-before-reload stays in `_run_vector_flush`/publisher. 3.9: kill switches are checked first. 3.11: catch-ups still run after the quiet window, and only gone paths are skipped.

**OPEN-E/F: `packages/pipeline/mcp_locate.py`, `packages/pipeline/context_trace.py`**

1. **Shared helper.** Extract the inline hydrate wait from the `pack_context` tool body in `create_mcp` into a module-level `_await_ast_ready(tool: str, repo: Path) -> dict | None`. It returns `None` when ready, or the exact `ast_warming` error payload pack returns today (`should_retry=true`, `retry_after_s`, `ast_wait_ms`) with `empty_reason:"ast_not_ready"` added. Pack calls it with identical behavior (3.1).
2. **Callers.** The `expand_context` and `collect_hot_context` tool bodies call `_await_ast_ready` first. When the AST is already hydrated the helper is a flag check, so there is no added latency (3.12).
3. **`empty_reason` in `run_expand_context`.**
   - If `nid` does not resolve and there is no disk delta: `{"ok": False, "error": …, "empty_reason": "node_unresolved"}`. Keep `error` for 3.14.
   - Otherwise, when `delta == []`: `"already_expanded"` if the candidates before the prior filter were non-empty, else `"no_edges"`.
   - Add `"empty_reason": None` only when the delta is empty; non-empty responses are unchanged.
4. Make sure the lean response filter (`mcp_response_lean`) does not strip `empty_reason`.

**OPEN-A: `packages/pipeline/engine.py`, `packages/pipeline/warm_autoload.py`, `packages/pipeline/runtime_controller.py`**

1. **Stage log.** Add `_warm_stage(name)`, which prints `[warm-stage] name=<n> t_ms=<since engine start> dt_ms=<since previous>` once per stage per process. Call it at engine HTTP up, soft binder ready, `[embed] plan`, embedder loaded (`prewarm_embedder` end), `prime_dense_ready`, and (MCP side, `mcp_lifecycle`) AST hydrated / pack_ready.
2. **Re-kick guard.** Also count re-entries: `prewarm_embedder_async` calls while `running`, and `load_engine` / FAISS opens during prewarm. Log them as `[warm-stage] rekick …` so thrash shows up in `engine.log`.
3. **Fix the thrash the log proves.**
   - Expected candidate: `/v1/client/touch` and `register_client` re-arming `ensure_embed_keepalive_loop` → `prewarm_embedder_async` while `prewarm_busy_stamp_active`. Gate that the same way `/v1/client/touch` already does.
   - Also expected: the newcomer walk during warm, gated by OPEN-D's quiet and throttle rules plus `in_prewarm()`.
4. **Honesty.** No field semantics change (3.6). `warm_wait` already reports `dense_loading`. Make sure its `retry_after_s`/deadline use the unified reader (OPEN-B), and set the note to "soft search only; dense loading — do not treat as ready" while `embedder_loaded` is false.

**OPEN-G: `packages/pipeline/locate.py`, `packages/pipeline/mcp_locate.py`, `packages/pipeline/server.py`**

1. `_search_hits`: time the `tool_search_code` call as `http_ms`. Merge the server-reported `server_ms` and `admit_ms` into `LAST_SEARCH_META["timings"]`. `do_POST` adds them to the `/v1/search` payload; the field is additive.
2. `map` tool body: add `pre_ms` (prewarm join, locate-query record, session bind), `seed_ms` (suggested-seed / AST finalize) and `post_ms`. Report `unattributed_ms = elapsed_ms - sum(...)`.
3. If `admit_ms` dominates, reuse the OPEN-C fast path for `/v1/search` when the runtime is already active (`hub.get(pid)` has a live engine). The `activate_repo` registry write becomes at most once per `CTX_ADMIT_TOUCH_S` (default 30 s) per repo. This removes waste without changing ranking (3.13).

**OPEN-H/J: `packages/pipeline/process_control.py`, `packages/pipeline/lifecycle_runtime.py`, `packages/pipeline/mcp_bridge.py`, `packages/pipeline/mcp_lifecycle.py`**

1. **Parent identity.** `_frontend_parent_gone` and the `ppid` check in `reap_orphaned_mcp_processes` treat the parent as gone when it is dead **or** `parent.create_time() > child.create_time()` (PID reuse). A locate worker is orphaned when its parent is not an `mcp_bridge` or a known host-sim/probe harness.
2. **One locate per bridge.** In the reconcile, group `mcp_locate` processes by bridge parent and terminate all but the newest. In `mcp_bridge`, when respawning the child, terminate and wait for the previous `Popen` before spawning (to verify in the respawn path).
3. **Single engine.** On watchdog reconcile, if more than one `pipeline.engine` / `engine run` process exists, keep the one that owns `:8765` (existing health/port owner lookup) and `safe_terminate_pid` the rest. Never touch the watchdog (3.18).
4. **Coalesce plus reap.** `coalesce_mcp_clients` keeps its bookkeeping; `register_client` then calls the existing `sweep_orphan_scubiee_frontends(keep_pids={owner})`. It kills processes only when they are provably orphaned, never just for sharing a host with another chain (3.18).
5. **Heavy-warm cap (OPEN-J).** Add a machine-wide file lock in `CTX_HOME` (`warm_heavy.lock`, N=`CTX_WARM_HEAVY_CONCURRENCY`, default 1) around `_kick_ast_bundle_hydrate` and `prewarm_pack_graph`. A worker that fails to get the lock waits, bounded by the pack AST wait, and pack keeps its `should_retry` contract. The engine embedder is already single-flight via `_PREWARM_LOCK`.
6. **Measure.** Peak RSS before and after, using psutil sums over Scubiee processes during cold warm, with a script snippet in the battery.
7. **Docs.** Host-sim kills IDE bridges, so reload MCP afterwards. Add a floor RAM recommendation for the beta notes.

**OPEN-I: docs and scripts only**

1. Record in `docs/production-ready-0.3.131.md` and the handoff fix log: "pack is MCP-only; HTTP `/v1/pack` is intentionally absent."
2. At implementation time, check `scripts/` for literal `/v1/pack` with the needle search the handoff allows. Switch any hit to the MCP stdio path (`mcp_host_sim/hosts/bridge_stdio.py::pack`) or `locate_cli`.

**OPEN-K: tests plus one product line**

1. `test_attach_mcp_session_is_nonblocking`: set `CTX_MCP_ATTACH_WARM=0` so it exercises the legacy AUTO_WARM branch it was written for. Add a sibling assertion that the default `RuntimeController` branch returns `warm_started=True` without blocking.
2. `test_start_attach_warm_pipeline_returns_immediately`: product fix. `RuntimeController.ensure(kind="attach")` returns a snapshot built from cached state without `_probe_health`; the worker thread does the probe. If that changes other `ensure` callers, limit it to the `"attach"` kind. Status still probes (3.6).
3. `test_final_check_forces_held_publish`: update the mocked `_sync_paths` to return `chunks_upserted = loop.bulk_reindex_threshold + 1`, which the hold rule now requires. Add the counter-case: a small upsert is delivered immediately, which locks in the hot-lane behavior.
4. `test_watchdog_child_stays_alive_then_exits_clean`: replace the fixed 8 s wait with a poll-until-condition loop. The budget is `CTX_TEST_WATCHDOG_WAIT_S`, default 30 s. It exits as soon as the condition holds.

**OPEN-L: `packages/pipeline/mcp_response_lean.py` or the pack body collection in `context_trace`** (DEFERRED by the user; kept here for when it is re-queued)

1. New env `CTX_MCP_PACK_CLASS_BODY_MAX_LINES` (unset = off). When set and the body's node kind is `class`, truncate `text` to N lines and add `text_truncated: true` (plus the existing `full_loc`). No change when unset (3.5).

## Testing Strategy

### Validation Approach

Two phases. First, run exploratory tests on the **unfixed** code to confirm or refute each "to verify" hypothesis; a refuted hypothesis sends that item back to root-cause analysis before any patch. Then patch one issue at a time in the suggested order, run the unit tests, sync the install, reload MCP, and run the acceptance battery. Unit tests alone never count as done.

Test runner on this host: `python -m pytest -p no:logfire -q -p no:cacheprovider …`. The conda base `logfire` pytest plugin fails to import.

### Exploratory Bug Condition Checking

**Goal**: surface counterexamples on unfixed code and confirm the root causes.

**Test Plan**: small unit tests with fakes, plus log-level instrumentation (temporary, or behind `CTX_DEBUG_SYNC=1`) during one `live_sync_probe.py` run.

**Test Cases**:
1. **Deadline readers** (fails on unfixed code): with `CTX_WARM_DEADLINE_MS` unset, `runtime_controller.warm_deadline_ms()` gives 30000 while the install pin is 90000. With env=90000, `as_status_fields()["warm_deadline_ms"] == 90000`. This confirms the missing-pin path is what the live 30000 comes from.
2. **Newcomer signature** (fails): `_start_newcomer_scan(now=…)`, then join the thread; stderr contains `newcomer scan failed`.
3. **Newcomer resets in-flight hot entry** (fails once the signature is fixed): mark `a.py` `probe_write`, `begin(["a.py"])` → `processing`, run `_enqueue_newcomers(now)` with `root_probe` monkeypatched to report `a.py` as added. Assert the entry is still `processing`/`probe_write`. Unfixed: it becomes `queued`/`disk_poll`.
4. **Deletion-only hot batch → full publish** (fails): a ledger with two missing `probe_write` paths goes through `drain_due` with a fake `_sync_paths` returning `chunks_removed=2` and `hot_delta=None`. Assert `_notify_refresh` is invoked with a full publish inside the hot window.
5. **Non-hot sync drops the vdb cache** (fails): seed `_hot_vdb_cache` with a fake vdb and matching fingerprint, run `_sync_paths(hot=False)` with `incremental_sync` monkeypatched, and assert the cache is `None`.
6. **Gone graph_catchup runs incremental_sync** (fails): a `graph_catchup` entry for a missing and unindexed path is processed after the quiet window, and `incremental_sync` is called.
7. **`/v1/dirty` admission cost** (to measure): time `admit_request` against the live engine while the keeper is idle and while a full publish runs. Log `admit_ms`.
8. **Binder drift source** (to measure): during a 5-trial probe, log `(base_chunk_count, len(chunks), last_writer, pending_publish)` at every decline.
9. **Expand empty/ast** (fails): `run_expand_context` on a node with no config edges, `direction=config`, has no `empty_reason`. The MCP `expand_context` with `ast_hydrated()` false returns right away (elapsed < 50 ms).
10. **Map attribution** (fails): a map with a monkeypatched slow `admit_request` (2 s) reports timings that sum to under 20% of elapsed.
11. **Orphan PID reuse** (fails): a fake process table where a locate's `ppid` is alive but was created after the locate; `reap_orphaned_mcp_processes` skips it.

**Expected Counterexamples**:
- In-flight hot entries downgraded to `disk_poll`. Deletion-only batches publishing `full`. `_hot_vdb_cache is None` after every non-hot sync. `incremental_sync` running for gone paths. Expand returning `ok=true, delta=[]` with no reason.
- Possible alternative causes, if a test refutes: GIL contention (D); an external writer of the collection (C-b); asynchronous full publish (C-c); a server thread pool that is saturated rather than admission cost (C-e / G).

### Fix Checking

**Goal**: for every input where the bug condition holds, the fixed code satisfies `expectedBehavior`.

**Pseudocode:**
```
FOR ALL e WHERE isBugCondition(e) DO
  result := F'(e)
  ASSERT expectedBehavior(e, result)
END FOR
```

### Preservation Checking

**Goal**: for every input where the bug condition does not hold, F and F' agree.

**Pseudocode:**
```
FOR ALL e WHERE NOT isBugCondition(e) DO
  ASSERT F(e) = F'(e)
END FOR
```

**Testing Approach**: property-based testing with seeded generators (a fixed-seed `random.Random` building cases fed through `pytest.mark.parametrize`, seed and case id printed on failure; Hypothesis is not used or installed) on the pure pieces:
- the ledger and `drain_due` scheduling,
- `run_expand_context` non-empty deltas,
- deadline resolution,
- orphan classification over generated process tables,
- the body cap with the env unset (OPEN-L is deferred; this case only guards 3.5).

It generates many ledger interleavings and process tables that hand-written cases would miss.

**Test Plan**: first record F's behavior on non-bug inputs (golden outputs on unfixed code), then assert F' matches.

**Test Cases**:
1. **Idle hot save**: a single existing-file `probe_write` with an idle ledger → `publish=patch`, same stage sequence, and `_hot_vdb_cache` reused (3.7).
2. **Kill switches**: `CTX_HOT_PUBLISH=0`, `CTX_HOT_VDB_CACHE=0` and `CTX_HOT_DELETE_MASK=0` → identical to F (3.9).
3. **Hydrated expand/collect**: the same deltas and bodies as F for callers/effects on fixed nodes (`test_expand_after_pack`, `test_pack_expand_parallel`, `test_expand_caller_ranking`). `empty_reason` is absent when the delta is non-empty (3.12).
4. **Pack contract**: `_await_ast_ready` produces a byte-identical `ast_warming` payload apart from the added `empty_reason` (3.1).
5. **Status shape**: the key set is a superset of F's and the stage order is the same (3.6).
6. **Live chain safety**: a generated table with a live IDE → bridge → locate chain plus watchdog → no kills (3.18).

### Unit Tests

- `warm_contract` / `runtime_controller`: env set or unset, invalid, below 1000. All surfaces are equal. `warm_deadline_source` is correct.
- `sync_loop`: the newcomer signature, in-flight filter, throttle and quiet gate; the deletion mask plus deferral; vdb cache retention; skipping gone paths; hot-first deferral; forced `drain_publish` before a hot patch.
- `engine.WarmSearchEngine`: masked files excluded from results; the mask cleared on a new binder; `apply_chunk_delta` unchanged.
- `server`: `/v1/dirty` fast path responds with the same shape, and falls back to `admit` when the keeper is absent or the repo differs.
- `context_trace.run_expand_context`: each `empty_reason` value; the `mcp_locate` helper for pack, expand and collect.
- `process_control`: PID-reuse orphan, duplicate locate per bridge, duplicate engine, watchdog untouched.
- The four OPEN-K tests, as rewritten above.
- `mcp_response_lean`: the class body cap on and off (deferred with OPEN-L).

### Property-Based Tests

All generators below are seeded `random` + `pytest.mark.parametrize` (no Hypothesis), with the same invariants.

- Random interleavings of `mark(hot|disk_poll|graph_catchup)`, `begin`, `complete`, the newcomer tick and `drain_due` over a small path set. Invariants: a hot entry is never downgraded or delayed past `hot_debounce_ms` by a non-hot producer; every path eventually reaches `published`; deleted paths are never returned by the fake search.
- Random env strings for `CTX_WARM_DEADLINE_MS` → one value across all surfaces.
- Random process tables (pids, ppids, create_times, cmdlines) → kills exactly the provably orphaned or duplicate set and never the live chain or the watchdog.
- Random expand inputs over a fixture graph → `delta==[]` ⇔ `empty_reason` present; for non-empty deltas the output equals F's.

### Integration Tests (acceptance battery, from the handoff doc; host-sim last)

Run from the repo root in PowerShell, with `PYTHONPATH` cleared so the uv-tool build runs:

```powershell
# 0) Refresh host entries and sync the install (Kiro workspace mcp.json currently lacks the pin
#    and points at .venv-cli-test)
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
powershell -File scripts/sync-uv-install.ps1        # expect differ: 0 missing: 0, ignore.py present
# Reload Scubiee MCP in Kiro/Cursor

# 1) gate + status (MCP): index_skip + index_write_hint; pack_ready=true, ast_hydrated=true,
#    warm_wait.done=true, warm_deadline_ms == CTX_WARM_DEADLINE_MS (90000), warm_deadline_source

# 2) Attach pack race
python scripts/attach_pack_race.py --sessions 2 --packs 3        # ok=true, first pack n_heat>0

# 3) Hot sync at the owner bar
$env:CTX_PROBE_SLA_S='8'; $env:CTX_PROBE_TRIALS='5'
python scripts/live_sync_probe.py                                  # >=4/5 within 8 s; none routinely >10 s
# plus one idle single-round (~4.5 s, publish=patch)
# engine.log: no binder-drift storm; cleanup does not force full reload + vec_open>3 s on the next save;
#             no "[sync] no chunk delta ... ms=10" for gone probe paths; /v1/dirty latency logged <200 ms

# 4) Kill/recover
python scripts/engine_kill_recover_probe.py --hold-bridge --budget-s 120   # ok=true

# 5) Live MCP ladder (after reload)
# map -> pack_context lean -> expand_context callers -> collect_hot_context   (no ast_warming thrash;
#   at most one bounded retry on a fresh attach)
# expand_context direction=config on a node with no config edges -> empty_reason="no_edges"
# pack include_bodies=1 on BackgroundSyncLoop -> loc clamped + full_loc, text unchanged (cap unset)
# first map after attach -> timings sum >= 80% of elapsed_ms

# 6) Newcomer / warm stages
Select-String "$env:USERPROFILE\.scubiee\engine.log" -Pattern "newcomer scan failed"   # none repeating
Select-String "$env:USERPROFILE\.scubiee\engine.log" -Pattern "\[warm-stage\]"         # 6 stages on cold start
# record ensure -> embedder_loaded wall ms; peak Scubiee RSS before/after (OPEN-J); process tree = one
# bridge->locate->engine chain per IDE + watchdog (OPEN-H)

# 7) Host-sim LAST (kills IDE MCP bridges; reload MCP afterwards)
python scripts/mcp_host_sim.py --lane a --live --skip-idle --settle-s 35   # ok=true incl. pack_first
```

Report the measured timings and `ok` flags for each step in the handoff fix log. Document any irreducible hot-sync cases (for example a ≥300-chunk deletion outside the hot window) there too.
