# Scubiee MCP locate-quality combo feedback

**Date:** 2026-09-11  
**Host:** Cursor MCP `project-0-context-engine-scubiee`  
**Repo / project:** `C:\Users\usman\Downloads\context-engine` / `ce_2f9c289d2a885432f240969ea2889532`  
**Related:** infra reliability audit → [`2026-09-10-scubiee-mcp-reliability-issues.md`](./2026-09-10-scubiee-mcp-reliability-issues.md)

**Goal:** One place to fix **locate quality** (map / pack / expand / collect / seed / escape) end-to-end. Infra flaps are out of scope here except where they blocked a probe.

---

## Executive summary

When the engine is warm (`agent_ready=yes`), **dense code-vocab map → pack is strong (~8/10)**. Agents still fail on a recurring set of **seed / ranking / escape / graph** bugs that are reproducible across many domains.

| Surface | Score (warm) | Trend across this chat’s batteries |
|---------|-------------:|------------------------------------|
| Dense map | 8–8.5 | Stable |
| Dense pack (good seed) | 8 | Stable |
| Suggested-seed picker | 4–6 | Improved (`kind`, skip `_`, null on fixture-only) but still picks leaves |
| Thin detection | 9 | Honest `thin=true` |
| `policy=broad` escape | 5 | Helps some leaves; fails or no-ops on others |
| Expand callers | 5–7 | Was empty → fixed plumbing; ranking mixed → now often includes true callers |
| Expand callees / effects / broad | 4–6 | Non-empty but noisy / already_in_pack heavy |
| Collect / include_bodies | 7 | Works; partial id fill |
| Vague / salad / name collision | 2–4 | Still the main agent footgun |
| Dual-seed pack | 8 | Works when both seeds valid; bad args hard-fail |

**Overall locate product (warm):** ~7/10 — shippable for skilled agents; not yet “follow suggested_seed blindly.”

---

## Test batteries covered

| Battery | Sessions / focus | Outcome |
|---------|------------------|---------|
| Vector-DB explain | first chat beat | Thin pack from bad `seed_line=1` / `_` seed |
| Smoke | health + map/pack/collect | Collect fixed; expand weak |
| Thorough 7 (embed/conductor/lifecycle/session/vague/turbo/salad) | same queries twice | Broad escape + expand plumbing improved on rerun |
| Diff 7 (graphify/wipe/capability/merkle/vague-index/semantic/daemon-salad) | new domains | Wipe excellent; vague-index + blob seed fail |
| **Combo matrix (this doc)** | rules / dense / seed-policy / vague-auth / project_id / resources / dual-seed / bodies / callers | Issue catalog below |

### Combo matrix (2026-09-11)

| ID | Query class | Suggested seed | Pack | Escape / expand | Notes |
|----|-------------|----------------|------|-----------------|-------|
| A rules | dense | ✅ `write_project_gate_rules` | dense 12 | callers → `write_project_tool_surface`, `apply_connected_tools_to_repo` | Gold path |
| A3 bodies | dense + `include_bodies=1` | same | bodies + chain | — | Bodies work; only 1 body despite `max_bodies=2` |
| B dense | dense (FaissDenseAdapter) | ❌ `load_cache` | **thin** | broad → `DenseIndex` (`escape_helped`) — **still not** `FaissDenseAdapter` | Wrong module family |
| B4 dual | Conductor + MultiArch | dual seeds | dense; hops to MultiArch | — | **Fixes single-seed Conductor isolation** |
| B5 adapter | control `FaissDenseAdapter` | manual | **thin** (tiny class) | — | True target is thin by nature |
| C seed-policy | dense | ✅ `heatmap_is_thin` | thin (3 accessor helpers) | broad → **`escape_helped:false`** | Escape stuck on leaf cluster |
| D vague-auth | vague `"where is auth"` | **`null`** ✅ | fixture pack → `ok:false` seed not found | — | Correct refuse; no packages/ seed |
| E project_id | dense | ⚠️ `collection_name_for_project` | thin 1 | broad → `ProjectRef` still thin, `escape_helped:false` | Missed `resolve_project` |
| F resources | dense | ❌ `keeper_tick` | dense but sync/merkle-heavy | effects → `incremental_sync` | Asked RM; got keeper |
| F2 control | `resources.py` line=1 | → `ResourceManager` | dense + `wait_for_capacity` | — | Right file works |
| G embed callers | dense | `embed_many` | dense | callers → **`index_repo`, `incremental_sync` first** | Caller ranking improved |

