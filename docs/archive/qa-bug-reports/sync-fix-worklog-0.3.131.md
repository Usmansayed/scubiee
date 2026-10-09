# Hot-lane worklog — 0.3.131

Date: 2026-09-26. Repo: `C:\Users\usman\Downloads\context-engine`. Project id: `ce_c505c4e65dbe5e2063a6c1089fe4db4e`. Engine: `http://127.0.0.1:8765`.
Brief: `docs/plans/2026-09-26-hot-lane-5s-map-reflect.md`.

Goal from the brief: when an agent writes a new file, MCP `map` (dense `D_channel_best`) returns it within 5.0 s of the dirty accept, and the engine is not restarted in that window.

Approved design decisions: staged patch publish (append-only first), new-chunk vectors carried to the publisher on a side channel, env kill-switches that fall back to the full reload.

---

## 1. Result

Installed build 0.3.131, DirectML embedder, warm engine. `CTX_PROBE_TRIALS=10 python scripts/live_sync_probe.py .`:

| trial | hit ms | chunk delta | dense rank | mode | pid stable |
| --- | --- | --- | --- | --- | --- |
| 1 | 2599 | +2 | 2 | D_channel_best | yes |
| 2 | 4376 | +2 | 2 | D_channel_best | yes |
| 3 | 4018 | +2 | 2 | D_channel_best | yes |
| 4 | 4367 | +2 | 2 | D_channel_best | yes |
| 5 | 3128 | +2 | 2 | D_channel_best | yes |
| 6 | 3015 | +2 | 2 | D_channel_best | yes |
| 7 | 2924 | +2 | 2 | D_channel_best | yes |
| 8 | 3177 | +2 | 2 | D_channel_best | yes |
| 9 | 3038 | +2 | 2 | D_channel_best | yes |
| 10 | 3231 | +2 | 1 | D_channel_best | yes |

**10/10 within 5.0 s. p50 3177 ms, p95 4376 ms.** On 0.3.130 the same check took ~102 s, and the engine died mid-sync.

MCP acceptance check: a real MCP `map` call for a freshly written `packages/pipeline/sync_mcp_map_131/probe.py` returned it as the **rank-1 card**, `source=D_channel_best:dense`. The probe files were deleted afterwards and re-dirtied, and the path is gone from search.

The probe's rank 2 is expected. Its query also matches the probe's own `__init__.py`.

A typical hot save, from the engine log (`[keeper] hot sync …`):

```text
debounce=295 parse=14 embed=436 vec_open=64 vec_mutate=685 sync_call=1911 publish=5
```

---

## 2. What was in the way

The brief's first three causes were correct: FAISS mutation without the lock, the full-binder publish, and heavy hot-path work. Fixing only those got to ~20 s. Each remaining stage turned up in the per-stage log line, one after another:

| Stage (before → after) | Cause | Fix |
| --- | --- | --- |
| process death | FAISS `add/delete/compact/_own_index_storage` mutated the index while `search` read it | all mutators hold the collection `RLock` that `search` uses |
| publish 23 s → **4–5 ms** | `load_engine(force_reload=True)` rebuilt the whole binder | append-only `WarmSearchEngine.apply_chunk_delta` patch publish |
| debounce 1–2 s → **250 ms** | one debounce for every reason | hot debounce for save reasons; a rewrite never pushes a queued save out |
| compaction | named upsert compacted the whole collection on any delete | skipped on the hot lane; idle/bulk still compacts |
| graph 6.7 s → **0** | `build_merge` rebuilds all 15.9k nodes through `build(dedup=True)` | a hot save defers the graph (and capability cards); a non-hot catch-up carries them |
| embed 2.4 s → **0.4 s** | every `embed_many` re-compressed the whole 10k-entry `embed_cache.npz` (~1.3 s) | snapshot only for ≥64 new rows; load replays the `.jsonl` log tail |
| invalidate 3.5 s → **0.15–0.3 s**, after publish | `invalidate_paths` loaded and **rewrote** all 130 session stores on every save | skip stores that don't cache the path; hot adds invalidate after publish |
| vector write 2.3 s → **0.1–0.7 s** | `add` dequantized all 7.5k rows to read back 2; a fresh collection per sync re-ran a 768² QR and re-read `faiss.index`; `save` sat on the critical path | row-range decode, cached rotation, collection reuse guarded by a disk fingerprint, save deferred past publish |
| queue 3–7 s | `.zed/…` passed the newcomer scan but the Merkle dropped it, so it re-synced every poll (~7 s each) | `root_probe` skips junk newcomers |
| queue 3–7 s | the ~7.5 s newcomer repo walk ran on the keeper thread every 30 s | moved to its own thread |
| queue | a deferred graph catch-up (~8 s) could start between two saves | catch-ups wait until 20 s after the last save |
| queue | a save could wait behind one slow non-hot path | explicit saves always go ahead of any backlog |

