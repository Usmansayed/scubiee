# Scubiee open beta issues — Kiro fix handoff

**Date:** 2026-09-26 (evening)  
**Repo:** `C:\Users\usman\Downloads\context-engine`  
**Project:** `ce_3536ac8e8e83bb8e4d888db37847729c`  
**Build:** uv-tool `scubiee 0.3.131` + workspace `packages/` (keep in sync with `scripts/sync-uv-install.ps1`)  
**Host:** Windows 10, Cursor / Kiro MCP + engine `:8765`

**Purpose:** Fix **all remaining open issues** where possible. Some costs (cold dense warm wall-clock, RAM) may stay high on this machine — still look for **wrong-path / thrash / misleading signals / queue starvation** and fix those. Do not claim green on unit tests alone.

**Related docs (read first):**
- `docs/beta-issues-2026-09-26.md` — original BETA-01…18 + evening fix log
- `docs/scubiee-bugs-found.md` — live tool exercise + BUG-1 / OBS-*
- `docs/production-ready-0.3.131.md` — warm wait / install sync notes
- `docs/sync-fix-worklog-0.3.131.md` — hot-lane history (10/10 @ 5s once; regress under churn)

---

## How to work (mandatory)

1. Prefer Scubiee MCP locate **VERY STRICTLY** in this managed repo: soft/structural → `map` → `pack_context`(lean) → `expand_context` / `collect_hot_context`. Needles → Grep/Glob/Read. **BAN** shell `scubiee map|pack|expand` while MCP is callable. Edit/Write stay native.
2. After any code change: run `scripts/sync-uv-install.ps1` (PYTHONPATH cleared) so Cursor/Kiro MCP sees the install, then **reload Scubiee MCP** in the IDE.
3. Prove with the acceptance battery below. Report measured timings and `ok` flags.
4. Prefer minimal focused patches; no drive-by refactors; **no commits unless asked**.
5. Fresh bridge / probes must strip `PYTHONPATH` so uv-tool code is what runs.

---

## Already fixed — DO NOT re-litigate (verify only)

| ID | What shipped | Proof to re-check |
| --- | --- | --- |
| BETA-02 / 05 | Stale AST bundle served in-process; pack waits hydrate; `pack_ready` / `ast_hydrated` | `python scripts/attach_pack_race.py --sessions 2 --packs 3` → first pack ok, `n_heat>0` |
| BETA-06 | Host-sim pack_first | `python scripts/mcp_host_sim.py --lane a --live --skip-idle --settle-s 35` → `ok=true`, pack_first ok |
| BETA-03 / 08 / 15 | Recover-on-demand; hold_bridge; prewarm progress grace | `python scripts/engine_kill_recover_probe.py --hold-bridge --budget-s 120` |
| BETA-04 / 13 / 18 | `sync-uv-install.ps1`; ignore + gate hints | `gate` shows `index_skip` + `index_write_hint`; `ignore.py` present in uv-tool |
| BETA-01 / 17 (signaling) | `status.warm_wait` block | Live `status` has `warm_wait.done` / stages — **wall clock still open** (see OPEN-A) |
| BETA-10 lean | `_heat_card` loc clamp + `full_loc` | Lean pack on `BackgroundSyncLoop` → loc head + `full_loc` |
| BETA-10 bodies (BUG-1) | `_slim_loc_item` / `_slim_pack_item` clamp loc (text body kept) | `test_include_bodies_paths_clamp_loc`; reload MCP then `include_bodies=1` |

If any of the above regresses, fix regression first before new work.

---

## Open issues — fix these

### OPEN-A — Cold dense warm still too slow / variable (ex BETA-01 wall clock)

**Symptom:** Soft search can be up in seconds; **dense + embedder** often **~60–90s+**, sometimes **~100–170s**. Agents that wait ~30s still fail. Host-sim / ensure can hang or hit prewarm grace (~180s) then heal.

**Why it might be wrong (not just “hardware is slow”):**
- Misleading deadline: MCP env sets `CTX_WARM_DEADLINE_MS=90000` (`mcp_install.py`) but `status.warm_deadline_ms` often still reports **30000** (default in `warm_contract.warm_deadline_ms` / `runtime_controller`) — agents trust 30s.
- Prewarm can sit after `[embed] plan` at ~100% CPU for minutes; embed cache replay itself is only ~2.6s — something else is wedging or redoing work.
- Multiple warm helpers (`warm_contract.py` vs `runtime_controller.py`) both define `warm_deadline_ms()` — risk of which one status uses vs which attach uses.
- Idle stop (`CTX_ENGINE_IDLE_S`) + new chat = full cold start every gap (by design for RAM, but compounds perceived “warm is broken”).

