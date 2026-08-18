# CE Live Reindexing System — Final Design

**Date:** 2026-08-16  
**Status:** **LOCKED for implementation** (product contract)  
**Folder:** [`docs/reindexing/`](./)

**Supersedes as policy:** exploratory menus in  
[index-freshness-agent-trajectory.md](./index-freshness-agent-trajectory.md) and  
[agent-write-patterns-and-channel-conflicts.md](./agent-write-patterns-and-channel-conflicts.md)  
(those remain useful as research appendices; this doc is the source of truth).

**Related code today:** `packages/pipeline/sync_loop.py`, `incremental.py`, `root_probe.py`,  
`engine.py` (hot-patch / publish), `embedder.py`, Graphify `build_merge` / AST cache.

---

## 1. Goal

When agents are **forced to locate via CE**, the index must be:

1. **Fresh enough** that code the agent just wrote is findable within ~1–2 seconds of a quiet save.  
2. **Stable enough** that an active `map` / `search` / `focus` streak does not reshuffle mid-thought (token thrash).  
3. **Cheap enough** that normal agent dirty sets (≈5–20 chunks) never feel like “reindexing the repo.”

**Non-goal:** full-corpus re-embed on a timer. Full index remains cold-start / repair / branch-storm only.

---

## 2. Measured performance (design constraints)

Hardware path locked for product: **1× warm `nomic-ai/CodeRankEmbed`**, FastEmbed, **DirectML**, **`batch_size=16`**.  
Do **not** ship multi-model concurrent Nomic workers on DML (3+ copies crash; 2 is flaky and only ~1.4× faster).

| Workload | Embed-only (measured) | Design implication |
|----------|----------------------:|--------------------|
| 5 chunks | ~0.22–0.24 s | Instant after debounce |
| 10 chunks | ~0.34–0.39 s | Instant |
| ~15–20 chunks (typical sync dirty) | ~0.5–0.8 s | “Every edit very fresh” is viable |
| 100 chunks | ~3.5 s | Still fine; rare for one quiet window |
| Full frontend-mcp ~3806 chunks | **~118 s (~2 min)** | Never on the live path |
| Clean root probe | tens of ms | Timer backup stays cheap |
| Graph patch (changed files only) | typically sub-second–~1–2 s | Structural live before dense |

**Assumption (product):** agent-driven sync dirty sets stay ≤ ~20 chunks almost always. Larger → storm path (§7).

---

## 3. Current system (as-built) vs target

| Layer | Today | Target |
|-------|-------|--------|
| Trigger | Keeper every **5 min** + `.sync-trigger` | **Primary:** file-change / write debounce 1–2 s; **backup:** 4–5 min probe; session-end drain |
| Work unit | `incremental_sync` on dirty merkle set | Same core; always bounded + coalesced |
| Graph | `patch_and_save_graph` / replace by `source_file` | Unchanged algorithm; run **eager** on debounce fire |
| Embed | Re-embed changed chunks, **1 model** | Unchanged; fire for small dirty sets immediately after extract |
| Search freshness | Hot-patch BM25; `publish_engine` after refresh | Formal **dirty ledger + overlay**; **process ≠ publish** |
| Generation | Bump on refresh | Freeze publish during locate streak; promote on quiet |

We are not inventing a new indexer. We are **retargeting triggers and publication policy** around the existing Merkle → extract → patch → embed → FAISS path.

---

## 4. Architecture overview

