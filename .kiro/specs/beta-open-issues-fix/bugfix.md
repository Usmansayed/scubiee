# Bugfix Requirements Document

## Introduction

Scubiee 0.3.131 (uv-tool install plus workspace `packages/`, Windows, Cursor/Kiro MCP, engine on `:8765`) still has twelve open closed-beta issues, OPEN-A through OPEN-L, listed in `docs/beta-open-issues-kiro-fix-2026-09-26.md`. They cause misleading warm signals (agents trust a 30 s deadline while dense warm takes 60–170 s), a broken newcomer scan, hot-sync misses under add/delete churn, ambiguous or non-waiting expand/collect responses, opaque first-map timings, duplicate process trees, RAM pressure during warm, an undocumented missing HTTP pack route, and four failing or flaky tests. OPEN-L (full class text with `include_bodies`) is optional and deferred.

Fix order: OPEN-B → OPEN-D → OPEN-C → OPEN-E/F → OPEN-A → OPEN-G → OPEN-H/J → OPEN-I/K.

Definition of done: the acceptance battery in the handoff doc, run against the synced uv-tool install (`scripts/sync-uv-install.ps1` with `PYTHONPATH` cleared, then an MCP reload), with measured timings and `ok` flags recorded. Unit tests alone are not green.

## Bug Analysis

### Current Behavior (Defect)

**OPEN-B: warm deadline label**

1.1 WHEN the MCP/engine env sets `CTX_WARM_DEADLINE_MS=90000` (or a host entry omits it) THEN the system reports `status.warm_deadline_ms: 30000`, even while `warm_elapsed_ms` is 55 000–200 000+
1.2 WHEN the warm deadline is read by status versus by attach/prewarm THEN the system uses two separate deadline readers with different defaults, so surfaces can disagree for the same process env

**OPEN-D: newcomer scan**

1.3 WHEN the keeper kicks the newcomer scan (about every 30 s) THEN the scan fails with `newcomer scan failed … missing 1 required keyword-only argument: 'now'` and logs it every time
1.4 WHEN only the missing `now=` is supplied (the naive fix) THEN the system starves hot sync, which drops to 0/5 at the 8 s SLA with 18–40 s saves

**OPEN-C: hot sync under add/delete churn**

1.5 WHEN a trial cleanup deletes files and marks them dirty (a deletion-only batch) THEN the system forces a full publish (`publish_call_ms` 6–8 s, `total_ms` 10–13 s)
1.6 WHEN a save follows a deletion batch or full publish THEN the system pays `vec_open` of about 3870 ms (`write_ms` about 4.7 s)
1.7 WHEN the live binder and the delta base diverge THEN the system logs `hot patch declined (binder drift: live chunks N != delta base M)` and falls back to a full reload
1.8 WHEN reconcile runs for probe paths with no chunk delta THEN the system runs `[sync] no chunk delta … ms=10–12s` jobs on the keeper, and saves marked meanwhile wait
1.9 WHEN the keeper is busy THEN `/v1/dirty` itself takes 3–4 s to return, and the SLA clock only starts after it returns
1.10 WHEN `live_sync_probe.py` runs at `CTX_PROBE_SLA_S=8 CTX_PROBE_TRIALS=5` THEN the system passes fewer than 4/5 trials; early trials finish at about 9.2–10.0 s, past the probe window

**OPEN-E: expand/collect readiness**

1.11 WHEN `expand_context` or `collect_hot_context` is called before the AST is hydrated THEN the system returns `ast_warming` immediately, with no bounded wait like pack has

**OPEN-F: empty expand delta**

1.12 WHEN `expand_context` returns an empty delta (e.g. `direction=config`) THEN the system returns `ok=true, delta=[], count=0` with no reason, so "no hop", "AST not ready" and "bad node" look the same
1.13 WHEN the AST is not ready during expand THEN the system gives no `should_retry` / `retry_after_s` signal consistent with pack

**OPEN-A: cold dense warm**

1.14 WHEN the engine cold-starts THEN dense + embedder warm takes about 60–170 s with no per-stage wall-clock timing, so the multi-minute gap after `[embed] plan` cannot be attributed
1.15 WHEN soft search is ready but dense is still loading THEN the system shows signals (`warm_ready`, `runtime_state=READY`, `warm_phase=ready`) that can be mistaken for dense-ready

**OPEN-G: first map timings**

1.16 WHEN the first `map` after attach runs THEN `elapsed_ms` is about 13–14 s while the reported timings cover under 5% of it (observed `elapsed_ms=13172`, `embed_ms=0.4`, `retrieve_ms=40.9`; earlier `14322` vs `1.5 + 113`)

**OPEN-H: process trees**

