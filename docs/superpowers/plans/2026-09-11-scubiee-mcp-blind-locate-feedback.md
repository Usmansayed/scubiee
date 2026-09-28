# Scubiee MCP blind locate battery — feedback report

**Date:** 2026-09-11  
**Host:** Cursor MCP `project-0-context-engine-scubiee`  
**Repo / project:** `C:\Users\usman\Downloads\context-engine` / `ce_2f9c289d2a885432f240969ea2889532`  
**Index at report time:** ~6379 chunks / 935 files · CodeRankEmbed / fastembed  
**Related:**
- Locate-quality combo catalog → [`2026-09-11-scubiee-mcp-locate-quality-combo-feedback.md`](./2026-09-11-scubiee-mcp-locate-quality-combo-feedback.md)
- Infra reliability audit → [`2026-09-10-scubiee-mcp-reliability-issues.md`](./2026-09-10-scubiee-mcp-reliability-issues.md)

**Goal:** Run **many new-topic** map→pack (and expand when thin/skewed) probes **before** concluding, capture quality feedback, and record **warm-wait + latency** numbers so product work can prioritize the right fixes.

---

## What we did

### Method

1. Confirm `status` / `gate` (health only — not locate).
2. For each **new domain**, write a dense ~40+ token code-vocab query (symbols, `packages/…` paths, APIs, outcome verbs).
3. `map(k≈10–12)` → follow `suggested_seeds` into `pack_context(mode=lean)` with `seed_*` + `seed2_*` / `seed3_*` when multi-module.
4. If `thin=true` or seed2/seed3 missing from heatmap → `expand_context` or one `policy=broad` pack (no re-pack thrash).
5. Score by whether an agent could Native-Read top locs and answer/edit without Grep shotgun.
6. Topics deliberately **not** reused from earlier combo/smoke batteries (except one intentional `compress_mix` recheck).

### Batteries

| Batch | Sessions | Topics |
|-------|----------|--------|
| Practical 3 | `practical-q1-watchdog`, `practical-q2-compress`, `practical-q3-governor` | watchdog revive, `compress_mix`, `resolve_desired_tier` |
| Blind B1 | `blind-b1-*` | fair_schedule, doctor, query_router, session_store, accel, enrich |
| Blind B2 | `blind-b2-*` | root_probe, store_lock, hot_patch, upgrade, dirty_ledger, registration |
| Blind B3 | `blind-b3-*` | vectordb, connect/permissions, embed adapter, chunk/parse, MCP handlers, gate rules |
| Blind B4 | `blind-b4-*` | compress (recheck), work_session, freshness, cli_ui |
| Latency | in-process MCP wrappers `lat-bench*` | timed status/gate/map/pack/expand after warm |

**Total scored soft locates:** ~25 topics (+ expands / one broad escape).

Also earlier same-day context (not re-scored here): combo matrix, vague/salad diffs, pytest locate-quality suite (**28 passed**).

---

## Executive verdict

When the engine is **warm** (`warm_state=ready`, `soft_search_ready=true`), **dense code-vocab map→pack is usually strong (~7–9/10)**. Blind follow of every `suggested_seed` is **not** safe yet: leaf seeds, multi-seed heatmap honesty, and broad escape on stuck leaves still produce empty/wrong heatmaps.

| Bucket | Count (approx) | Examples |
|--------|----------------:|----------|
| Excellent (8–9) | ~12 | compress_mix, vectordb, root_probe, store_lock, dirty_ledger, upgrade, freshness, enrich, query_router |
| Usable (6–7) | ~7 | hot_patch, fair (seed2 rescue), watchdog, accel, embed, cli_ui, connect (after expand) |
| Weak / fail (2–5) | ~6 | session_store leaf, work_session multi-seed miss, MCP handlers leaf, gate pause skew, register primary miss, doctor skew |

**Overall blind locate product (warm):** ~7/10 — worth using for skilled agents; not “trust suggested_seed blindly.”