```text
                    ┌─────────────────────────────────────┐
                    │           Triggers                   │
                    │  file watch / save / Edit tool       │
                    │  merkle probe (4–5 min)              │
                    │  session end / MCP disconnect        │
                    └──────────────┬──────────────────────┘
                                   ▼
                         dirty_set (ledger)
                                   │
                         debounce 1–2 s
                         (reset per path on rewrite)
                                   ▼
              ┌────────────────────┴────────────────────┐
              │         SyncWorker (single flight)       │
              │  extract dirty files (AST cache hits OK) │
              │  graph patch + prune removals            │
              │  BM25 / disk overlay update              │
              │  embed ≤N chunks (1 model, batch 16)     │
              │  FAISS upsert for those ids              │
              └────────────────────┬────────────────────┘
                                   ▼
                    ready_overlay / pending_publish
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                                         ▼
     locate_streak active?                      quiet / idle / streak end
              │                                         │
              ▼                                         ▼
     keep published generation                 promote → publish_engine()
     (queries merge overlay)                   bump generation once
```

### Two clocks (mandatory)

| Clock | Meaning |
|-------|---------|
| **Process clock** | Disk → extract → graph → BM25 → embed → vectors ready in overlay |
| **Publish clock** | Overlay becomes the **published** search generation agents “see” as stable ranks |

Live CE = fast process clock + careful publish clock.

### Truth layers (mandatory vocabulary)

| Layer | Meaning | Query rule |
|-------|---------|------------|
| **Disk** | Absolute source-of-truth bytes on the filesystem | `focus` on a dirty path reads disk |
| **Overlay** | Current searchable truth: dirty-file graph/BM25/dense data already processed but not globally promoted | Merge it into results; prefer it over stale data for that path |
| **Published generation** | Stable retrieval snapshot for a coherent locate streak | Do not reshuffle it mid-streak |

`published` is **not** the definition of freshness. A path is fresh once its
overlay is searchable; promotion only controls stable global ranking.

---

## 5. Dirty ledger

First-class in-memory (+ optional persist) structure — not an informal side effect.

Per path:

| Field | Values / role |
|-------|----------------|
| `path` | Repo-relative |
| `content_hash` / mtime | Identity |
| `state` | `queued` → `extracting` → `graph_ready` → `bm25_ready` → `dense_pending` → `dense_ready` → `published` |
| `reason` | `write` \| `probe` \| `session_end` \| `external` |
| `chunk_estimate` | For cap decisions |
| `session_authored` | Touched by agent Edit this session (boost) |

**Queries / ranking while dirty:**

1. `focus` / span open on dirty path → **always disk** (invalidate stale handles for that path only).  
2. Soft `map` / `search`: prefer **BM25 + graph overlay + session-authored boost** for dirty paths; **demote stale dense** for those paths until `dense_ready`.  
3. Same path appearing twice (fresh BM25 + stale dense) → keep fresher; tag `freshness=disk|overlay|published`.
4. A `ready_overlay` path is reported as fresh even when the published
   generation is deliberately frozen.

---

## 6. Primary path — continuous per-edit sync

### 6.1 Trigger

On filesystem mtime/hash change or host write signal (IDE watcher → existing `.sync-trigger` or native watch):

1. Add path(s) to `dirty_set`.  
2. Start a **1500 ms** debounce timer (**per path** coalesce; global
   single-flight worker).  
3. If path rewrites during its debounce or while it is synchronising, extend
   that path’s quiet window to **2500 ms** (cap) and queue exactly one follow-up
   pass for its newest content hash.

**Default debounce:** 1500 ms first-write / 2500 ms rewrite-burst
(configurable `CTX_SYNC_DEBOUNCE_MS` and
`CTX_SYNC_REWRITE_DEBOUNCE_MS`, clamp 500–5000).

### 6.2 On debounce fire (normal agent edit)

Assume dirty set maps to **≤ ~20 chunks** (typical):

1. Acquire sync lock (skip/queue if already syncing — coalesce into next run).  
2. ResourceManager gate (`sync` / `embed`); if deferred, keep dirty and retry.  
3. **Extract** only dirty files (Graphify AST cache for unchanged).  
4. **Graph patch** (`build_merge` / `patch_and_save_graph`) + **prune** removed files.  
5. Update **BM25 / disk overlay** immediately → mark `bm25_ready` / `graph_ready`.  
6. **Embed** changed chunks with **one** warm model, batch 16.  
7. Upsert vectors; mark `dense_ready`.  
8. **Publish policy (§8)** — may promote now or wait for streak end.

