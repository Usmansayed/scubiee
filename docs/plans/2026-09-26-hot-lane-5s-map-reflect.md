# Plan: 5-second map reflect (hot-lane sync) — for Kiro

**Author context date:** 2026-09-26  
**Repo:** `C:\Users\usman\Downloads\context-engine`  
**Project id:** `ce_c505c4e65dbe5e2063a6c1089fe4db4e`  
**Current installed product:** `0.3.130`  
**Target release after this work:** `0.3.131`  
**Engine:** `http://127.0.0.1:8765`  
**Logs:** `C:\Users\usman\.scubiee\engine.log`, `C:\Users\usman\.scubiee\watchdog.log`

This document is the full brief for implementing and proving a **≤ 5 second** path from “file saved / marked dirty” to “MCP `map` returns that path in cards / `hits[].file`”. Do not treat generation bumps or dirty `ok: true` as success.

---

## 0. Read these first (do not reinvent)

| Doc / code | Why |
|---|---|
| `docs/sync-issue-report-2026-09-25.md` | Why simulation ≠ live; chunk list vs search |
| `docs/sync-fix-worklog-0.3.128.md` | Chunk position vs durable FAISS id alignment |
| `docs/sync-fix-worklog-0.3.128.md` §7 open items | CPU embed floor, uncommitted drift |
| This plan | Latency + process survival (the remaining problem) |

**Already shipped (do not break):**

- **0.3.124** — named `force_files` skips full-repo freshness walk; small touch uses background memory budget.
- **0.3.125** — no publish on zero delta; log dirty sync errors; cold embedder defer (`CTX_SYNC_WAIT_FOR_EMBEDDER=1` set by `_start_keeper`).
- **0.3.126** — unchanged chunks keep ids; additions before deletions.
- **0.3.127** — mmap FAISS → own storage before add/delete (`_own_index_storage`).
- **0.3.128** — `FaissDenseAdapter(chunk_ids=…)`, `reconcile_vector_store`, merkle canonical keys, vectors-before-chunks write order, `dense_missing` on health.
- **0.3.129** — silence httpx INFO on MCP stderr (Cursor was closing the session).
- **0.3.130** — explicit save reasons sync **ahead of** a large `disk_poll` backlog (`_split_explicit_writes`).

**Correctness of “file eventually appears in map” already passed live on 0.3.130** (~102 s). This plan is about **making that ≤ 5 s** and **stopping the engine from dying mid-sync**.

---

## 1. Goal (non-negotiable)

### Pass criteria (all required)

After writing a **new** small `.py` file under `packages/pipeline/` and `POST /v1/dirty` with `reason=changed_file` (or `editor_save` / `probe_write` / `watch` / `write` / `after_kiro_write`):

1. Within **5.0 seconds** of the dirty accept returning:  
   - `/health` `chunks` has increased by the new file’s chunks, **or** the published binder’s searchable text list includes the path (if you switch to patch-publish, health must still reflect the new count).  
   - `POST /v1/search` with a unique token from the file returns that path in `hits[].file`.  
2. MCP `map` with a dense query naming that symbol returns the path as a **card** (ideally rank 1). Map **requires** `dense=true` / `D_channel_best` — BM25-only is **not** a pass.  
3. Engine **PID must not change** during the 5 s window (no restart / abort).  
4. Probe directory deleted afterward; dirty the deleted path again.

### Hard constraints (product)

- Do **not** change ranking algorithms: map stays `retrieve_D_channel_best`; pack stays `composite_v1` / `multi_seed_v1`.  
- Do **not** raise `CTX_AUTO_FULL_INDEX_CHUNKS` (10k).  
- Do **not** implement disk callers in product `context_trace.py` unless asked.  
- PowerShell: no `&&` (use `;`). Pytest: `-p no:logfire`.  
- Do not commit / push / print tokens unless the user asks.  
- Local install: `uv tool install --reinstall "C:\Users\usman\Downloads\context-engine"` after `scubiee halt`; then restore MCP pins (`restore_live_mcp_pins(force=True)`) because halt stubs `cmd /c exit 0`.  
- After reliability failure: unit tests alone are not enough; run a live probe and report timings + ok flags.