---

## Scoreboard (blind topics)

| Topic | Map | Pack / follow-up | Score |
|--------|-----|------------------|------:|
| compress_mix / TurboQuant | strong | both seeds hot + helpers | 9 |
| vectordb `FaissCollection` | strong | class + `upsert_vectors` | 9 |
| root_probe / merkle | strong | probe + merkle helpers | 9 |
| store_write_lock | strong | lock + `atomic_write_text` | 9 |
| dirty_ledger / sync | strong | ledger + status + derive | 9 |
| upgrade daemon bounce | strong | `daemon_version` + `ensure_daemon_after_upgrade` | 9 |
| freshness `check_freshness` | strong | check + merkle (+ cold IndexManager) | 9 |
| enrich / EnrichedChunk | strong | dense product surface | 9 |
| query_router | strong | `query_state` + path likeness | 9 |
| hot_patch | strong | good; giant `extract` noise | 7 |
| FairEmbedScheduler | wrong primary `Handler` once | seed2 recovered hold/acquire | 7 |
| watchdog revive | strong dual suggest | daemon-heavy heatmap; loop needed Native-Read | 7 |
| accel `load_accel` | OK | small but on-target | 7 |
| embed adapter | OK | RM-heavy; seeds present | 7 |
| cli_ui `SetupProgress` | OK | file-local; seed2 dropped | 7 |
| connect permissions | strong | seed2 absent until expand → `write_project_tool_surface` | 6 |
| chunk/parse | suggests giant `extract` | adapter OK; no enrich cards | 6 |
| doctor diagnose | OK | heat skewed (home/accel); `doctor_repo` cold | 5 |
| register_project | strong | primary absent from heatmap; expand → `cmd_register` | 5 |
| gate rules write | correct seed | `pause_resume` / `read_id` hot; primary cold | 4 |
| MCP tool handlers | leaf `locate_tool_names` | permissions-only; seed2 `run_ship_check` dropped | 3 |
| session_store spans | leaf `savings_defaults` | thin; broad `escape_helped:false`; expand missed `put_span` | 3 |
| work_session `pin` | map→`pin` | **neither `pin` nor `put_span` in heatmap** (isolation helpers only; agreement_nodes=25) | 2 |

---

## Feedback that will improve the product most

### P0 — MULTI-SEED-HEATMAP-HONESTY

**Symptom:** `multi_seed_v1` reports large `agreement_nodes` while seed2/seed3 (or even seed1) never appear in the returned heatmap.

**Blind repros:**
1. `work_session::pin` + `session_store::put_span` → heatmap only `session_isolation.*` (score 2).
2. `register_project` + `registry_lock` + `migrate_project` → heatmap dominated by `project_id` helpers; primary missing.
3. Connect: `apply_permissions…` + `write_project_tool_surface` → seed2 missing until expand.
4. Watchdog dual: `agreement_nodes=127` but loop body barely present.

**Ask:** Guarantee each accepted seed id is represented in top-k heat **or** return `seed_coverage: {seed_id: bool}` + `thin` if any required seed is uncovered. Do not advertise high agreement when coverage is seed1-only.

### P0 — LEAF-SEED + BROAD-ESCAPE STILL STUCK

**Symptom:** Suggested primary is a leaf/helper (`savings_defaults`, `locate_tool_names`, `daemon_version`, giant `extract`). Lean pack thin/file-local. `policy=broad` sometimes no-ops (`escape_helped:false`) and can be **very slow**.

**Blind repros:**
- session_store → `savings_defaults` → thin; broad still thin, `escape_helped:false`.
- MCP handlers → `locate_tool_names` → permissions constants only.
- Latency bench: same broad-on-leaf pack took **~48.1s** and still failed (see timings).

**Ask:** Prefer public class/entrypoint over leaf helpers in `suggested_seeds`. Broad escape must reseed to a denser public symbol **or** fail fast with `escape_helped:false` without a 45s+ burn.