Bugs found and fixed along the way:

- `hot_patch_texts` indexed texts by durable `c.id` instead of chunk position.
- A use-before-assignment of `named_delta` in the new hot branch made every hot sync fail and loop. Mocked tests missed it; it is now covered by real-path tests.
- `graph_pending` grew forever because the no-delta catch-up returned without saving meta.
- `npm/package.json` was stuck at 0.3.102, which failed the version-match test.

---

## 3. Durability

**Deferred vector save.** The collection save now runs right after the publish, on the keeper thread, before the next sync reads the disk. `_OnceFlush` makes sure it runs exactly once:

- The keeper always calls it, even when the publish fails.
- The full-publish fallback calls it **before** `load_engine`. A modified file takes that path, and without this it would reload chunks that have no vectors.
- If the process crashes in between, disk holds chunks with no vectors. `reconcile_vector_store` re-embeds them on the next sync (0.3.128 behaviour).

**Collection reuse.** Reuse across hot saves is guarded by a size+mtime fingerprint of every collection file, taken after our own save. If any other writer touches those files, or any non-hot sync runs, the next hot save reloads from disk.

**Embed cache.** Rows appended to `.jsonl` after the last `.npz` snapshot are replayed on load. Snapshot rows win over duplicate log rows.

**Graph debt.** Owed files are recorded in `meta.graph_pending`. The next non-hot sync re-parses them (nothing re-embeds, because the chunk Merkle finds no delta) and merges them into `graph.json`.

---

## 4. Knobs

| env | default | effect |
| --- | --- | --- |
| `CTX_HOT_PUBLISH` | `1` | `0` = always use the full `load_engine` publish |
| `CTX_HOT_DEBOUNCE_MS` | `250` | debounce for save reasons |
| `CTX_HOT_VDB_CACHE` | `1` | reuse the collection across hot saves |
| `CTX_GRAPH_CATCHUP_DELAY_S` | `30` | delay before a deferred graph merge becomes due |
| `CTX_GRAPH_CATCHUP_QUIET_S` | `20` | quiet period after the last save before a catch-up may run |
| `CTX_EMBED_NPZ_MIN_NEW` | `64` | minimum new rows before rewriting the embed-cache snapshot |

Hot reasons: `write`, `changed_file`, `editor_save`, `probe_write`, `after_kiro_write`, `watch`.

---

## 5. Widening decision (brief task 10)

Modified and deleted files still take the full publish. Measured here:

- full publish: 1.5–5.6 s (avg 2.8 s, n=12)
- patch publish: 3.6–82 ms (avg 7.4 ms, n=25)
- BM25 rebuild alone over 7502 chunks: **339–393 ms**

BM25 alone already exceeds the brief's ~300 ms patch-publish cap, and a shifting delta also needs a dense row permutation and a graph-span rebuild on top. **Verdict: no-go for 0.3.131.** A follow-up would need incremental BM25 (append/tombstone postings), not a rebuild.

---

## 6. Caveats and known costs

- The SLA holds for a save that lands on an idle keeper. The keeper is single-threaded, so a save queued behind a deletion or bulk batch waits for that batch first. In one manual check a save waited ~4 s behind the probe's own cleanup and became visible at 7.3 s.
- A new file has zero BM25 and graph affinity until its catch-up runs. It ranks on dense alone, which is the channel that admits it to map. Lexical-only queries for it may rank lower during that window.
- Locking `compact()` blocks searches while it runs. Compaction now only happens on idle/bulk.
- **`uv tool install --reinstall` replaces `onnxruntime-directml` with plain `onnxruntime`.** Dense then fails with `DmlExecutionProvider is not available` until `scubiee setup --repair --skip-model --skip-bench` runs. The brief's install recipe needs that step (see §8).
- The embed floor here is the DirectML GPU (~0.4 s for 2 chunks). On a CPU-only machine the brief measured ~1.7 s per chunk.
- `restore_live_mcp_pins(force=True)` left `.cursor/mcp.json` on the `cmd /c exit 0` stub once, so I restored it by hand. Later restores reported `ok=True`. Reload Scubiee MCP in Cursor after installing.

---

## 7. Tests

Targeted suites, all green except the two pre-existing failures listed below: `test_live_reindexing`, `test_sync_corpus_alignment`, `test_root_probe`, `test_vectordb`, `test_storage_policy`, `test_embed_cache_snapshot`, `test_watcher_recovery`, `test_sync_status_canaries`, `test_dirty_ledger`, `test_freshness`. 113 passed, 2 failed.

