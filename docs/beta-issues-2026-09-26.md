# Scubiee beta issues — practical test report

**Date:** 2026-09-26  
**Build under test:** installed uv-tool `scubiee 0.3.131` + workspace `packages/` (see install skew)  
**Project:** `ce_3536ac8e8e83bb8e4d888db37847729c`  
**Host:** Windows 10, Cursor MCP + HTTP engine `:8765`

Evidence artifacts:

- `docs/architecture/_pract_exp_results.json`
- `docs/architecture/_pract_attach_race.json`
- `docs/architecture/_beta_tool_battery.json`
- `docs/superpowers/plans/mcp-host-sim-20260926T105833Z.md`
- `docs/superpowers/plans/2026-09-10-scubiee-mcp-reliability-probes.json` (re-run today)
- `%USERPROFILE%\.scubiee\watchdog.log`

---

## Verdict (short)

**Closed beta: conditional yes.** Locate tools work well once fully warm on a live Cursor session.  
**Not ready for “all green” public beta** until attach-time `pack_context` / `ast_warming`, mid-session engine death + weak watchdog recovery, and install skew (workspace vs uv-tool) are addressed.

---

## What worked (measured)

| Experiment | Result |
| --- | --- |
| Live Cursor `gate` / `status` | Managed, `agent_ready=yes` when dense ready |
| Live Cursor `map` | Dense `D_channel_best`, ~396–674 ms |
| Live Cursor `pack_context` (warm session) | `ok`, `thin=false`, ~110–129 ms |
| Live Cursor `collect_hot_context` | Bodies returned |
| Live Cursor `workspace` show/pin/clear | OK |
| Hot sync new file under `packages/` | Visible in search in **4.8 s** (then **1.8 s** under concurrent maps) |
| Concurrent maps during dirty | 0 PID flaps, 0 search errors |
| Burst search ×15 | PID stable (`11304`), 0 fails |

---

## Issues

### P0 — Blocking for polished beta

#### 1. Full warm is much slower than agents expect (~30s is not enough)

- `status.warm_elapsed_ms` observed **~76s** and **~107s** to reach full ready.
- Soft search can be up in a few seconds; **dense + embedder** needs **~60–90s+** here.
- Agents that wait ~30s after “switch on” still hit prewarm / incomplete semantic and flaky pack.

**Evidence:** live `status` (`warm_elapsed_ms`), host-sim `settle_join_embedder` ~60s.

#### 2. `pack_context` fails with `ast_warming` on fresh MCP bridge even when map is dense and `agent_ready=yes`

- Fresh stdio bridge sessions A/B: **map OK (dense)** then **pack_0/1/2 all `ok=false`, `err=ast_warming`, `n_heat=0`** (6/6 packs).
- Waiting **15s** after status still returned `ast_warming`.
- Host-sim Lane A: map_first/map_second OK; **`pack_first` FAIL** (`heatmap_n=0`).
- Same session later on Cursor MCP: pack succeeds — so this is **attach / AST hydrate race**, not permanent pack death.

**Evidence:** `_pract_attach_race.json`, `mcp-host-sim-20260926T105833Z.md`, reliability audit `mcp_pack_lean_happy` FAIL.

#### 3. Mid-session engine stop / restart class still exists

Watchdog log (today):

- Repeated `health fail` while `pid_alive=False`, then **`skip auto load (agent warm)` with `clients=0`** → engine stays down until MCP/ensure.
- **16:28:00** `force restart` → `restart result=False`, then more `skip restart indexing/prewarm`.
- At start of this session engine was **not listening** on `:8765` until `engine ensure`.
- Reliability audit: `http_health_baseline` FAIL during churn.

**Impact:** agents see MCP/tool failures mid-chat; “warming retry” loops; need manual `scubiee engine ensure .`.

#### 4. Install skew: uv-tool 0.3.131 ≠ workspace packages (beta ship risk)