---

## 2. What “the drop” was (evidence)

Live probe on 0.3.130 (`packages/pipeline/sync_mcp_live130.py`):

| t | Observation |
|---|---|
| 0 | Dirty accept 344 ms, chunks 7681, gen 4 |
| ~4.7 s | `WinError 10054` — connection reset |
| ~9–40 s | `chunks=0`, `dense_embed_loading` — **new process**, cold |
| ~50 s | Engine back ready, gen 1, still 7681 |
| ~101.7 s | Search top = `sync_mcp_live130.py`, chunks 7685 |
| — | MCP map rank 1 for `mcp_sync_probe_3013` |

Engine log:

- Two `[sync] memory mode=background` lines, then  
  `--- start 2026-09-26 00:20:00 ---` (full restart).  
- Watchdog: `health fail … pid_alive=True src=lock` (health blocked while something held the process/engine lock during publish/load).

**Conclusion:** the process died or was force-restarted under concurrent sync + search. Dirty ledger survived, so the file eventually indexed after restart — that is **not** a 5 s pass.

### Root cause A — FAISS is not safe to mutate under readers

[Faiss wiki — Thread safety](https://github.com/facebookresearch/faiss/wiki/Threads-and-asynchronous-calls):

> Concurrent searches OK. Operations that **change** the index need mutual exclusion with search.

In `packages/pipeline/vectordb.py`:

- `FaissCollection.search` / `save` use `self._lock`.  
- `add`, `delete`, `compact`, `_own_index_storage` do **not** take that lock.  

Keeper thread can `add_with_ids` / `compact` while HTTP `/v1/search` (map) reads the same `IndexIDMap2`. That is undefined behavior → abort / 10054. Earlier `MaybeOwnedVector::resize` aborts are the same family.

### Root cause B — Publish rebuilds the entire binder

`ContextEngine._publish_runtime` (`ce_service.py` ~573):

```text
load_engine(repo, force_reload=True)  # rebuild BM25 + graph + dense for ALL ~7.6k chunks
runtime.engine = engine
runtime.generation += 1
compact_collection(...)  # may rewrite vectors again
```

Measured keeper lines on this machine:

- `upserted=4 removed=0 ms=23335` (~23 s for four chunks).  
- `no chunk delta … ms=7–9k` still burns the keeper.

HTTP search uses `skip_freshness=True` (`ce_service` ~1114), so map **only** sees what the last published binder contains. Until publish finishes (or the process dies), map cannot see the new file even if `chunks.jsonl` was written.

### Root cause C — Hot path still does heavy work

- Default debounce **1000 ms** (`CTX_DEBOUNCE_MS`).  
- Named upsert path may call `col.compact()` after delete (full rebuild).  
- CPU FastEmbed (DirectML missing on this machine) ≈ **1.7 s / chunk** warm.  
- Existing `hot_patch.py` only patches **BM25 texts** for already-indexed chunk rows; map **rejects** non-dense results (`locate._search_hits` → `dense_embed_loading`). So BM25 hot-patch **cannot** meet the map SLA by itself. Dense must land in the published binder within 5 s.

### Root cause D (mostly fixed)

Save starved behind bulk backlog → **0.3.130** `_split_explicit_writes`. Keep that; hot lane builds on it.

---

## 3. Target architecture (proven patterns)

Industry pattern (OpenLore watch mode, Faiss docs, shadow/alias swap designs):

1. **Never mutate the live search index without excluding readers** (lock or shadow+swap).  
2. **Atomic publish** — finish writers, then flip one pointer; do not rebuild 7k chunks for a 1-file save.  
3. **Short debounce + coalesce** for agent saves (150–400 ms), not 1 s + 9 s no-ops.  
4. **Priority lane** for explicit saves (already started in 0.3.130).  
5. **No full compact on every tiny upsert.**  
6. **Per-stage timings** in one log line.

### Hot lane vs bulk lane

| | Hot lane | Bulk / disk_poll |
|---|---|---|
| Trigger | `changed_file`, `editor_save`, `probe_write`, `watch`, `write`, `after_kiro_write` | `disk_poll`, backlog, bulk |
| Debounce | **200–300 ms** | keep current 1000 / 2000 |
| Batch | Prefer **the saved paths only** (0.3.130 already defers backlog) | slices as today |
| Vector write | add/delete under lock; **no compact** | compact OK when idle / bulk |
| Publish | **patch binder** (see §5) | full `load_engine` OK |
| SLA | **≤ 5 s to map-visible** | best-effort |

---

## 4. Budget for a 1-file hot save (must fit ≤ 5000 ms)

| Stage | Cap | Notes |
|---|---|---|
| Dirty accept | ≤ 300 ms | Already ~100–350 ms |
| Debounce (hot) | ≤ 300 ms | Override only for hot reasons |
| Parse + chunk | ≤ 200 ms | Named file only |
| Embed (warm) | ≤ 2000 ms | CPU floor ~1.7 s; GPU is better but not required for pass if cap met |
| Vector + chunk write | ≤ 400 ms | No compact; lock held briefly |
| Patch publish | ≤ 300 ms | No full `load_engine` |
| Headroom | rest | Queue must not wait on bulk |

If embedder is cold: defer (existing `CTX_SYNC_WAIT_FOR_EMBEDDER`) and **do not** count cold load against the 5 s SLA in the first attempt after engine start — but once `embedder_loaded=true`, the next dirty **must** meet 5 s. Document this in the test harness.

---

## 5. Implementation tasks (do in order)

### Task 1 — FAISS mutual exclusion (fixes the drop)

**File:** `packages/pipeline/vectordb.py`

- Take `self._lock` for the entire body of `add`, `delete`, `compact`, and `_own_index_storage` (or document that callers must already hold it — prefer locking inside the methods so every caller is safe).  
- Keep `search` / `save` under the same lock.  
- Goal: no concurrent `search` + `add_with_ids` / `remove_ids` / rebuild.

**Test:** unit test that starts a thread hammering `search` while `add`/`delete` runs; process must not abort; results may block but must not crash. Prefer a short stress under pytest (not optional).

### Task 2 — No compact on hot-lane named upsert

**File:** `packages/pipeline/incremental.py` (`_upsert_named_vectors`)

- After `col.delete`, do **not** call `col.compact()` when the sync is a hot-lane / named small touch (e.g. `force_files` and touch count ≤ live max, or a new flag `hot_lane=True`).  
- Tombstones + dead_ids already work with `FaissDenseAdapter` (0.3.128). Compact can run from idle / bulk / reconcile later.  
- Still call `save_collection` so disk matches memory.

### Task 3 — Hot debounce

**File:** `packages/pipeline/sync_loop.py` / `dirty_ledger.py`

- When `mark_dirty(..., reason=…)` is a hot reason, use `due_at = now + hot_debounce_ms` (default **250**, env `CTX_HOT_DEBOUNCE_MS`).  
- Do not slide rewrite debounce forever for the same path if state is already `queued` with a near due time (poll already avoids re-marking due paths — keep that).  
- Bulk / `disk_poll` keeps `DEFAULT_DEBOUNCE_MS` / rewrite.

### Task 4 — Patch publish (main latency win)

**File:** `packages/pipeline/ce_service.py` (`_publish_runtime` and/or a new helper)

Today every refresh does full `load_engine(force_reload=True)`. For hot-lane payloads where `chunks_upserted + chunks_removed` is small and `strategy` is incremental/named:

**Preferred behavior:**

1. Keep the existing `runtime.engine` object.  
2. Reload **only** what changed from store (or pass new `ChunkRecord`s in the payload from `incremental_sync`):  
   - Append/replace entries in `engine.chunks`, `engine.texts`, `engine.files`.  
   - Patch graph spans for touched files if cheap; if graph patch is hard, call existing `patch_and_save_graph` during sync (already there) and **rebuild only graph retriever for those spans** — avoid full graph file reparse of the whole repo if possible.  
   - Rebuild BM25 from the updated `texts` list **or** incremental BM25 if available; full BM25 over 7k docs in Python may still be too slow — measure. If BM25 rebuild alone exceeds ~200 ms, keep previous BM25 and accept dense-first for map (map is dense-gated anyway).  
   - Patch dense: extend/replace rows in `FaissDenseAdapter` for new chunk ids (re-read vectors for those ids from the collection under lock), or construct a new adapter from `col` + full `chunk_ids` list **without** re-embedding. Building the adapter matrix for 7k rows may be OK if it stays &lt;200–300 ms; profile.  
3. Bump `runtime.generation`, update health chunk count from `len(engine.texts)`.  
4. **Do not** call `compact_collection` on the hot path.  
5. Fall back to full `load_engine` if patch fails or delta is large (`> live_max_chunks` or bulk strategy).

**Important:** HTTP search uses `skip_freshness=True`, so the in-memory binder **must** be updated. Writing `chunks.jsonl` alone is not enough.

**Also:** `WarmSearchEngine.search` has a path that `clear_engines()` + full reload when store mtime moves and `skip_freshness=False`. HTTP map skips that. Keep skip_freshness behavior; fix the publish side.

### Task 5 — Stage timing log

**Files:** `incremental.py`, `sync_loop.py`

Extend the keeper line (or add one hot-lane line):

```text
[keeper] hot sync path=… accept_ms=… debounce_ms=… parse_ms=… embed_ms=… write_ms=… publish_ms=… total_ms=… upserted=… removed=… pid=…
```

Every stage must be measurable in the live test output.

### Task 6 — Version / release notes

- `pyproject.toml` → `0.3.131`  
- `packages/pipeline/upgrade_releases/v0_3_131.py` + register in `__init__.py`  
- Notes should mention: FAISS lock, hot debounce, no compact on hot upsert, patch publish, 5 s map SLA.

### Task 7 — Do **not** “fix” map by weakening dense

Map must stay `D_channel_best` / dense. Do not allow BM25-only map results to count as success. Existing `hot_patch_texts` can remain as a lexical assist for non-map search paths; it is **not** the 5 s solution for map.

**Bug note for implementer:** `hot_patch_texts` indexes `patched[c.id]` — chunk **position** in `texts` is `enumerate(chunks)`, not durable `c.id`. If you touch hot_patch, fix that to use position; do not expand scope unless needed.

---

## 6. Tests Kiro must add / run

### Unit / simulation

1. **FAISS lock stress** — concurrent search + add does not abort.  
2. **Hot debounce** — `changed_file` due within ~250 ms; `disk_poll` still ~1000 ms.  
3. **Explicit write ahead of bulk** — keep `test_explicit_write_is_synced_ahead_of_a_bulk_backlog`.  
4. **Named upsert without compact** — mock `col.compact` and assert it is **not** called on hot named delta; assert `add`/`save` are.  
5. **Patch publish** — given a fake runtime engine with N chunks, apply a 1-chunk delta; generation += 1; `len(texts)` += 1; `load_engine` must **not** be called (monkeypatch).

### Live (required before calling green)

Use / extend `scripts/live_sync_probe.py`:

- Register client (already does).  
- Wait until `embedder_loaded` (cold start exempt).  
- Record `pid` from health or OS.  
- Write unique `packages/pipeline/sync_live_<stamp>/f0.py`.  
- Dirty with `reason=changed_file` or `probe_write`.  
- Poll every 200–500 ms until **5.0 s** hard fail:  
  - `hits[].file` contains the path, **and**  
  - chunks increased (or binder reports new path), **and**  
  - same engine pid.  
- Also call MCP `map` once search passes (or in parallel after visible).  
- Cleanup probe + dirty delete.  
- Print stage timings from engine log tail.

Install recipe (Windows):

```text
scubiee halt
uv tool install --reinstall "C:\Users\usman\Downloads\context-engine"
# restore MCP pins (halt stubs cmd /c exit 0)
python -c "from pipeline.mcp_restore import restore_live_mcp_pins; print(restore_live_mcp_pins(project=r'C:\Users\usman\Downloads\context-engine', force=True))"
scubiee engine ensure .
python scripts/live_sync_probe.py .
```

User may need to **reload Scubiee MCP** in Cursor after pin restore.

Report in the reply:

- version, dirty_ms, total_ms_to_hit, chunk delta, map rank, pid_stable true/false, stage line from log.

---

## 7. Suggested code touch list

| Path | Change |
|---|---|
| `packages/pipeline/vectordb.py` | Lock `add`/`delete`/`compact`/`_own_index_storage` |
| `packages/pipeline/incremental.py` | Skip compact on hot named upsert; stage timings; optional hot flag |
| `packages/pipeline/sync_loop.py` | Hot debounce; pass hot flag; richer log; keep write-ahead-of-bulk |
| `packages/pipeline/dirty_ledger.py` | Optional hot_debounce_ms parameter on `mark` |
| `packages/pipeline/ce_service.py` | Patch publish for small incremental refreshes |
| `packages/pipeline/searcher.py` | Helper to rebuild/patch adapter rows if needed |
| `packages/pipeline/engine.py` | Only if patch publish needs a method on `WarmSearchEngine` (e.g. `apply_chunk_delta`) |
| `tests/test_vectordb.py` | Concurrent search+add |
| `tests/test_live_reindexing.py` | Hot debounce + no compact + write-ahead (existing) |
| `tests/test_sync_corpus_alignment.py` | Keep green |
| `scripts/live_sync_probe.py` | Enforce 5 s + pid stability |
| `pyproject.toml` + `upgrade_releases/v0_3_131.py` | Version |

Avoid drive-by refactors. Edit/Write stay native. Prefer Scubiee MCP map→pack for locating if MCP is up; else Grep/Read.

---

## 8. Research references (use these designs, don’t invent)

1. Faiss thread safety — no search+mutate without exclusion:  
   https://github.com/facebookresearch/faiss/wiki/Threads-and-asynchronous-calls  
2. OpenLore watch: coalesce paths, short debounce, **do not** rewrite whole vector table per file; decouple heavy embed from signature freshness:  
   https://github.com/clay-good/OpenLore/blob/main/docs/specs/openlore-spec-13.1-watch-mode-performance.md  
3. Shadow / atomic pointer swap for vector indexes:  
   https://github.com/hseshadr/edgeproc-core/blob/main/docs/vector-mgmt-architecture.md  
4. Fine-grained incremental embed (only dirty nodes): content-hash gate patterns (code-atlas / vibe gravity kit style) — we already have chunk-key / digest; keep using them.

---

## 9. Out of scope for 0.3.131

- Fixing DirectML install (note as env floor if CPU embed exceeds budget).  
- Deleting stale `_sync_pr_incoming` chunks from older experiments (optional cleanup later).  
- Raising 10k cap / changing composite ranking.  
- Making map accept BM25-only.  
- Committing / pushing unless user asks (note: 0.3.115–0.3.130 may still be uncommitted drift).

---

## 10. Definition of done checklist

- [ ] FAISS add/delete/compact serialized with search  
- [ ] Hot debounce ~250 ms for save reasons  
- [ ] Hot named upsert does not compact whole collection  
- [ ] Hot publish patches binder (no full load_engine) or measured publish_ms &lt; 300 ms  
- [ ] Keeper/hot log has per-stage ms  
- [ ] Unit tests above green (`-p no:logfire`)  
- [ ] Live probe: **hit ≤ 5.0 s**, **pid stable**, map shows file  
- [ ] Version 0.3.131 installed; MCP pins restored after halt  
- [ ] Short report with numbers pasted for the user  

If live probe fails, **name the stage** from the timing line (embed vs write vs publish vs restart) and fix that stage — do not add another unrelated ledger tweak.