---

## Severity legend

| Sev | Meaning |
|-----|---------|
| **P0** | Agents following the ladder get wrong/empty context and cannot recover with advertised tools |
| **P1** | Frequent wrong seed / thin pack; recoverable if agent is smart |
| **P2** | Noise, token waste, polish, inconsistent signals |

---

## Issue catalog (fix in one pass)

### P0 — VAGUE-NAME-COLLISION-SEED

**Symptom:** Vague queries bind to UI hooks / fixtures / literal names instead of product entrypoints.

**Repros:**
1. `"how does indexing work"` → suggested `cli_ui.InitProgress.indexing` (score ~550); pack stays in progress-bar UI.
2. `"how does session work"` → e2e `session()` #1 (score ~430); product `work_session` buried.
3. Broad escape from UI seed → `escape_helped:false` + **empty heatmap** (diff battery).

**Why it hurts:** Blind ladder = wrong subsystem; broad escape may make it worse.

**Acceptance:**
- Vague “how does X work” must prefer `packages/**` public entrypoints (`index_repo`, `work_session`, …) over CLI UI / scripts / fixtures.
- If only fixtures match, `suggested_seed=null` (already done for auth) + explicit next: “enrich query / Grep.”
- Broad on a thin UI leaf must either reseed to product entrypoint or keep prior dense cards — never empty heatmap.

---

### P0 — BROAD-ESCAPE-INCONSISTENT

**Symptom:** `policy=broad` sometimes densifies (`escape_helped:true`), sometimes no-ops, sometimes empties.

**Repros (this chat):**
| Seed | Broad result |
|------|----------------|
| TurboQuant `to_float32` | ✅ reseed `CompressedEmbeddingStore`, thin→dense |
| capability `blob` | ✅ reseed `CapabilityCard` (+ BM25) — still misses `locate` |
| dense `load_cache` | ✅ reseed `DenseIndex` — wrong target vs FaissDenseAdapter |
| `heatmap_is_thin` | ❌ `escape_helped:false`, still thin |
| `collection_name_for_project` | ❌ → `ProjectRef` still thin |
| `cli_ui.indexing` | ❌ empty heatmap |

**Acceptance:**
- Broad must define a measurable densify contract (e.g. useful cards ≥ N, or hop to class/entrypoint enclosing the leaf).
- Always emit `escape_helped` + `escape.from/to` honestly.
- Never return empty heatmap after a non-empty lean pack.

---

### P1 — SUGGESTED-SEED-PICKS-LEAVES

**Symptom:** Map ranks the right *file* but suggests a trivial / peripheral symbol.

**Repros:**
- Capability: map has `promotable_cards` #1 → suggests `CapabilityCard.blob` → thin pack.
- FaissDenseAdapter ask: suggests `dense_index.load_cache` (not `searcher.FaissDenseAdapter`).
- Resources ask: suggests `keeper_tick` while `resources.py` module card is present.
- Project id ask: suggests `collection_name_for_project` not `resolve_project`.
- Earlier: `repo_key`, `from_dict`, empty module symbols (empty-symbol case improved).

**Already improved:** `kind` field; skip `_` helpers; prefer class over private; `suggested_seed=null` when no packages/ seed.

**Acceptance:**
- Prefer public **class / orchestrator / CLI cmd / `run_*`** over accessors (`blob`, `load_cache`, `indexing` progress).
- Prefer query-named symbols/paths (`FaissDenseAdapter`, `resources.py`, `resolve_project`).
- Never suggest fixture/script symbols for product asks.
- Unit matrix: one test per leaf class (accessor, progress hook, cache loader, fixture auth).