| Surface | Location | `.scubieeignore` / gate hints |
| --- | --- | --- |
| Workspace | `packages/pipeline/ignore.py` | Present |
| uv-tool install | `…/uv/tools/scubiee/Lib/site-packages/pipeline/` | **`ignore.py` missing**; no `format_gate_ignore_lines` |
| Cursor MCP pin | `pythonw -m pipeline.mcp_bridge` (uv-tool) | Uses **install**, not workspace |
| Live engine today | Often inherited shell `PYTHONPATH=packages` from agent terminals | Can accidentally run **workspace** code |

**Symptoms:**

- Cursor `gate` returned only `1:ce_… sid:…` — **no `index_skip` / `index_write_hint` lines**.
- Scripted bridge with `PYTHONPATH=packages` **does** show `index_skip: builtins+scubieeignore(n=7)`.
- Dirty filter with `dropped` reasons appeared while engine process was influenced by workspace path — **not guaranteed** for a clean uv-tool-only user install.

**Fix required before beta:** reinstall/publish so uv-tool includes ignore + gate fields, or pin MCP/engine to one consistent build.

---

### P1 — Serious quality / reliability

#### 5. `agent_ready=yes` / dense map does not imply pack is usable

Status can report ready while pack still returns `ast_warming`. Agents following “status green → pack” fail.

#### 6. Host-sim Lane A settle battery fails on pack

`mcp_host_sim --lane a --live --skip-idle --settle-s 20` → overall `ok=false` solely on `pack_first`.

#### 7. Reliability audit still fails pack/expand/burst after engine stop/start

Today’s audit: pass=6 fail=5 — map/pack/expand/burst fail set still present under stop→start races.

#### 8. Idle / agent-warm policy leaves engine dead with no clients

When MCP clients drop to 0 and engine dies, watchdog **refuses auto-restart** (`skip auto load (agent warm)`). Next chat pays full cold start or sees refused connections.

#### 9. Stale / duplicate bridge–locate–engine process trees

Process tree often shows multiple `mcp_bridge` / `mcp_locate` / engine PIDs (some tiny RSS leftovers). Increases flap and port confusion after restarts.

#### 10. Class-level pack seeds produce huge locs

Example: `pack_context` seed `BackgroundSyncLoop` → loc `sync_loop.py:105-1474` (entire class). Agents told to Native-Read locs get unusable spans.

---

### P2 — Product / UX gaps

#### 11. No HTTP `/v1/pack` (pack is MCP-only)

`EngineClient` POST `/v1/pack` → `not found`. Fine if intentional; scripts that assume HTTP pack break.

#### 12. `expand_context` often returns empty delta

Observed `delta=[]` / `count=0` with `ok=true` after a good pack. Not always a bug, but agents can’t tell “no hop” vs “AST not ready”.

#### 13. Gate token surface inconsistent across hosts

Cursor gate omitted ignore hints; stdio bridge with workspace code included them. Agents can’t rely on gate for write-hint guidance until install is unified.

#### 14. First cold pack / search can miss SLA

Earlier live timing: first lean pack **~7.6s** vs 5s target; warm multi-seed fine. Queue under load still can push sync >5s (known from 0.3.131 notes).

#### 15. DirectML / ORT prewarm still causes watchdog “health fail while alive”

Log: `health fail count=8/8 pid_alive=True` then force restart during GIL/prewarm windows. Protection exists (`skip restart indexing/prewarm`) but force path still fires.

#### 16. RAM pressure during warm

Status sample: **~87% RAM**, ~2 GB free while warming embedder. Increases risk of OS kill / thrash on 16 GB machines.

---

### P3 — Docs / operator

#### 17. Operator checklist understates warm time

Docs say wait for ready; agents still use ~30s heuristics. Need explicit: soft ≠ dense; wait for `agent_ready=yes` or `embedder_loaded && dense_ready`.

#### 18. `.scubieeignore` feature not in published 0.3.131 wheel

Workspace has the feature + tests; uv-tool install does not ship `ignore.py`. Beta notes must not claim ignore/gate hints until published.

---

## Reproduce recipes