1.17 WHEN MCP restarts, kill/recover, or host-sim runs occur THEN the system leaves duplicate or orphan `mcp_bridge` / `mcp_locate` / engine processes instead of one chain per IDE session

**OPEN-J: RAM during warm**

1.18 WHEN the engine and locate workers warm THEN machine RAM reaches about 87% (about 2 GB free on 16 GB), which risks an OS kill or IDE crash

**OPEN-I: HTTP pack**

1.19 WHEN a client POSTs `/v1/pack` THEN the system returns `not found`, and the fact that pack is MCP-only is not documented

**OPEN-K: tests**

1.20 WHEN the test suite runs THEN `test_attach_mcp_session_is_nonblocking`, `test_start_attach_warm_pipeline_returns_immediately` and `test_final_check_forces_held_publish` fail, and `test_watchdog_child_stays_alive_then_exits_clean` flakes on its tight 8 s wait

**OPEN-L: body text (optional, deferred)**

1.21 WHEN `pack_context(include_bodies=1)` collects a body from a class node THEN the system returns the full class text (loc is clamped, text is not)

### Expected Behavior (Correct)

**OPEN-B**

2.1 WHEN `CTX_WARM_DEADLINE_MS` is configured for the MCP/engine process THEN the system SHALL report `status.warm_deadline_ms` equal to the configured value in live Cursor/Kiro `status` after an MCP reload (with env=90000, status reports 90000)
2.2 WHEN any surface reads the warm deadline (status, attach, prewarm, health deadline) THEN the system SHALL use one reader that always sees the process env, with one shared default

**OPEN-D**

2.3 WHEN the keeper kicks the newcomer scan THEN the system SHALL call it correctly and SHALL NOT log repeating `newcomer scan failed`
2.4 WHEN the newcomer scan runs THEN the system SHALL keep the walk off the hot critical path (it cannot hold the keeper during a hot save), bound its frequency and path set, respect `.scubieeignore` / ignore builtins, and hot sync SHALL still pass ≥4/5 within 8 s at `CTX_PROBE_SLA_S=8 CTX_PROBE_TRIALS=5`

**OPEN-C**

2.5 WHEN a deletion-only batch arrives while hot saves are active THEN the system SHALL NOT force a full publish ahead of hot saves; deleted paths SHALL stop appearing in results, and explicit hot saves SHALL be prioritized ahead of deletion/full/catch-up work
2.6 WHEN a save follows cleanup or a non-hot sync THEN the system SHALL NOT pay a 3 s+ FAISS/`vec_open` cold open
2.7 WHEN a hot patch is applied after a full reload or concurrent publish THEN the delta base SHALL match the live binder, and `engine.log` SHALL show no binder-drift storm
2.8 WHEN a hot save is due THEN a `[sync] no chunk delta` reconcile SHALL NOT run a 10 s+ job on the keeper ahead of it (defer it, shorten it, or skip gone paths)
2.9 WHEN `/v1/dirty` is posted while the keeper is busy THEN the system SHALL return promptly (target under 200 ms), without waiting on keeper work
2.10 WHEN `live_sync_probe.py` runs at `CTX_PROBE_SLA_S=8 CTX_PROBE_TRIALS=5` with `PYTHONPATH` cleared THEN the system SHALL pass ≥4/5 within 8 s with no routine trial over 10 s; an idle single round SHALL stay about 4.5 s; cleanup SHALL NOT force every next save through a full reload plus a 3 s+ FAISS open; remaining irreducible cases SHALL be documented

**OPEN-E**

2.11 WHEN `expand_context` or `collect_hot_context` is called on a fresh attach THEN the system SHALL apply the same bounded hydrate wait and `should_retry` / `retry_after_s` contract as pack, so after map+pack succeed, expand callers and collect succeed (or need at most one bounded retry) without `ast_warming` thrash

**OPEN-F**

2.12 WHEN `expand_context` returns an empty delta THEN the response SHALL carry an `empty_reason` that distinguishes at least `no_edges`, `ast_not_ready` and `node_unresolved`; `direction=config` on a node with no config edges SHALL return `no_edges`
2.13 WHEN the AST is not ready during expand THEN the system SHALL return `ok=false` or `should_retry=true` with `retry_after_s`, consistent with pack

**OPEN-A**

2.14 WHEN the engine cold-starts THEN the system SHALL log one line per warm stage with wall ms (engine up → soft → embed plan → embed load → dense ready → pack_ready), SHALL fix any rework/thrash those lines prove, and SHALL NOT skip dense; ensure→`embedder_loaded` wall times SHALL be recorded
2.15 WHEN soft search is ready but dense is not THEN the status signals SHALL be honest (`warm_wait.done=false`, deadline from the unified reader), so agents cannot mistake soft-ready for dense-ready

**OPEN-G**