---

### P1 — PACK-FILE-LOCAL / MISSING-CROSS-MODULE

**Symptom:** Pack stays inside one file/module while map already knew the cross-module cards.

**Repros:**
- Conductor-only pack → 4 cards; misses MultiArch (dual-seed fixes if agent knows to pass seed2).
- Session `pin` pack → lock helpers dominate; `session_store` only on map.
- Keeper/freshness pack missed `hot_patch_texts` / `sync_loop` that map returned.
- Graphify pack flooded with extract helpers; enrich/RepoIR thin.

**Acceptance:**
- When map cards include other `packages/` files in top-k, pack should pull ≥1 cross-file hot card (or advertise `seed2` from map).
- Auto-suggest `seed2` in map `next` when top cards span ≥2 packages modules.

---

### P1 — EXPAND-DIRECTION-NOISE

**Symptom:** Expand is non-empty but returns siblings / scripts / already_in_pack instead of the asked direction.

**Repros:**
- callers(`embed_many`) earlier: Mac GPU helpers (fixed enough that `index_repo` now ranks #1 in combo G).
- callers sometimes empty (connect permissions historically).
- callees(`retrieve_conductor`): only already_in_pack.
- broad(thin turbo): only already_in_pack.
- effects(`keeper_tick`): useful `incremental_sync` + many already_in_pack.

**Acceptance:**
- callers: ≥1 true call-site in top-3 when static graph has edges (`index_repo` for `embed_many`; `cmd_wipe` for `wipe` — already good).
- Prefer packages/ over scripts/fixtures.
- Dedupe or demote `already_in_pack` below new deltas (or omit when `already_in_pack=true` unless `include_seen=1`).

---

### P1 — GIANT-LOC-SPANS

**Symptom:** Heatmap locs span entire classes (e.g. `MultiArchConductor` 75–1420, `ResourceManager` 81–416, `index_repo` 105–543).

**Why it hurts:** Violates lean Native-Read contract; agents re-read thousands of lines.

**Acceptance:**
- Prefer method-level cards for classes > ~80 lines.
- Cap reported loc window (e.g. signature + first N lines) with `expand`/`collect` for full body.

---

### P2 — HELPER-NOISE-IN-HEATMAP

**Symptom:** Hot/cold lists fill with `_load_json`, locks, `atomic_write_text`, tokenize, path helpers.

**Acceptance:**
- Downrank trivial accessors / pure path utils unless query names them.
- Keep ≥60% of top-5 hot cards “explain-useful” (orchestrators, public API, state transitions).

---

### P2 — COLLECT-PARTIAL-IDS

**Symptom:** `collect_hot_context(ids=a,b)` often returns 1 body; threshold=0 still skips some.

**Acceptance:**
- Honor explicit `ids=` fully up to `max_chars` / count.
- Clear error listing missing ids (not in session / not in index).

---

### P2 — DUAL-SEED-ARG-UX

**Symptom:** Invalid dual-seed (`seed_file=packages/pipeline` directory) → hard fail; seed2 ignored if seed1 invalid.

**Acceptance:**
- Validate paths; if seed1 invalid but seed2 valid, use seed2.
- Map should propose `seed2_file/symbol` when useful (Conductor + MultiArch).

---

### P2 — FIXTURES-SCRIPTS-IN-MAP-TOP

**Symptom:** Even with good queries, fixtures/scripts appear in top cards (trace-lab query.py, e2e session, bench scripts).

**Acceptance:**
- Default map demote `fixtures/`, `scripts/` unless query mentions them or `include_lab=1`.
- Keep tests demoted relative to packages/ for soft explain asks.

---

### P2 — MCP-CONNECTION-FLAP-DURING-EVAL

**Symptom:** Mid-session `Connection closed` / loading namespace (hit during this combo run).

**Overlap:** See reliability doc P0 connection issues.

**Acceptance:** Cursor tool calls should retry once on transport close; status should not require chat restart.

---

## What is working (do not regress)

1. Warm health: `agent_ready=yes`, soft search ready.
2. Dense map → pack on wipe, rules/GATE, merkle, semantic ensemble, embedder, lifecycle.
3. Thin detection + “do not re-pack” messaging.
4. `suggested_seed.kind`; skip private `_` helpers; null seed when only fixtures (auth).
5. Fixture seed pack rejected (`ok:false`) — good.
6. Broad reseed works for some leaves (TurboQuant class, DenseIndex, CapabilityCard).
7. Expand callers can return true call sites (`wipe`→`cmd_wipe`, `embed_many`→`index_repo`).
8. Dual-seed Conductor+MultiArch pulls MultiArch into heatmap.
9. `include_bodies=1` / collect return real code.
10. `escape_helped` / `already_in_pack` flags for agent reasoning.

---

## Fix plan (resolve once)

### Wave 1 — Stop wrong ladders (P0)

1. **Vague / collision seed policy** — package-first; demote UI progress hooks & literal `session`/`indexing` name hits; never empty after broad.
2. **Broad escape contract** — reseed to enclosing class / query-named symbol / map’s best packages card; densify or keep prior; always honest `escape_helped`.

### Wave 2 — Seed + pack topology (P1)

3. **Leaf demotion** — accessors / cache loaders / progress methods lose to orchestrators when query is explain/soft.
4. **Cross-module pack / seed2 suggestion** — map emits optional seed2; pack pulls ≥1 foreign packages card when map had them.
5. **Expand ranking** — true direction edges first; demote scripts + already_in_pack.

### Wave 3 — Lean readability (P2)

6. Giant loc split; helper noise downrank; collect honors all ids; dual-seed validation; fixture/script demotion.

### Regression suite (must-have tests)

| Test | Assert |
|------|--------|
| vague indexing | seed ∈ {`index_repo`, `indexer`, `cmd_index`} not `InitProgress.indexing` |
| vague session | seed ∈ `work_session` / `session_store` not e2e `session` |
| capability | seed ≠ `blob`; prefer `locate` / `promotable_cards` / `CapabilityIndex` |
| FaissDenseAdapter query | seed/file hits `searcher.FaissDenseAdapter` or engine wiring |
| resources query | seed under `resources.py` not `keeper_tick` |
| broad thin turbo | `escape_helped` densifies or keeps cards; never empty |
| broad thin UI indexing | reseeds to `index_repo` or `escape_helped:false` with non-empty prior |
| expand callers embed_many | top-3 includes `index_repo` |
| expand callers wipe | includes `cmd_wipe` |
| dual-seed conductor | heatmap includes MultiArch method cards |
| collect ids=a,b | returns both when in index |
| fixture-only map | `suggested_seed is null` |

---

## Agent guidance (until Wave 1–2 land)

1. Do **not** blindly trust suggested_seed if symbol looks like accessor/UI/cache (`blob`, `indexing`, `load_cache`, `repo_key`).
2. Prefer map’s highest **packages/** class/orchestrator card; use **seed2** when top cards span two modules.
3. On `thin=true`, try **broad once**; if `escape_helped:false` or empty, Native-Read map cards / Grep — do not remap thrash.
4. Prefer expand **callers** for “who calls this”; treat callees/broad as optional.
5. Use `include_bodies=1` or Native-Read locs; don’t rely on collect for multi-id.

---

## Appendix — aggregate scores across batteries

| Battery | Overall |
|---------|--------:|
| First vector-DB beat | ~4–5 |
| Post-update smoke | ~7–8 (good seed) |
| Thorough 7 (rerun) | ~7.5 |
| Diff 7 | ~6.5–7 |
| Combo matrix | ~7 (gold paths 9; vague/leaf 2–4) |

**Ship gate recommendation:** Wave 1 + regression table green before calling locate “follow the ladder blindly.”