New coverage:

- FAISS concurrent search + mutate stress
- hot debounce and rewrite rules
- hot named upsert does not compact
- delta side channel (JSON-safe payload; forwarded and cleared once)
- append-only patch publish, including a real conductor with stale BM25; every fallback path; `CTX_HOT_PUBLISH=0`
- stage-line tokens
- `hot_patch_texts` position fix
- real-path `incremental_sync` hot lane: graph deferral, the delta, debt clearing (including the no-delta catch-up)
- embed-cache snapshot/log replay
- session-store skip
- vector-flush ordering (also when the publish fails; the flush runs before a full reload)
- the collection-reuse guard
- junk newcomers
- off-thread newcomer scan
- catch-up quiet window

Updated: three tests pinned the old debounce for save reasons. They now assert the hot contract, and each keeps a `disk_poll` case showing the long window still applies there.

Pre-existing failures, not caused by this work (installed 0.3.130 has the identical `hold` condition): `test_live_reindexing.py::test_final_check_forces_held_publish`, `test_root_probe.py::test_locate_streak_holds_publish_then_promotes`.

**Full suite: not completed.** With a live engine running, `test_checkout_identity.py` and `test_attach_warm_pipeline.py` hang in `daemon.start_daemon`. Even with both excluded, the run stalls around 62%. The one run that finished (earlier in the session, before the late fixes) showed 38 failures, mostly environment: no `fastembed` in the Miniconda Python, daemon/lifecycle tests, and trace_lab/polytrace evals. I did not triage every one of them against 0.3.130. Next step: run the suite with the engine halted, and compare it against a 0.3.130 baseline.

---

## 8. Install / verify recipe (Windows)

```text
scubiee halt
uv tool install --reinstall "C:\Users\usman\Downloads\context-engine"
scubiee setup --repair --skip-model --skip-bench        # restores onnxruntime-directml
$env:PYTHONPATH="C:\Users\usman\Downloads\context-engine\packages"
python -c "from pipeline.mcp_restore import restore_live_mcp_pins; print(restore_live_mcp_pins(project=r'C:\Users\usman\Downloads\context-engine', force=True))"
scubiee engine ensure .
$env:CTX_PROBE_TRIALS="10"; python scripts/live_sync_probe.py .
```

If the model cache is missing (`model_fp16.onnx … File doesn't exist`), run `scubiee setup --repair` without `--skip-model`.

Probe modes: the default is warm-up + one measured round. `CTX_PROBE_ROUNDS=1` runs one measured round. `CTX_PROBE_TRIALS=N` runs N settled trials and reports p50/p95. `CTX_PROBE_SLA_S` sets the budget (default 5.0).

---

## 9. Files changed

| File | Change |
| --- | --- |
| `packages/pipeline/vectordb.py` | lock all mutators; row-range decode in `add` |
| `packages/pipeline/turbo_quant.py` | `rows_float32`; cached, read-only rotation |
| `packages/pipeline/dirty_ledger.py` | `HOT_SYNC_REASONS`, hot debounce, `marked_at` |
| `packages/pipeline/incremental.py` | `hot_lane`, `HotDelta`, stage timings, graph/cards deferral + debt, deferred vector save (`_OnceFlush`) |
| `packages/pipeline/sync_loop.py` | hot batch selection, delta side channel, stage log line, deferred-flush run, graph catch-up scheduling + quiet window, collection reuse, off-thread newcomer scan, saves ahead of any backlog |
| `packages/pipeline/engine.py` | `WarmSearchEngine.apply_chunk_delta` |
| `packages/pipeline/ce_service.py` | `_hot_publish_runtime` + fallback, flush before full reload, `publish`/`publish_ms`, `pid` on `/health` |
| `packages/pipeline/embedder.py` | conditional `.npz` snapshot + log-tail replay |
| `packages/pipeline/session_store.py` | skip untouched session stores |
| `packages/pipeline/root_probe.py` | skip junk newcomers |
| `packages/pipeline/hot_patch.py` | position-indexed patch |
| `packages/pipeline/upgrade_releases/v0_3_131.py`, `__init__.py` | release registered |
| `pyproject.toml`, `npm/package.json` | 0.3.131 |
| `scripts/live_sync_probe.py` | 5 s SLA, PID check, dense map check, stage-named failures, trials mode |
| `tests/…` | see §7; new file `tests/test_embed_cache_snapshot.py` |

Nothing has been committed or pushed.