**What to do:**
1. Make `status.warm_deadline_ms` (and any attach deadline field) **always** read the effective env (`CTX_WARM_DEADLINE_MS` from MCP/engine process). Fix OBS-1 as part of this.
2. Instrument cold warm: one line per stage with wall ms (engine up → soft → embed plan → embed load → dense ready → pack_ready). Find the multi-minute gap.
3. If the gap is **rework / thrash** (re-plan, re-open FAISS, competing keeper, newcomer walk): fix the thrash. If it is unavoidable ORT/DirectML load: keep wall clock, but make `warm_wait` / docs unreachable for “wait 30s” traps.
4. Do **not** lower product quality by skipping dense; fix signaling + thrash first.

**Done when:** `warm_deadline_ms` matches configured deadline; cold warm either (a) measurably faster on this host without quality loss, or (b) stages are honest and agents cannot mistake soft-ready for dense-ready. Record ensure→`embedder_loaded` wall times.

**Evidence paths:** `%USERPROFILE%\.scubiee\engine.log`, live `status.warm_wait`, host-sim `auto_warm` / `settle_join_embedder`.

---

### OPEN-B — OBS-1: `warm_deadline_ms=30000` while warm took 55s+ / env is 90000

**Symptom:** Live `status` shows `warm_deadline_ms: 30000` with `warm_elapsed_ms` ~55k–100k+. MCP pin env has `CTX_WARM_DEADLINE_MS=90000`.

**Likely cause:** Status path uses a helper whose default is 30000, or reads deadline before MCP env is applied / from a different process than the bridge.

**What to do:** Trace who fills `warm_deadline_ms` in `status` / `warm_contract` / `mcp_locate`. Unify on one reader that always sees process env. Add a unit/host assertion: with env=90000, status reports 90000.

**Done when:** Live Cursor/Kiro `status` shows `warm_deadline_ms` equal to configured env after MCP reload.

---

### OPEN-C — Hot sync under churn: misses ~8–10s ceiling (ex BETA-14 / hot-lane regress)

**Product bar (owner):** ~6s is OK if close to 5; **must not** routinely exceed **~8–10s**. Steady idle save ~4.5s is fine.

**Symptom (measured 2026-09-26):**
- Idle keeper: ~4.3–4.8s PASS.
- Trial burst: early trials **not searchable within 8s** (`search_ms=None`); engine.log shows they finished at **~9.2s / ~10.0s** — past the probe window, not “lost forever”.
- Cleanup after each trial: delete dir → dirty `f1`+`__init__` → almost always `publish=full` with `publish_call_ms` **6–8s**, `total_ms` **10–13s**.
- Then next save: `vec_open` spikes (**~3870ms**), `write_ms` **~4.7s**.
- `hot patch declined (binder drift: live chunks N != delta base M)` → full reload.
- Concurrent `[sync] no chunk delta … ms=10–12s` on same probe paths (vector reconcile / no-op touch) steals the keeper thread.
- `/v1/dirty` itself sometimes **3–4s** when keeper is busy (SLA clock starts after dirty returns → user-facing worse than `hit_ms`).

**Likely causes (wrong path / queue design):**
1. Deletion batches always take **full publish** and invalidate FAISS reuse → next hot save pays cold open.
2. Binder drift after overlapping patch/full publishes → hot patch aborted.
3. Graph catchup / no-delta reconcile on deleted probe paths queues behind or ahead of hot saves.
4. Probe creates `__init__.py` + file then deletes both — worst-case churn; still reflects real agent “add then delete” patterns.
5. Newcomer / background work on keeper thread (see OPEN-D).

**What to do:**
1. Map→pack into `sync_loop` / `ce_service.mark_dirty` / publish / `apply_chunk_delta` with query about binder drift + full publish + vec_open.
2. Prefer: hot deletions use append-only or cheaper publish when safe; or prioritize **explicit hot saves ahead of** deletion/full/catchup (worklog already claimed this — verify it still holds under probe cleanup).
3. Fix binder drift: ensure `base_chunk_count` matches live binder after full reload / concurrent publish; don’t leave delta bases stale.
4. Ensure `[sync] no chunk delta` reconcile cannot run a 10s+ job on the keeper while a hot save is due (defer, shorter path, or off-thread).
5. Re-run: `CTX_PROBE_SLA_S=8 CTX_PROBE_TRIALS=5` with PYTHONPATH cleared; target **≥4/5** within 8s, none routinely >10s when settled. Also one idle single-round.