### A. Warm timing

```text
scubiee engine stop
scubiee engine ensure .
# poll status /health every 5s until embedder_loaded && dense_ready
# record wall clock — expect >> 30s on this machine
```

### B. Attach pack race

```text
# New mcp_bridge stdio session, no long warmup:
# initialize → map (expect ok dense) → pack_context lean ×3
# Expect: pack err=ast_warming, heatmap_n=0
```

### C. Hot sync OK path

```text
# Write packages/pipeline/_probe_TOKEN.py with unique TOKEN
# mark_dirty / save → search/map for TOKEN within 5s
# Measured: 1.8–4.8s when engine warm
```

### D. Install skew

```text
Test-Path …/uv/tools/scubiee/Lib/site-packages/pipeline/ignore.py   # False today
# Cursor gate: no index_skip lines
# Bridge with PYTHONPATH=packages: index_skip present
```

---

## Suggested beta gate (must be green)

1. Publish/reinstall so **uv-tool == workspace** for ignore + gate hints (or drop claims).
2. Pack after attach: either block `agent_ready` until AST hydrated, or auto-retry pack until heatmap non-empty (bounded).
3. Watchdog: restart dead engine when MCP demand returns; don’t leave “skip auto load” black hole.
4. Document warm: **wait for `agent_ready=yes`**, not a fixed 30s.
5. Re-run: `mcp_host_sim --lane a --live --settle-s 35` with **pack_first ok**, plus Cursor live ladder.

---

## Issue ID index

| ID | Severity | Title |
| --- | --- | --- |
| BETA-01 | P0 | Warm ≫ 30s; soft ≠ dense |
| BETA-02 | P0 | pack `ast_warming` on fresh bridge |
| BETA-03 | P0 | Mid-session engine death / weak auto-recover |
| BETA-04 | P0 | uv-tool vs workspace install skew |
| BETA-05 | P1 | agent_ready lies about pack readiness |
| BETA-06 | P1 | Host-sim pack_first fail |
| BETA-07 | P1 | Reliability audit pack/expand/burst fails |
| BETA-08 | P1 | Idle agent-warm skip auto load |
| BETA-09 | P1 | Stale multi process trees |
| BETA-10 | P1 | Huge class loc spans from pack seeds |
| BETA-11 | P2 | No HTTP `/v1/pack` |
| BETA-12 | P2 | Empty expand_context delta UX |
| BETA-13 | P2 | Gate hints missing on Cursor |
| BETA-14 | P2 | Cold pack / queue SLA misses |
| BETA-15 | P2 | Watchdog force restart during prewarm |
| BETA-16 | P2 | High RAM during warm |
| BETA-17 | P3 | Operator warm guidance |
| BETA-18 | P3 | Ignore feature not in published wheel |

---

## How to use this file with Kiro

1. Open this repo in Kiro with Scubiee MCP connected (`project_id=ce_3536ac8e8e83bb8e4d888db37847729c`).
2. Paste **Kiro starter prompt** (below) as the first user message.
3. Prefer Scubiee `map` → `pack_context` (lean) for soft locate; Grep/Read for needles.
4. After fixes: run the acceptance battery in the prompt; do **not** claim green on unit tests alone.
5. Ship path: fix in `packages/` → reinstall/repair uv-tool so Cursor MCP + engine match workspace (BETA-04).

### Suggested fix order

1. **BETA-04** — unify install (otherwise Cursor never sees ignore/gate fixes).
2. **BETA-02 + BETA-05** — pack/`ast_warming` vs `agent_ready` coherence.
3. **BETA-03 + BETA-08 + BETA-15** — watchdog / mid-session recover.
4. **BETA-01 + BETA-17** — warm signaling + docs (even if wall clock stays high).
5. **BETA-10**, then P2/P3 as capacity allows.

### Key code surfaces (start here)