2.16 WHEN the first `map` after attach runs THEN the response timings SHALL explain ≥80% of the first-map wall clock, or the first-map wall clock SHALL drop without quality loss

**OPEN-H**

2.17 WHEN kill/recover plus a normal IDE session have run THEN the process tree SHALL be one bridge→locate→engine chain per IDE session plus the watchdog, with no orphans; the docs SHALL note that host-sim kills IDE MCP bridges and MCP must be reloaded afterwards

**OPEN-J**

2.18 WHEN the engine and locate workers warm THEN concurrent heavy prewarm work SHALL be capped and duplicate processes gone, peak warm RSS SHALL be measured before/after and improved (or duplicates removed), and a floor RAM recommendation SHALL be documented for the beta notes

**OPEN-I**

2.19 WHEN the HTTP pack decision is recorded THEN the system SHALL document that pack is MCP-only (HTTP `/v1/pack` intentionally absent) in `docs/production-ready-0.3.131.md` or the handoff fix log, and no script SHALL expect `/v1/pack`; no HTTP route is added

**OPEN-K**

2.20 WHEN the test suite runs THEN each of the four named tests SHALL pass deterministically or be quarantined (`xfail`/skip) with a recorded reason, without hiding a real regression

**OPEN-L (optional, deferred)**

2.21 WHEN an optional env cap is set and `include_bodies=1` collects a class body THEN the system SHALL cap the returned text; the cap SHALL be env-gated and off by default, so behavior is unchanged when it is unset

### Unchanged Behavior (Regression Prevention)

3.1 WHEN `python scripts/attach_pack_race.py --sessions 2 --packs 3` runs THEN the system SHALL CONTINUE TO return the first pack `ok` with `n_heat>0`, and pack SHALL CONTINUE TO honor its `ast_warming` contract (`should_retry`, `retry_after_s`, `ast_wait_ms`)
3.2 WHEN `python scripts/mcp_host_sim.py --lane a --live --skip-idle --settle-s 35` runs THEN the system SHALL CONTINUE TO return `ok=true` including `pack_first`
3.3 WHEN `python scripts/engine_kill_recover_probe.py --hold-bridge --budget-s 120` runs THEN the system SHALL CONTINUE TO recover on demand with `hold_bridge` and prewarm grace, returning `ok=true`
3.4 WHEN `scripts/sync-uv-install.ps1` runs and `gate` is called THEN the system SHALL CONTINUE TO report `differ:0 missing:0` (with `ignore.py` present) and gate SHALL CONTINUE TO show `index_skip` and `index_write_hint`
3.5 WHEN lean or `include_bodies=1` packs are returned THEN the system SHALL CONTINUE TO clamp `loc` and include `full_loc`
3.6 WHEN `status` is called THEN the system SHALL CONTINUE TO return `pack_ready`, `ast_hydrated` and the `warm_wait` fields, with the stage order `engine_down → soft_loading → dense_loading → pack_ast_loading → ready`
3.7 WHEN a single file is saved on an idle keeper THEN the system SHALL CONTINUE TO reach dense map in about 4.5 s via the append-only patch
3.8 WHEN files are deleted or modified THEN the system SHALL CONTINUE TO reflect them correctly with no stale hits, and durability SHALL be kept (vector flush before full reload, re-embed of missing vectors after a crash)
3.9 WHEN `CTX_HOT_PUBLISH=0` or another kill switch is set THEN the system SHALL CONTINUE TO fall back to the existing behavior
3.10 WHEN new files appear THEN the newcomer scan SHALL CONTINUE TO discover them and SHALL CONTINUE TO skip junk and honor ignore rules
3.11 WHEN graph catch-up work is pending THEN the system SHALL CONTINUE TO run it outside the quiet window and clear `graph_pending`
3.12 WHEN expand/collect run on a hydrated AST THEN the system SHALL CONTINUE TO return the same deltas and bodies with no added latency
3.13 WHEN `map` or `pack_context` runs THEN the system SHALL CONTINUE TO produce unchanged ranking, no slower than before
3.14 WHEN a tool call hits an error path (empty seed, unknown node or handle) THEN the system SHALL CONTINUE TO return a clean `ok=false` payload
3.15 WHEN HTTP `/health`, `/v1/dirty` or search are called THEN the system SHALL CONTINUE TO honor their contracts, and pack SHALL CONTINUE TO be MCP-only
3.16 WHEN the engine warms THEN the system SHALL CONTINUE TO load dense and the embedder fully
3.17 WHEN the engine is idle for `CTX_ENGINE_IDLE_S` THEN the system SHALL CONTINUE TO stop it
3.18 WHEN process cleanup or reconcile runs THEN the system SHALL CONTINUE TO leave every live IDE chain and the watchdog running
3.19 WHEN the test suite runs THEN tests that pass today SHALL CONTINUE TO pass