**Done when:** 5-trial hot sync at 8s SLA is mostly green; engine.log shows cleanup not forcing every next save through full reload + 3s+ FAISS open. Document remaining irreducible cases.

**Evidence:** `%USERPROFILE%\.scubiee\engine.log` (`[keeper] hot sync`, `[publish] hot patch declined`, `[sync] no chunk delta`), `docs/architecture/_battery_hotsync_sla8.txt`.

---

### OPEN-D — Newcomer scan broken + starves hot sync if naively fixed

**Symptom:** Every ~30s: `newcomer scan failed` because `_start_newcomer_scan` calls `_enqueue_newcomers()` **without required `now=`** (`sync_loop.py` ~390).

**Trap:** Passing `now=` alone made hot sync **0/5** (18–40s) — full repo walk on the keeper starves the hot lane.

**What to do:**
1. Fix the call signature **and** keep the walk **off the hot critical path** (already intended: own thread / throttle). Verify walk cannot hold the keeper during a hot save.
2. Bound frequency and path set (respect `.scubieeignore` / ignore builtins).
3. Prove: no `newcomer scan failed` spam; `CTX_PROBE_TRIALS=5` SLA_S=8 still passes at the OPEN-C bar.

**Done when:** Call is correct, logs clean, hot sync not regressed.

---

### OPEN-E — expand_context / collect_hot_context return `ast_warming` with no wait (unlike pack)

**Symptom:** Pack has bounded AST wait (`CTX_MCP_PACK_AST_WAIT_S`); expand/collect can still return `ast_warming` immediately.

**What to do:** Share the same hydrate-wait / `should_retry` / `retry_after_s` contract as pack (or document and gate on `pack_ready` / `ast_hydrated` only). Prefer one helper.

**Done when:** Fresh attach: after map+pack ok, expand_context callers and collect_hot_context succeed (or one bounded retry) without empty/`ast_warming` thrash.

---

### OPEN-F — BETA-12 / OBS-4: empty expand delta UX

**Symptom:** `expand_context(..., direction=config)` (and sometimes other directions) → `ok=true`, `delta=[]`, `count=0`. Agent cannot tell **“no hop”** vs **“AST not ready”** vs **“bad node”**.

**What to do:**
1. Distinguish: `empty_reason` / `note` field: `no_edges` | `ast_not_ready` | `node_unresolved` | …
2. If AST not ready: `ok=false` or `should_retry=true` with `retry_after_s`, consistent with pack.
3. Live check: config direction on a node with no config edges → clear `no_edges`; before hydrate → clear not-ready.

**Done when:** Empty delta is unambiguous in the JSON agents see.

---

### OPEN-G — OBS-3: first map after attach ~14s with opaque timings

**Symptom:** First `map` `elapsed_ms` ~14322 while `embed_ms`~1.5 + `retrieve_ms`~113. Second map ~5.7s; later cold topic ~1.9s.

**Likely cause:** One-time attach cost (seed finalize, graph, session, binder) not attributed in `timings`.

**What to do:** Break out first-call stages in map response timings (or engine log). If cost is avoidable thrash, remove it; if unavoidable, expose it so agents/SLA don’t treat it as retrieve latency.

**Done when:** Timings explain ≥80% of first-map wall, or first-map wall drops without quality loss.

---

### OPEN-H — BETA-09: stale / duplicate bridge–locate–engine process trees

**Symptom:** Multiple `mcp_bridge` / `mcp_locate` / engine PIDs after restarts; host-sim `clean_slate` kills leftovers; Cursor can show Not connected after host-sim.

**What to do:** On bridge start / watchdog reconcile: coalesce same-host MCP workers (see `lifecycle_runtime.coalesce_mcp_clients`); kill orphan locate without IDE parent; document that host-sim kills IDE MCP (reload after).

**Done when:** After kill/recover + normal Cursor session, process tree is one bridge→locate→engine chain (plus watchdog), not a pile of orphans.

---

### OPEN-I — BETA-11: No HTTP `/v1/pack` (optional / decide)