| Area | Paths |
| --- | --- |
| Pack / AST warm | `packages/pipeline/mcp_locate.py` (`pack_context`, `ast_warming`, `ast_hydrated`), pack/trace hydrate |
| Agent ready | `packages/pipeline/sync_status.py`, `mcp_locate.status_impl` / `derive_agent_ready` |
| Watchdog / idle | `packages/pipeline/watchdog.py`, `warm_autoload.py`, `lifecycle_runtime.py` |
| Ignore / dirty | `packages/pipeline/ignore.py`, `ce_service.mark_dirty`, `sync_loop.mark_dirty` |
| Gate hints | `mcp_locate.gate_impl`, `format_gate_ignore_lines` |
| Host sim gate | `scripts/mcp_host_sim.py`, `packages/pipeline/mcp_host_sim/` |
| Reliability audit | `scripts/scubiee_mcp_reliability_audit.py` |

### Acceptance battery (must pass before “fixed”)

```text
# 1) Install consistency
Test-Path %USERPROFILE%\AppData\Roaming\uv\tools\scubiee\Lib\site-packages\pipeline\ignore.py
# Expect True after publish/reinstall

# 2) Warm + ready truth
scubiee engine ensure .
# status: agent_ready=yes only when pack can succeed

# 3) Attach pack race
# Fresh bridge: initialize → map → pack lean (no long sleep)
# Expect pack ok + heatmap_n > 0 (or explicit retryable warming with should_retry)

# 4) Host sim
python scripts/mcp_host_sim.py --lane a --live --skip-idle --settle-s 35
# Expect ok=true including pack_first

# 5) Hot sync sanity
# Write packages/pipeline/_probe_TOKEN.py → dirty → map/search TOKEN ≤5s warm path

# 6) Mid-session recover
# Kill engine while MCP connected (or simulate clients=0 death) → demand returns → engine back without manual ensure
```

---

## Kiro starter prompt

Copy everything inside the fence into a new Kiro chat:

```text
You are fixing Scubiee beta blockers for closed beta. Repo: context-engine (Windows). Managed project_id=ce_3536ac8e8e83bb8e4d888db37847729c.

READ FIRST (do not skip):
- docs/beta-issues-2026-09-26.md  — full issue list BETA-01…18, evidence paths, acceptance battery
- Evidence JSON/MD linked at the top of that file
- Prefer Scubiee MCP locate: map → pack_context(lean) → expand/collect if needed. BAN shell scubiee map|pack while MCP is up. Edit/Write stay native.

CONTEXT:
- Installed product is uv-tool scubiee 0.3.131; Cursor MCP pins pythonw -m pipeline.mcp_bridge from that install.
- Workspace packages/ has newer work (e.g. .scubieeignore / ignore.py / gate index_skip) that is NOT in the uv-tool site-packages today (BETA-04). Agent shells often set PYTHONPATH=packages and accidentally make the engine look “fixed” while Cursor MCP still runs the old install — do not trust that.
- Hot sync under packages/ works (~2–5s). Map/pack work on a fully warm Cursor session. Failures cluster on cold attach, AST hydrate, and engine/watchdog lifecycle.

GOAL (in order — finish each before the next unless blocked):
1) BETA-04 — Make uv-tool install and workspace agree for ignore.py + gate index_skip/index_write_hint. Document the reinstall/repair command. Verify Cursor gate shows index_skip lines without PYTHONPATH hacks.
2) BETA-02 + BETA-05 — Fresh MCP bridge: map dense OK must not be followed by pack_context err=ast_warming / heatmap_n=0 while agent_ready=yes. Either (a) gate agent_ready until pack/AST truly usable, and/or (b) make pack wait/retry hydrate with clear should_retry, and/or (c) ensure AST is ready before first pack after attach. Prove with a fresh-bridge script: map then pack succeeds (or one bounded retry).
3) BETA-03 + BETA-08 + BETA-15 — Mid-session engine death: watchdog must not leave “skip auto load (agent warm)” black holes when MCP demand returns; avoid force-restart thrash during ORT prewarm while still recovering real crashes. Prove with ensure/kill/reconnect style check.
4) BETA-01 + BETA-17 — Soft ≠ dense. status/docs must make warm wait criteria explicit (agent_ready=yes / embedder_loaded+dense). 30s wait is insufficient on this machine (~76–107s observed) — improve signaling even if wall clock stays high.
5) BETA-10 — Pack seeds that resolve to whole classes must not return multi-thousand-line locs; prefer function/entrypoint spans agents can Native-Read.
6) Only then P2/P3 (expand empty-delta UX, process-tree cleanup, optional /v1/pack, RAM notes).

CONSTRAINTS:
- Do not claim green on unit tests alone. Run the acceptance battery in docs/beta-issues-2026-09-26.md (host-sim Lane A pack_first ok, attach pack race, install ignore.py present, hot sync sanity).
- Report measured timings and ok flags.
- Prefer minimal focused patches; no drive-by refactors; no commits unless I ask.
- Keep GATE / MCP locate rules: edit MUST pack when using Scubiee; query quality denser code-vocab.

START NOW:
1) gate + status (confirm managed + whether ignore hints appear on this host).
2) Confirm install skew: does uv-tool site-packages contain pipeline/ignore.py?
3) map→pack once on the soft problem “pack_context ast_warming agent_ready hydrate mcp_bridge attach” to land in the right modules.
4) Propose a short plan (files + approach) for BETA-04 then BETA-02/05, then implement.
```