**Target SLA (p50, warm model, ≤20 chunks):**

| Milestone | Target |
|-----------|--------:|
| `save → graph+BM25 searchable` | ≤ **1.5–2.5 s** (incl. debounce) |
| `save → dense searchable` | ≤ **2–3.5 s** (incl. debounce) |
| `save → published generation` | ≤ **same**, or delayed until locate quiet |

### 6.3 Why “every edit very fresh” is correct here

Agent sync is **not** full reindex. Even a “big” agent turn usually dirties a handful of files → **~15–20 chunks**. At ~33 chunks/s embed, that is sub-second embed after quiet. The product promise is:

> **After you stop typing/saving for ~1.5 s, CE is live again.**

Session-end and 5‑minute keeper become **safety nets**, not the freshness engine.

---

## 7. Storm / large-drift path

If after coalesce:

- dirty **files** > `CTX_SYNC_MAX_FILES` (default **40**), or  
- estimated **chunks** > `CTX_SYNC_MAX_CHUNKS` (default **100**), or  
- freshness strategy says `full` (≥50% corpus / large checkout),

then:

1. Do **not** claim live SLA.  
2. Set status `needs_full` or `catchup_chunked`.  
3. Prefer **chunked incremental** batches under the caps, or require explicit full index.  
4. Keep `CTX_ALLOW_BG_FULL=0` by default (unchanged).

Branch switches / format-all are storms; agent ApplyPatch loops are not.

---

## 8. Publish vs process (locate-streak protection)

### 8.1 Locate streak

**Initial v1 heuristic:** active if any CE locate tool (`map` / `search` /
`focus` / phase equivalents) ran within the last `CTX_LOCATE_STREAK_MS`
(default **8000**).

The timer is deliberately **tunable, not theoretical**. Record streak duration,
publish delay, and whether the next tool is another locate, Edit/Write, shell
verification, or idle. Tune the threshold from this telemetry. A later version
may end a streak directly on a non-locate tool event; v1 must not block on host
event fidelity.

While active:

- SyncWorker **may still process** dirty files into overlay.  
- **Do not** call `publish_engine()` / bump global generation in a way that reshuffles the stable result list mid-streak.  
- Tool responses may include a one-line hint: `overlay_pending: N` (optional, keep short).

When streak ends **or** quiet debounce after last locate:

- Promote overlay → published; single generation bump.

### 8.2 Session memory

- On publish: invalidate handles **only for dirty paths**, not the whole session.  
- Follow-ups stay memory-first (`workspace` / already-shown); don’t force re-map because of sync.

---

## 9. Backup paths

| Trigger | Behavior |
|---------|----------|
| **4–5 min probe** | Root probe; if dirty and no active sync, drain `dirty_set` with same SyncWorker |
| **Session end / MCP disconnect / process exit** | `final_check`: process remaining dirty + **force publish** |
| **Manual / doctor** | `ctx sync` / repair rebuild |

Default interval may move from 300000 → **240000** ms when implementing; probe remains no-op when clean.

---

## 10. Embedding / graph product rules

1. **One** warm CodeRankEmbed instance per engine process.  
2. **`batch_size=16`** (accel profile); ResourceManager may shrink under pressure, never spawn extra model copies.  
3. Graph updates are **patches**, never full-repo AST on the live path.  
4. Missing `graph.json` → rebuild from AST **cache** if possible before full extract.  
5. Deletes: always prune graph + drop vectors for that `source_file`.

---

## 11. Agent-visible status contract

`status` (and optional search card fields) MUST be able to report:

| State | Meaning |
|-------|---------|
| `ready` | Published gen matches disk (dirty empty) |
| `syncing` | SyncWorker in flight |
| `overlay_ready` | Dirty processed; publish held for streak |
| `dense_pending` | Graph/BM25 ready; embed not done |
| `deferred` | Resource pressure |
| `needs_full` / `catchup` | Storm path |
| `error` | Last sync failed (include short reason) |

Never block `map`/`search` for minutes waiting on embed; serve overlay / hot-patch instead.

---

## 12. KPIs (ship with the feature)

| KPI | Definition | Gate |
|-----|------------|------|
| `save_to_overlay_lexical_ms` | Debounce start → overlay BM25/graph hit for new symbol | p50 ≤ 2500 ms |
| `save_to_overlay_semantic_ms` | Debounce start → overlay dense hit | p50 ≤ 3500 ms |
| `save_to_published_ms` | Debounce start → generation promoted | p50 ≤ 3500 ms when no streak |
| `locate_streak_ms` | Last-locate → promotion delay, grouped by next tool event | Tune `CTX_LOCATE_STREAK_MS` from real sessions |
| `locate_thrash` | Unique map/search before first edit on sealed “edit then find” task | no regression vs frozen-gen baseline |
| `sync_thrash_rate` | Syncs per path / minute under multi-edit | ≪ 1 without debounce (prove debounce works) |
| Concurrent DML models | Must remain **1** | regression test / config assert |

A/B task: sealed **add symbol → map/search own symbol within 5 s**, compare tokens vs session-end-only freshness.

---

## 13. Implementation sketch (modules)

No new “second indexer.” Extend:

| Module | Change |
|--------|--------|
| `sync_loop.py` / new `dirty_ledger.py` | Debounce queue, streak flag, overlay promote |
| Watcher | Prefer native watch or tighten `.sync-trigger` from IDE; per-path debounce |
| `incremental.py` | Already correct core; ensure prune + caps + return channel readiness |
| `engine.py` | Merge overlay in search; demote stale dense; generation fence |
| `session_store.py` | Path-scoped handle invalidation |
| `ce_service.py` | Wire on_refresh only on **publish**, not every process tick |
| Config | `CTX_SYNC_DEBOUNCE_MS`, `CTX_LOCATE_STREAK_MS`, `CTX_SYNC_MAX_FILES`, `CTX_SYNC_MAX_CHUNKS` |

---

## 14. Explicit non-goals / anti-patterns

- Full re-embed every 4–5 minutes.  
- Un-debounced sync on every keystroke / ApplyPatch.  
- Multi-copy Nomic “workers” for throughput.  
- Blocking agents on dense completion.  
- Invalidating entire session memory on every publish.  
- Treating branch-wide storms as “20 chunk live sync.”

---

## 15. One-paragraph product contract

> Context Engine keeps a **live incremental index**: after each quiet save (~1.5 s), it re-extracts and graph-patches only changed files, refreshes BM25 from disk, and re-embeds the small dirty chunk set with **one** warm CodeRankEmbed (batch 16). Typical agent edits (≤~20 chunks) become structurally and semantically searchable in a few seconds. While the agent is mid-locate, CE may process in the background but **does not reshuffle the published generation** until the streak goes quiet. Five-minute probes and session-end drains are backups; full corpus reindex is repair-only.

---

## 16. Decision log

| Decision | Choice |
|----------|--------|
| Primary freshness | Debounced continuous sync on file change |
| Debounce | 1–2 s (default 1500 ms) |
| Typical dirty assumption | ≤ ~15–20 chunks |
| Embed workers | **1** model |
| Batch | **16** |
| Graph | Eager patch on sync fire |
| Dense | Eager for small dirty sets; never block tools |
| Publish | Separated; freeze during locate streak |
| Timer | Backup probe 4–5 min |
| Session end | Force drain + publish |
| Storm | Caps + chunked/full; no fake live SLA |

**Next step after approval of this doc:** implementation plan + A/B harness for `save→searchable` and sealed edit-then-find.