### P1 — HEAT VS ASK (WRONG HOT CLUSTER)

**Symptom:** Correct seed chosen, but heatmap promotes unrelated hot helpers.

**Blind repros:**
- Gate: seed `write_project_gate_rules` but hot rows are `pause_resume.is_paused` / `read_id_file`.
- Doctor: multi-seed OK, heat skewed to home/accel/preflight.
- Fair: map once suggested `server.Handler` as primary (seed2 saved it).

**Ask:** Stronger query↔symbol affinity for heat ranking; demote pause/home helpers unless query mentions them.

### P1 — EXPAND IS THE RECOVERY PATH (MAKE IT FIRST-CLASS)

Expand often recovered what pack missed (`write_project_tool_surface`, `cmd_register`, merge_* permissions). Expand from `savings_defaults` did **not** find `put_span`/`recall` — graph/query still blind there.

**Ask:** When pack `seed_coverage` incomplete, MCP `next` should prefer expand with the missing seed ids. Expand ranking should boost same-file public siblings of a leaf seed (`put_span` next to `savings_defaults`).

### P2 — MAP POLLUTION / INCOMPLETE SEEDS

Docs, tests, scripts, fixtures still rank into map cards. `faiss_store.FaissCollection` marked `seed_incomplete` — good signal; agents still get told to pass it as seed2.

**Ask:** Soft-demote non-`packages/` for suggested_seeds; never recommend `seed_incomplete` in `next` seed2/seed3 slots.

### P2 — GIANT LOCS

`packages/graphify/extract.py::extract` locs ~4522–5664 burn agent context if Read blindly.

**Ask:** Cap suggested loc span / prefer adapter entrypoints (`graphify_to_repo_ir`) when extract is mega-function.

---

## Engine warm / wait issues faced

### During this chat (observed)

| Event | What happened | Agent impact |
|-------|---------------|--------------|
| MCP namespace `loading` / missing | Early smoke + mid combo battery | Waited ~3–8s, rediscovered tools; once “MCP dropped — reconnecting” |
| `Connection closed` / stdio flap | Mid combo (earlier same day) | Had to pause live probes; fell back to pytest |
| Engine `warming` / `soft_search_ready=false` | Before practical blind 3 | Explicit wait ~15s → then `agent_ready=yes`; messaging was usable (not thrash) |
| `agent_ready=stale` while locate allowed | Smoke + end-of-report status | Locate still worked; sync lag on dirty paths (e.g. `.zed/…`) |
| Background keeper sync | status full: last_probe ~8.1s, last_sync ~11.1s | Did **not** block map/pack once warm; `syncing_stale_ok` |
| Cold start after engine restart (prior audit) | `warm_state=indexing`, map fail ~15.8s | CLI map immediately after start failed — known |

### Blind batch itself (B1–B4)

Once warm, **no multi-minute warm waits** between topics. Parallel map batches and packs returned in normal agent-turn times. Failures were **quality** (wrong heat), not “engine not ready.”

### Latency / cost surprises

1. **`policy=broad` on a stuck leaf** was the only locate call that felt like a warm/wait hang in the timed bench (~48s) — product should treat this as P0 latency, not only quality.
2. Multi-seed lean packs were **fast** (~90–100ms) when the graph was already warm.
3. First `status` after process attach ~2s; subsequent `gate` ~6ms.

---

## Timings

### A) Live MCP wrapper bench (2026-09-11, engine already warm)

Measured via in-process `create_mcp` + same tool fns the ship surface exposes (not wall-clock of Cursor IPC). Warm: `warm_state=ready`, `agent_ready=yes`.