### Shorter follow-up prompts (optional)

**Pack-only:**

```text
Focus only on BETA-02/05 in docs/beta-issues-2026-09-26.md. Fresh bridge pack must not return ast_warming with empty heatmap while map is dense and agent_ready=yes. Fix + prove with attach race script. No unrelated refactors.
```

**Watchdog-only:**

```text
Focus only on BETA-03/08/15 in docs/beta-issues-2026-09-26.md. Engine dies mid-session / clients=0; watchdog skip auto load leaves MCP dead. Fix recover-on-demand; don’t thrash during ORT prewarm. Prove with kill/reconnect. Evidence: %USERPROFILE%\.scubiee\watchdog.log
```

**Ship install-only:**

```text
Focus only on BETA-04/18. Publish or reinstall so uv-tool scubiee includes packages/pipeline/ignore.py and gate index_skip/index_write_hint. Cursor MCP gate must show those lines with no PYTHONPATH=packages. Document exact commands.
```

---

## Fix status (Kiro session, 2026-09-26 evening)

Uncommitted. All runs used the uv-tool interpreter with `PYTHONPATH` cleared, after `scripts/sync-uv-install.ps1` reported `differ: 0 missing: 0`.

| ID | Change | Proof |
| --- | --- | --- |
| BETA-04 / 13 / 18 | `scripts/sync-uv-install.ps1`: `uv pip install --no-deps --reinstall-package scubiee .` into the uv-tool env (keeps `onnxruntime-directml`), then byte-parity check of every packaged `.py` + `import pipeline.ignore`. `-CheckOnly` verifies only. | `ignore.py` present = True. Fresh Cursor-config bridge `gate` shows `index_skip: builtins+scubieeignore(n=7)` and `index_write_hint`. Live Cursor window not re-verified (Cursor MCP was not running at the end); reload Scubiee MCP in Cursor to pick it up. |
| BETA-02 / 05 | Root cause: `hydrate_ast_bundle(bake_on_miss=True)` rejected the on-disk bundle whenever its fingerprint was stale (every edit) and spawned a bake child that loads the same stale bundle anyway. It now serves the stale bundle in-process. `pack_context` waits up to `CTX_MCP_PACK_AST_WAIT_S` (10 s) for the hydrate before returning `ast_warming` with `should_retry=true`, `retry_after_s=3`, and `ast_wait_ms`. `status` adds `pack_ready` and `ast_hydrated`. | `scripts/attach_pack_race.py` (map then pack, no sleep). Before: pack ×3 `ast_warming`. After: 2/2 sessions first pack ok, `n_heat=16`, first pack 1.1–1.2 s, later packs 95–205 ms (`_attach_race_battery_nowait.json`). |
| BETA-06 | (follows from 02) | `mcp_host_sim --lane a --live --skip-idle --settle-s 35`: `ok=true`, `pack_first` 201 ms, `map_first` 70 ms, `expand_first` 73 ms, `auto_warm` 18.0 s (`mcp-host-sim-20260926T160108Z.md`). Earlier runs today: one `WARM_TIMEOUT` (soft at 41.0 s vs 40 s budget), one hung run with no report. |
| BETA-03 / 08 | Watchdog: dead engine + MCP demand recovers on the first failing tick (only the first recovery after a healthy stretch; crash loops keep normal pacing). `enforce_mcp_warm_contract` holds RUN (`hold_bridge`) while a non-orphan bridge is alive, so the idle policy does not stop an engine the watchdog would restart. `mcp_frontend_present` skips the per-process tree walk (~0.8 s → 0.01 s). | `scripts/engine_kill_recover_probe.py` (taskkill engine tree, no `ensure`): run 1 kill→health 20.8 s / soft 23.7 s via watchdog `recover now`; run 2 (bridge held) kill→health 6.7 s / soft 44.6 s. |
| BETA-15 | Watchdog: a prewarm past the 45 s window is treated as slow, not wedged, while the engine tree keeps burning CPU (≥1 s per tick), up to `CTX_WATCHDOG_PREWARM_GRACE_S` (180 s). | Log: `prewarm slow but progressing cpu_delta_s=15.x — not restarting` for ~3 min, then one heal at the cap. Unit test `test_prewarm_progress_discriminates_slow_vs_wedged`. |
| BETA-01 / 17 | `status.warm_wait` = `{done, stage, wait_for, soft_ready, dense_ready, pack_ready, elapsed_s, retry_after_s, note}`. Stages: `engine_down → soft_loading → dense_loading → pack_ast_loading → ready`. Docs: `docs/production-ready-0.3.131.md` "Warm wait criteria" + "Install sync". | Agent-style wait on `warm_wait.done`: 10–26 s when an engine was already starting, map + pack ok right after. |
| BETA-10 | Lean heatmap rows clamp spans over `CTX_PACK_LOC_MAX_LINES` (250) to the first `CTX_PACK_LOC_HEAD_LINES` (120) lines and keep the original span in `full_loc`. | Seed `BackgroundSyncLoop`: `loc sync_loop.py:105-224`, `full_loc 105-1474`, largest span in the heatmap 205 lines. |