**Symptom:** `EngineClient` POST `/v1/pack` → not found. Pack is MCP-only.

**What to do:** Either (a) document as intentional and stop scripts from expecting it, or (b) add a thin HTTP pack for probes only. **Default recommendation:** document intentional; do not expand surface unless probes truly need it.

**Done when:** Decision recorded in `docs/production-ready-0.3.131.md` or this file’s fix log; scripts updated if needed.

---

### OPEN-J — BETA-16: RAM pressure during warm

**Symptom:** ~87% RAM / ~2GB free while warming on 16GB machines → OS kill / Cursor crash risk (seen mid-session).

**What to do:** Cap concurrent prewarm work; ensure idle stop / single embedder load; avoid duplicate engine processes (ties to OPEN-H). Measure RSS during warm before/after. Full “half the RAM” may be impossible with DirectML — reduce thrash and duplicate processes first.

**Done when:** Peak warm RSS improved or duplicate processes gone; document floor RAM recommendation for beta notes.

---

### OPEN-K — Pre-existing flaky / failing tests (cleanup)

**Known fail/flake on HEAD:**
- `test_attach_mcp_session_is_nonblocking`
- `test_start_attach_warm_pipeline_returns_immediately`
- `test_final_check_forces_held_publish`
- `test_watchdog_child_stays_alive_then_exits_clean` (tight 8s wait)

**What to do:** Fix or quarantine with reason. Do not hide real regressions.

---

### OPEN-L — include_bodies still returns full class **text** (by design of BUG-1)

**Note:** Loc is clamped; `pack[].text` may still be the whole class when `include_bodies=1`. That is intentional for “agent asked for bodies.” Optional follow-up: cap body chars for class seeds or prefer method seeds. **Lower priority** than OPEN-A…D.

---

## Suggested fix order

1. **OPEN-B** (deadline label) — small, high leverage for agent behavior.  
2. **OPEN-D** (newcomer) — fix call + keep off hot path; prove hot sync.  
3. **OPEN-C** (hot sync churn / binder drift / full publish) — main reliability.  
4. **OPEN-E + OPEN-F** (expand wait + empty delta UX).  
5. **OPEN-A** (cold warm thrash instrumentation + any real thrash fix).  
6. **OPEN-G** (first-map timings).  
7. **OPEN-H / OPEN-J** (process tree / RAM).  
8. **OPEN-I / OPEN-K / OPEN-L** as capacity allows.

---

## Acceptance battery (must pass before “open issues fixed”)

```text
# 0) Sync install (always)
powershell -File scripts/sync-uv-install.ps1
# Expect: differ:0 missing:0 ; ignore.py present
# Reload Scubiee MCP in IDE

# 1) Gate + status
# gate: index_skip + index_write_hint
# status: pack_ready=true, ast_hydrated=true, warm_wait.done,
#         warm_deadline_ms == CTX_WARM_DEADLINE_MS (e.g. 90000)

# 2) Attach pack race
python scripts/attach_pack_race.py --sessions 2 --packs 3
# Expect: ok=true, first pack n_heat>0

# 3) Host-sim (LAST — kills MCP bridges)
python scripts/mcp_host_sim.py --lane a --live --skip-idle --settle-s 35
# Expect: ok=true including pack_first
# Then reload MCP in IDE

# 4) Hot sync
# PYTHONPATH cleared; uv-tool python
$env:CTX_PROBE_SLA_S='8'; $env:CTX_PROBE_TRIALS='5'
python scripts/live_sync_probe.py
# Expect: pass rate ≥4/5 within 8s; no routine >10s when settled
# engine.log: no binder-drift storm after cleanups

# 5) Kill/recover
python scripts/engine_kill_recover_probe.py --hold-bridge --budget-s 120
# Expect: ok=true

# 6) Live ladder (Cursor/Kiro MCP after reload)
# map → pack lean → expand_context callers → collect_hot_context
# expand_context empty config → has empty_reason (OPEN-F)
# pack include_bodies=1 on BackgroundSyncLoop → loc clamped + full_loc

# 7) Newcomer
# engine.log: no repeating "newcomer scan failed"
```

**Do not claim green** if only unit tests pass. Report measured timings.

---

## Copy-paste starter prompt for Kiro