| Call | ms | Notes |
|---------:|-------|
| `status` (summary) | **1967** | First attach-ish |
| `gate` | **6** | Cheap |
| `map` (fair_schedule) | **4196** | seed `FairEmbedScheduler`, 8 cards |
| `map` (session_store dense) | **2677** | seed correctly `put_span` when query named it |
| `map` (gate rules) | **3352** | seed `write_project_gate_rules` |
| `pack_context` lean single (`compress_mix`) | **439** | thin=false, n=9 |
| `pack_context` lean dual (`store_lock`) | **102** | `multi_seed_v1`, n=7 |
| `pack_context` lean triple (`DirtyLedger`) | **91** | n=5 |
| `pack_context` lean+**broad** leaf (`savings_defaults`) | **48066** | thin=true, `escape_helped=false`, n=3 — **outlier** |
| `expand_context` (permissions → tool surface) | **377** | delta=8 |

**Warm-path takeaway:** map ≈ **2.5–4.5s**; lean pack ≈ **0.1–0.5s**; expand ≈ **0.4s**; broad-on-leaf ≈ **48s** and still useless.

### B) Prior MCP reliability audit (2026-09-10, colder / warming)

From [`2026-09-10-scubiee-mcp-reliability-probes.json`](./2026-09-10-scubiee-mcp-reliability-probes.json):

| Probe | ms |
|-------|---:|
| http `/health` | 607 |
| mcp initialize | 2482 |
| tools/list | 4 |
| status (warming signals) | 17944 |
| map happy | 17986 |
| pack lean happy | 24132 |
| expand_context | 64 |
| CLI map right after engine start (indexing) | 15780 (failed) |

**Cold/warming takeaway:** map/pack can sit in the **~18–24s** range while soft search is still coming up — agents should `status` once and wait, not remap-spam.

### C) Keeper / sync (status full at report write)

| Signal | ms / state |
|--------|------------|
| last_probe | ~8105 ms · dirty 1 path |
| last_sync | ~11115 ms · incremental |
| `sync_status` | syncing |
| `locate.state` | ready (`syncing_stale_ok`) |
| `agent_ready` | stale (locate still OK) |

---

## What worked well (keep)

- Dense queries + `suggested_seeds` plural + seed2/seed3 wiring.
- Honest `thin=true` + “do not re-pack” guidance.
- Dual/triple packs when coverage is real (`compress_mix`, `store_lock`, `dirty_ledger`, `vectordb`, `freshness`).
- Expand as a useful cross-module hop for connect/register.
- Status notes during warming were actionable (`should_retry`, agent_ready note) — better than silent failure.
- Pytest locate-quality suite green (28) — good regression floor for the fixes above.

---

## Recommended fix order

1. **Seed coverage honesty** on multi_seed heatmaps (+ surface `seed_coverage` / force thin).
2. **Leaf demotion** in suggested_seeds + **fast-fail broad** (hard budget, e.g. ≤2–3s or skip).
3. **Same-file public sibling boost** on expand from leaf seeds (`savings_defaults` → `put_span`/`recall`).
4. **Heat affinity** so pause/home/docs don’t outrank the accepted seed on gate/doctor asks.
5. Emit **`elapsed_ms`** on every map/pack/expand/status response (agents currently guess from wall clock).

---

## Appendix — session ids for replay

`practical-q1-watchdog`, `practical-q2-compress`, `practical-q3-governor`, `blind-b1-fair`, `blind-b1-doctor`, `blind-b1-router`, `blind-b1-sessionstore`, `blind-b1-sessionstore-broad`, `blind-b1-accel`, `blind-b1-enrich`, `blind-b2-rootprobe`, `blind-b2-storelock`, `blind-b2-hotpatch`, `blind-b2-upgrade`, `blind-b2-dirty`, `blind-b2-register`, `blind-b3-vectordb`, `blind-b3-connect`, `blind-b3-embed`, `blind-b3-chunk`, `blind-b3-mcp`, `blind-b3-gate`, `blind-b4-compress`, `blind-b4-worksession`, `blind-b4-freshness`, `blind-b4-cliui`, `blind-latency-probe`, `lat-bench*`.