### Still open / found during verification

- **Cold dense warm is still slow and variable.** Measured `ensure` → `embedder_loaded` 171 s with no client attached; once one prewarm sat after `[embed] plan` for >4 min at ~100% CPU until the 180 s grace cap healed it. Root cause not found (the embed cache replay is 2.6 s, so it is not that).
- **Hot sync:** 3/5 trials ≤5 s (hits 4.0–5.1 s) on the synced install. Not the 10/10 from the 0.3.131 worklog.
- **Newcomer scan is broken in 0.3.131:** `_start_newcomer_scan` calls `_enqueue_newcomers()` without its required `now=` argument, so it logs `newcomer scan failed` every 30 s. Fixing that call made hot sync 0/5 (18–40 s; the repo walk starves the keeper). Left as is; it needs a throttling decision first.
- Idle policy with `CTX_ENGINE_IDLE_S=10` stops the engine ~10 s after the last client leaves, so every new chat after a gap pays a cold start (by design; RAM).
- Pre-existing test failures (fail on HEAD too): `test_attach_mcp_session_is_nonblocking`, `test_start_attach_warm_pipeline_returns_immediately`, `test_final_check_forces_held_publish`. `test_watchdog_child_stays_alive_then_exits_clean` has a tight 8 s wait and flaked once in a long batch.
- P2/P3 not started: BETA-09, 11, 12, 14, 16. `expand_context` / `collect_hot_context` still return `ast_warming` immediately (no bounded wait like pack).