```text
You are fixing remaining Scubiee CLOSED-BETA open issues. Repo: context-engine (Windows). Managed project_id=ce_3536ac8e8e83bb8e4d888db37847729c.

READ FIRST:
- docs/beta-open-issues-kiro-fix-2026-09-26.md  ← THIS FILE (open issues, causes, done-when, battery)
- docs/beta-issues-2026-09-26.md (history + already-fixed table)
- docs/scubiee-bugs-found.md (OBS-1/3/4, BUG-1 bodies clamp)

RULES (this repo — VERY STRICTLY):
- Soft/structural locate MUST use Scubiee MCP: map → pack_context(lean) → expand/collect.
- BAN shell scubiee map|pack|expand while MCP callable. Edit/Write native.
- After code changes: scripts/sync-uv-install.ps1 + reload MCP. Strip PYTHONPATH for probes.

ALREADY FIXED — verify only, do not rewrite: BETA-02/05/06 attach pack, BETA-03/08/15 watchdog, BETA-04/13/18 install sync, BETA-10 lean+bodies loc clamp, warm_wait signaling.

GOAL — fix all OPEN-* in docs/beta-open-issues-kiro-fix-2026-09-26.md in the suggested order (B → D → C → E/F → A → …). Prefer fixing wrong-path/thrash/misleading signals over “accept slow.”

CONSTRAINTS:
- Minimal focused patches; no drive-by refactors; no commits unless I ask.
- Prove with the acceptance battery in that file (host-sim last). Report timings and ok flags.
- Hot sync bar: ~6s OK; must not routinely exceed ~8–10s. Newcomer fix must not starve hot lane.

START NOW:
1) gate + status (confirm warm_deadline_ms vs CTX_WARM_DEADLINE_MS — OPEN-B).
2) Confirm newcomer scan failure in engine.log — OPEN-D.
3) Short plan (files + approach) for OPEN-B then OPEN-D then OPEN-C, then implement.
```

---

## Fix log (fill as you go)

| ID | Change | Proof | Status |
| --- | --- | --- | --- |
| OPEN-B | `warm_contract` default 90s + `warm_deadline_source` | Live status `warm_deadline_ms=90000` source=env | done |
| OPEN-D | `_enqueue_newcomers(now=)` + in-flight filter + `_hot_work_pending` quiet | After **engine restart onto synced install**, no `newcomer scan failed`; 5/5 hot | done |
| OPEN-C | deletion defer when on-disk hot pending; hot-first; keep VDB on non-hot | Hot sync **5/5 @8s** (p50 4.1s max 4.8s) after restart; cleanup still `publish=full` between trials but settled before measure | mostly done |
| OPEN-E | `_await_ast_ready` before expand/pack | attach_pack_race ok; host-sim expand ok | done |
| OPEN-F | `empty_reason` only when delta empty (omit None) | Live MCP expand config → `empty_reason=already_expanded`; unit golden expand 39 pass | done |
| OPEN-A | signaling OK; cold wall clock still ~60–90s+ on this host | status `warm_wait` honest; host-sim soft_ready +15.6s this run | partial |
| OPEN-G | | | open |
| OPEN-H | | | open |
| OPEN-J | | | open |
| OPEN-I | | | open |
| OPEN-K | | | open |
| OPEN-L | | | open (optional) |

### Acceptance battery (2026-09-27, post `sync-uv-install` + engine restart + ONNX repair)

| Probe | Result |
| --- | --- |
| `scubiee setup --repair` | restored `model_fp16.onnx` (~275MB); bulk reindex ONNX miss cleared |
| attach_pack_race | ok (packs ok) |
| live_sync rounds=2 SLA=8 | PASS measured **3709ms** |
| live_sync TRIALS=5 SLA=8 | **5/5 PASS** hit p50=4078 p95=4761 |
| mcp_host_sim Lane A settle=35 | **ok=true** map_first 103ms pack_first 181ms |
| engine_kill_recover --hold-bridge | **ok=true** kill→soft **70.8s** |
| expand empty_reason (MCP) | `already_expanded` on empty config delta |

**Ops note:** syncing uv-tool does **not** hot-reload a running engine — stop/ensure after sync or probes run old code (newcomer `now=` miss, hung 0/5).

---

## Notes for closed beta messaging

- **Ship closed beta** is still reasonable with caveats: wait for `warm_wait.done` / dense, not 30s; hot sync fine when quiet; expect slower after delete storms until OPEN-C lands.
- **Do not** advertise “5s hot sync always” or “warm in 30s” until OPEN-A/C/B are addressed.
