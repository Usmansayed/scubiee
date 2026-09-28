# Kiro results for docs/kiro-open-issues-2026-09-27.md

Machine: Windows, 15.7GB RAM, Cursor + Kiro open. Engine and MCP from the uv tool,
synced with `scripts/sync-uv-install.ps1` (`differ: 0  missing: 0`, OK) before every live
run. PYTHONPATH cleared for every run. Nothing committed.

Final build: **0.3.132** (`pyproject.toml`, `npm/package.json`, release note
`packages/pipeline/upgrade_releases/v0_3_132.py`). Wheel and sdist:
`dist/scubiee-0.3.132-py3-none-any.whl`, `dist/scubiee-0.3.132.tar.gz`. Installed in the
uv tool; `/health` reports `version=0.3.132`.

## Summary (live, 0.3.132, 2026-09-28 02:29–03:17)

| Issue | Pass check | Result |
|---|---|---|
| 1 stale map | 5/5 fresh within 1s of the bump, repeat = cache hit | **5/5** (fresh 176–207ms, repeat server 2.9–4.0ms) |
| 2 engine dies | no unexplained PID change, kill recovers, no APPCRASH | **pass**: kill→health 7.0s; 10/10 stop/ensure; 0 APPCRASH; every PID change has a `[stop]` line |
| 3 RAM guard / commit | no `embed waiting pressure=critical`; private bytes down | **pass**: 0 lines; median private 3724–3882MB → 1697MB, max 4209 → 1719MB |
| 4 save → searchable | 21/21 ≤5s, small steps ≤3s p95 | **18/21**; small steps max 2.75s; `new_big` (60 new chunks) 6.3–7.2s **still fails** |
| 5 first edit re-embeds | `[embed] N/N new` ≤3 | **1/1 new** (94-chunk module, engine restarted first) |
| 6 graph catch-up blocks saves | B searchable ≤5s during A's catch-up | **3/3** (3.2–3.3s; was 15.0–17.1s, 0/3) |
| 7 reinstall breaks MCP | next call in the same session succeeds | **pass**: gate #2 ok (6.3s, worker respawned on new code) |
| 8 traceback spam | 0 `ConnectionAbortedError` tracebacks | **pass**: 0 tracebacks, 460 one-line notes |
| 9 failing tests | both fixed; full suite run | both fixed; full-suite list below |

## 1. `map` returns stale results after an edit

**Status: staleness fixed (15/15 post-fix runs fresh on the first map after the bump,
0 stale answers). The 1s latency part of the pass check is met in 9/15 runs; the 6
misses are slow re-queries while the keeper runs a graph catch-up / deferred vector
save (issues 4 and 6), not the cache.**

### Sources

- Elasticsearch shard request cache: cached results are invalidated on every shard
  refresh, so the cache never returns results that differ from an uncached search —
  https://www.elastic.co/docs/deploy-manage/distributed-architecture/shard-request-cache
- Blanco et al., "Caching search engine results over incremental indices" (SIGIR 2010):
  index updates are what makes result caches stale; flushing on update is the
  simple-but-correct baseline — http://www.dc.fi.udc.es/~roi/publications/sigir2010b.pdf
- Alici et al., "Timestamp-based result cache invalidation" (SIGIR 2011): compare the
  generation time of a cached result with index update times —
  http://www.cs.bilkent.edu.tr/~oulusoy/sigir11_1.pdf
- Generational (version-stamped) invalidation: tag each entry with the counter it was
  built on; a counter bump makes old entries unreachable —
  https://www.emergentmind.com/topics/generational-invalidation-scheme

For a single-user local engine the "invalidate on refresh" model (Elasticsearch) is the
right fit: publishes are seconds apart at most, and correctness after an edit matters
more than hit rate across edits.

### Root cause

Both map caches in the MCP locate process ignore the index: the process cache is called
with the constant `fingerprint="soft_v1"` and its `_LAST` path skips the fingerprint
entirely (300s TTL), and the session-store `map_cache` used for duplicate queries has no
generation or TTL at all. The engine is a separate process, so its publish cannot clear
either cache.

### Fix

The engine writes a small stamp file on every generation bump; the MCP side keys both
caches on it.

- New `packages/pipeline/index_generation.py`: `write_stamp(project_id, generation,
  epoch)` writes `~/.scubiee/projects/<id>/generation.json` (tmp + `os.replace`, retries
  a Windows sharing violation, monotonic per epoch so a late older publish cannot move it
  back). `read_token(repo)` returns `"<epoch>:<generation>"` or None.
- `RepoRuntime.epoch` (random per runtime): the generation counter restarts at 0 on an
  engine restart or a recreated runtime, so the token must carry more than the counter.
  Seen live: `/health` generation went 16 → 2 across a restart.
- `ce_service.RuntimeManager._stamp_generation` is called after every bump:
  `publish_engine`, `_publish_runtime` (full), `_hot_publish_runtime` (patch, outside the
  lock), `_ensure_engine` (fresh binder load now bumps N → N+1 instead of only 0 → 1,
  since a binder reloaded from disk is a new publication).
- `map_result_cache`: `get/put_map_cached` require the token; `_LAST` now stores the token
  and evicts on mismatch; no token = no caching; `get_recent_map_cards` only returns cards
  from the current token.
- `mcp_locate.map_impl`: reads the token once, *before* the search (a publish landing
  mid-search leaves the entry under the older token, so the next map re-queries), passes
  it to both caches. `_map_cache_get/_map_cache_put` store/compare `token`; old entries
  without one are never served. Session hits now say `"cache": "session"`.
- `mcp_response_lean`: the lean map response keeps `cache` (`hit` / `last` / `session`)
  so a caller can tell a repeat did not re-query.

Cost of the fast path (installed interpreter, 2000 reads of the real stamp):
`p50=0.346ms p95=0.530ms p99=0.608ms max=0.891ms`. Repeat-map server time with the check:
2.7–3.9ms (outliers 13.9 / 29.0 / 996ms while the keeper was busy, see below).

### Tests

- New `tests/test_map_cache_generation.py` (9 tests): stamp roundtrip + monotonic per
  epoch + new epoch; torn/missing stamp disables caching; process cache misses on a new
  token; no token = no cache; `get_recent_map_cards` filtered by token; `_stamp_generation`
  and `_hot_publish_runtime` advance the stamp; session-store cache token-keyed (tokenless
  legacy entries rejected); end-to-end `map` tool: map → publish → map returns the new
  cards, unchanged repeat hits, session-store path also invalidated.
- Updated `tests/test_attach_warm_pipeline.py::test_map_result_cache_hit_miss` (it
  asserted the bug: a different fingerprint still hit) and
  `tests/test_mcp_exploration_regressions.py::test_map_cache_roundtrip` (token-keyed).
- `pytest tests/test_map_cache_generation.py tests/test_attach_warm_pipeline.py
  tests/test_dense_map_required.py tests/test_mcp_exploration_regressions.py
  tests/test_lean_pack_seed_rank.py tests/test_multi_repo_runtime.py
  tests/test_mcp_response_lean.py`: 90 passed, 1 failed
  (`test_client_retries_transient_url_error`: it patches `urllib.request.urlopen` but the
  client reached the live engine on :8765; unrelated to this change, listed under issue 9).
- Standard loop (10 files): 267 passed, 2 failed — `test_final_check_forces_held_publish`
  (known, issue 9) and `test_watcher_recovery.py::test_5000_event_storm_processes_only_configured_batch`,
  which passes alone and with `test_live_reindexing.py` (order-dependent env leak; issue 9).

### Probe

New `scripts/map_staleness_probe.py [runs] [--json out] [--bridge-log file]`: spawns the
real bridge from `.cursor/mcp.json` (PYTHONPATH stripped), creates a scratch module,
then per run: map(Q) → append a function → poll `/health` for a generation bump → map(Q)
must show the function within 1s → map(Q) again must be a cache hit. Q is a sentence drawn
per run so no chunk matches it before the edit. A bump without our edit is detected with a
direct `/v1/search` (top_k=8, same as map) and ignored; engine has it but map does not =
stale.

Two probe lessons worth keeping:
- Hot patches leave BM25 one generation behind (`engine._patch_chunk_delta` docstring), so
  a just-saved chunk is only reachable through dense until the next full publish. A
  nonsense-word query never found the new chunk (the first post-fix attempt reported 0/5
  for that reason). See "new findings" at the end.
- Lean map cards carry `loc` (`file:start-end`), not `start_line/end_line`, and `why` is a
  200-char preview; several small functions share a chunk, so the probe checks the token
  *or* a card reaching past the old end of file.

### Before the fix (installed tree without the change, engine restarted)

```
run=0 gens=7,8   edit->bump 29121ms  engine has edit, map stale >12s  (stale map 77.3ms)
run=1 gens=8,9   edit->bump 22963ms  engine has edit, map stale >12s  (stale map 2555ms)
run=2 gens=9,10  no bump carrying the edit within 60s
run=3 gens=10,11,12 edit->bump 50769ms engine has edit, map stale >12s (stale map 71.7ms)
run=4 gens=12,13 no bump carrying the edit within 60s
SUMMARY 0/5

second pass:
run=0 gens=2,3   edit->bump 31534ms  engine has edit, map stale >12s, cache=hit(inferred) 70.9ms
run=1,2          no bump carrying the edit within 120s
SUMMARY 0/3
```

The stale answers came back in 70–77ms (a cache hit; a real map is 230ms+) while
`/v1/search` on the same engine already returned the edit.

### After the fix (3 × 5 runs, engine pid 15468 stable across all 15)

```
SUMMARY 4/5
  run 0: edit->bump 2746 ms  fresh 240.1 ms (miss)  repeat 74.1 ms server 3.9 ms cache=last  same_pid=True ok=True
  run 1: edit->bump 14477 ms fresh 1427.1 ms (miss) repeat 71.7 ms server 3.2 ms cache=last  same_pid=True ok=False
  run 2: edit->bump 12567 ms fresh 284.2 ms (miss)  repeat 91.4 ms server 3.2 ms cache=last  same_pid=True ok=True
  run 3: edit->bump 15320 ms fresh 257.3 ms (miss)  repeat 71.3 ms server 2.9 ms cache=last  same_pid=True ok=True
  run 4: edit->bump 14398 ms fresh 239.0 ms (miss)  repeat 66.6 ms server 3.4 ms cache=last  same_pid=True ok=True
SUMMARY 3/5
  run 0: edit->bump 13148 ms fresh 277.6 ms   repeat 52.4 ms   server 3.1 ms   cache=last ok=True
  run 1: edit->bump 9022 ms  fresh 255.3 ms   repeat 80.3 ms   server 3.1 ms   cache=last ok=True
  run 2: edit->bump 14226 ms fresh 2363.7 ms  repeat 2537.9 ms server 996.3 ms cache=last ok=False
  run 3: edit->bump 13568 ms fresh 1347.2 ms  repeat 51.8 ms   server 2.7 ms   cache=last ok=False
  run 4: edit->bump 12293 ms fresh 240.1 ms   repeat 84.0 ms   server 3.4 ms   cache=last ok=True
SUMMARY 2/5
  run 0: edit->bump 12766 ms fresh 1350.5 ms  repeat 56.5 ms server 2.8 ms  cache=last ok=False
  run 1: edit->bump 12015 ms fresh 227.2 ms   repeat 54.1 ms server 2.9 ms  cache=last ok=True
  run 2: edit->bump 11759 ms fresh 229.9 ms   repeat 51.2 ms server 2.8 ms  cache=last ok=True
  run 3: edit->bump 13907 ms fresh 11299.8 ms repeat 83.0 ms server 29.0 ms cache=last ok=False
  run 4: edit->bump 24046 ms fresh 7893.1 ms  repeat 67.3 ms server 13.9 ms cache=last ok=False
```

Every "fresh" map above was a cache miss that returned the new function on the first call
after the bump. The slow ones line up with keeper work on the same engine
(`engine.log`, third pass):

```
[keeper] hot sync path=packages/pipeline/zz_mapstale_1790508907.py ... sync_ms=1614 invalidate_ms=8588 total_ms=10813
[keeper] deferred vector save ms=1105
[keeper] deferred vector save ms=5870
[sync] no chunk delta files=2 paths=packages/pipeline/zz_mapstale_1790508907.py,scripts/map_staleness_probe.py reconciled=0 ms=15530
```

and in the first pass `publication_ms=1366 ... invalidate_ms=10005` plus
`deferred vector save ms=1377` around run 1. The bridge/worker stderr (captured with
`--bridge-log`) showed no AST re-hydrate in the MCP worker during these runs, so the time
is spent in the engine's `/v1/search` under keeper load.

Typical hot sync lines for the probe edits (after the fix):

```
[keeper] hot sync path=packages/pipeline/zz_mapstale_1790508504.py debounce_ms=565 slice_ms=88 parse_ms=56 graph_ms=0 embed_ms=409 write_ms=52 vectors_ms=8 (open=0 mutate=8 save=-) chunkfile_ms=43 reconcile_ms=511 publication_ms=48 cards_ms=0 sync_ms=1939 sync_call_ms=1942 invalidate_ms=117 publish_call_ms=11 publish_ms=6 total_ms=3800 upserted=2 removed=0 publish=patch pid=15468
[keeper] hot sync path=packages/pipeline/zz_mapstale_1790508504.py debounce_ms=9824 ... sync_ms=1718 ... invalidate_ms=109 ... total_ms=12024 upserted=2 removed=1 publish=patch pid=15468
```

Monitor (`engine_mem_monitor.py`, 16:29–17:08, 851 samples): min free RAM 1696MB, max
engine private 4209MB, max RSS 1328MB, 49 health-error samples. **PID not stable over the
whole window**: 32072 → 26988 (16:33) → 27840 (16:37) → 21960 (16:47) → 15468 (16:56);
stable for all 15 counted runs. The restarts are issue 2 (watchdog "force heal hung engine"
at 16:33/16:37 while prewarm starved `/health`; "engine dead with MCP demand
pid_alive=False" at 16:56 with no APPCRASH event).

### Re-check on 0.3.132 (after issues 4 and 6)

```
SUMMARY 5/5 fresh within 1000ms of the generation bump, repeat = cache hit
  run 0: edit->bump 2126 ms  fresh 175.8 ms (cache=miss)  repeat 85.8 ms server 2.9 ms cache=last  same_pid=True ok=True
  run 1: edit->bump 2377 ms  fresh 201.8 ms (cache=miss)  repeat 64.9 ms server 3.5 ms cache=last  same_pid=True ok=True
  run 2: edit->bump 2605 ms  fresh 206.5 ms (cache=miss)  repeat 72.2 ms server 3.7 ms cache=last  same_pid=True ok=True
  run 3: edit->bump 2829 ms  fresh 179.6 ms (cache=miss)  repeat 67.0 ms server 3.3 ms cache=last  same_pid=True ok=True
  run 4: edit->bump 3262 ms  fresh 178.6 ms (cache=miss)  repeat 83.7 ms server 4.0 ms cache=last  same_pid=True ok=True
```

edit→bump fell from 9–29s to 2.1–3.3s and every fresh map is under 210ms.

### Still open for issue 1
- `pipeline.locate._CACHE` (`locate()` / `related()` cards, 600s TTL, no generation) has
  the same flaw. It is not on the MCP `map` path; left unchanged.

---

## 2. Engine dies silently

**Status: fixed. Five separate killers, all found by adding an audit line to every stop.**

### Sources

- Job objects: a process in a `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` job dies when the last
  job handle closes; children inherit the job unless created with
  `CREATE_BREAKAWAY_FROM_JOB` (needs `JOB_OBJECT_LIMIT_BREAKAWAY_OK`) —
  https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
- `Win32_Process.Create` starts a process whose parent is WmiPrvSE, outside the caller's
  job and tree — https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/create-method-in-class-win32-process
- `faulthandler` for native crash tracebacks — https://docs.python.org/3/library/faulthandler.html
- WER LocalDumps (full dumps of a crashing process) —
  https://learn.microsoft.com/en-us/windows/win32/wer/collecting-user-mode-dumps
- Windows delete/rename vs open handles (sharing violation, `ERROR_SHARING_VIOLATION` 32) —
  https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-deletefilew

### Root causes (each proven with a `[stop]` audit line or a probe)

1. **Bridge job.** The engine was a `Popen` child of the MCP bridge inside the bridge's
   KILL_ON_JOB_CLOSE job; closing the IDE/bridge killed it with no log line.
   `scripts/engine_bridge_exit_probe.py`: legacy spawn 0/3 survive, new spawn 5/5.
2. **Prewarm lock self-deadlock.** `prewarm_embedder_async` called `prewarm_status()`
   while holding `_PREWARM_LOCK`; every `/health` then blocked (py-spy: 99 threads in
   `prewarm_status`), and the watchdog "force healed" a live engine.
3. **Engine self-quiesce.** `load_engine → heal_checksum_mismatch → index_repo →
   quiesce_background_indexing` stopped the engine's own watchdog/daemon
   (`by=engine at=store_lock.quiesce_background_indexing<indexer.index_repo<...`).
4. **Stale prewarm markers (0.3.132 battery).** `_mark_prewarm_busy(False)` and
   `set_phase(dense)` swallowed WinError 32/5 when the watchdog or a bridge had the file
   open, leaving "prewarm" on disk; 3 minutes later the watchdog restarted a healthy engine
   as a hung prewarm (`health ok but hung prewarm — falling through to restart path`).
   Reproduced with the installed old code: `hung_prewarm_should_abort = True` and disk
   phase `prewarm` after both "clears".
5. **The test suite.** `tests/test_wipe.py::test_wipe_repo_halts_before_removal` opts out
   of the file's kill mocks, so the real post-wipe restart ran `stop_daemon` +
   `kill_all_scubiee_processes` on the developer's machine: engine, watchdog and every MCP
   bridge (`hold bridge exited rc=15`). Running the documented test loop killed the live
   engine. Bisected by checking the engine PID around each test file.

### Fix

- Spawn: `daemon._spawn_engine_orphan` (WMI `Win32_Process.Create` + `pipeline.engine_boot`
  boot JSON for env/log); fallback `Popen` with `CREATE_BREAKAWAY_FROM_JOB`; the bridge job
  now sets BREAKAWAY_OK. `CTX_ENGINE_ORPHAN_SPAWN=0` restores the old path.
- `engine_log.py` (new): timestamped log lines, `faulthandler`, `note_stop(target, pid,
  reason, method)` with the caller's stack (`[stop] target=… reason=… by=… at=…`), and
  `hard_exit` (TerminateProcess, skips ORT/DirectML DLL-detach destructors).
- `_PREWARM_LOCK` is an RLock; status is copied before calling out.
- `store_lock.quiesce_background_indexing` is a no-op inside the engine/watchdog role;
  `load_engine` tries `republish_manifest_if_coherent` before a reindex.
- Prewarm markers: `_mark_prewarm_busy(False)` retries the unlink and else overwrites the
  stamp with `0 0` (pid 0 = writer gone); `warm_autoload._write_phase_file` retries the
  rename and falls back to an in-place overwrite. The watchdog also refuses the hung-prewarm
  restart when `/health` says `embedder_loaded=True`.
- Tests: `conftest._never_kill_the_developers_processes` blocks `psutil.kill/terminate`,
  `os.kill` and `taskkill_silent` on PIDs outside pytest's own tree;
  `test_wipe_repo_halts_before_removal` mocks the restart.
- `scripts/enable_wer_localdumps.ps1` written; **not applied** (needs admin).

### Tests

`tests/test_engine_lifecycle_audit.py` (17), `tests/test_prewarm_stamp_locked.py` (4:
stamp held open during clear, phase file held open during `set_phase`, neutralised stamp,
watchdog does not restart when the embedder is loaded).

### Live (0.3.132)

```
engine_kill_recover_probe --budget-s 120:  kill_to_health_s 7.0  kill_to_soft_ready_s 7.0  ok true
  watchdog: engine dead with MCP demand clients=2 — recover now … restart result=True
10 x stop/ensure: stop 2638–2884ms, ensure 4390–5398ms, warm=ready every cycle
APPCRASH (Application log 1000/1001/1002/1026, python) since 03:15:02: none
```

Every PID change in the 02:29–03:17 window has a matching `[stop]` line (user stop,
`idle_standby` with no clients, or the kill probe). Monitor: 1282 samples, min free RAM
732MB (full test suite running for part of it), max engine private 1719MB.

---

## 3. Low-RAM guard stalls saves; engine commits ~4GB

**Status: fixed.**

### Sources

- OpenBLAS allocates a buffer per thread (`OPENBLAS_NUM_THREADS`) —
  https://github.com/OpenMathLib/OpenBLAS/wiki/faq#multi-threaded
- numpy / threadpoolctl on BLAS thread pools — https://numpy.org/doc/stable/reference/global_state.html

### Root cause

`scripts/engine_commit_breakdown.py` on the installed interpreter: numpy import +491MB
committed, faiss +1932MB, ORT session +790MB, index +231MB. The numpy and faiss commits
are OpenBLAS per-thread buffers (16 threads); with `OPENBLAS_NUM_THREADS=1` each is ~8MB.
Separately the RAM guard had two thresholds (prefs vs env) and made hot saves wait up to
120s at `pressure=critical`.

### Fix

`OPENBLAS_NUM_THREADS=1` in the engine spawn env (and the graph worker); one
`DEFAULT_MIN_FREE_RAM_MB=512` (env beats prefs); hot-lane embeds (≤64 chunks) and hot
syncs wait at most ~1s, then proceed at full batch size; bulk keeps 180s and bs=1.
Tests: `tests/test_hot_lane_ram_guard.py`.

### Live

| monitor file | samples | median private MB | max private MB |
|---|---|---|---|
| issue1_before (0.3.131) | 646 | 3724 | 4172 |
| issue2_before (0.3.131) | 297 | 3882 | 4027 |
| 0.3.132 battery | 1282 | **1697** | **1719** |

`embed waiting pressure=critical` lines on 2026-09-28: **0**.

---

## 4. Save → searchable

**Status: small files fixed (≤2.75s every sample). The 60-chunk `new_big` step still
misses 5s: 6.3–7.2s, of which the DirectML embed alone is ~3.1s.**

### Sources

- GIL convoy effect: a thread that releases the GIL for a short syscall waits a full
  switch interval to get it back from a CPU-bound thread — https://bugs.python.org/issue7946,
  https://github.com/python/cpython/issues/89977, David Beazley,
  http://www.dabeaz.com/blog/2010/02/revisiting-thread-priorities-and-new.html
- `ctypes.PyDLL` keeps the GIL held for the foreign call —
  https://docs.python.org/3/library/ctypes.html#ctypes.PyDLL
- `GetFileAttributesExW` — https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfileattributesexw

### Root causes

1. BM25 lagged one generation on hot patches (edit steps TIMEOUT).
2. Per-save fixed costs: reconcile ~500ms, merkle ~500ms (ignore rules reloaded per file,
   300ms), a git subprocess per `PipelineStore`, keepalive full reloads after
   `clear_engines`, a duplicate prewarm binder, manifest re-checksums (385–2049ms).
3. **GIL convoy in the change poll** (found with `scripts/keeper_stack_logger.py`: the
   keeper sat 6–11s in `root_probe._rebuild_universe` → `stat`). Each `os.stat` /
   `Path.resolve` / file read releases the GIL; with a `/v1/search` running, each one waits
   ~15ms to get it back. `scripts/root_probe_convoy_bench.py`: stat loop over 1167 indexed
   files **78ms idle, 18,325ms with one busy thread**; the full poll 3,075ms (1.8s of it
   `PipelineStore.__init__` resolving the project, 19 `resolve()` calls).
4. Session-span invalidation opened ~130 session stores per save (resolve + mkdir + read
   each): `invalidate_ms` up to 6709.
5. The first save after a delete reused the deleted file's tombstoned vector ids, so
   `col.add` took the upsert path: `compact()` of every vector, `mutate=7015ms`.

### Fix

- BM25 `append_docs/mark_dead` on hot patch; no `clear_engines` when a hot delta exists;
  `_engine_key` normalisation; no reconcile on the hot lane; ignore rules loaded once;
  mtimes reused; cached `git_common_dir`; manifest checksum reuse on unchanged
  size+mtime_ns; invalidate after publish.
- `pipeline/fast_stat.py` (new): `fast_stat` = `GetFileAttributesExW` through
  `ctypes.PyDLL` (no GIL handoff; same `st_mtime` float as `os.stat`; reparse points and
  errors fall back to `os.stat`; `CTX_FAST_STAT=0` disables) and `cached_resolve`.
  Used by `_rebuild_universe`, `_dir_newcomers`, `load_scubiee_ignore`.
- `root_probe(store=…)` + `_probe_inputs` cache (keyed on merkle.json / meta.json /
  .scubieeignore stamps); the keeper passes one long-lived store (`_poll_store`).
- `session_store.invalidate_paths`: scandir listing, direct paths, and a mention cache
  keyed on each store's (mtime_ns, size); an unchanged store costs one GIL-held stat.
- `_avoid_tombstoned_ids`: new chunks get ids the collection never held.
- `_estimate_dirty_chunks`: byte-level per-file count (`count_chunks_per_file`), cached
  on the chunks.jsonl stamp (90 → 32ms idle, then a cache hit).

Bench after: stat loop with one busy thread 18,325 → 167ms; full poll 3,075 → 772ms.

### Tests

`tests/test_bm25_append.py`, `tests/test_manifest_reuse.py`, `tests/test_fast_stat.py`
(matches `os.stat` incl. the float mtime; missing paths; env off; **400-file stat loop
<1s with a busy thread — fails at 5.96s with `CTX_FAST_STAT=0`**; mention cache sees a new
span; `count_chunks_per_file` vs escaped quotes in text; probe-input cache sees a
rewritten merkle), `tests/test_graph_catchup_async.py::test_new_file_after_deleting_the_newest_file_does_not_compact`
(fails without the fix: `compacts == [1]`).

### Live: `disk_save_probe.py . 3` on 0.3.132

```
round 0 new_file 2728  edit_small 2615  new_big 7245 X  edit_big 3302  new_subdir 2524  delete 2281  restore_big 3542
round 1 new_file 2539  edit_small 2747  new_big 7012 X  edit_big 4009  new_subdir 2723  delete 2324  restore_big 4024
round 2 new_file 2429  edit_small 2517  new_big 6255 X  edit_big 3816  new_subdir 2534  delete 1964  restore_big 3224
SUMMARY 18/21 within 5s     same_pid=True on all 21
```

Small-file steps (new_file, edit_small, new_subdir, delete): max **2747ms** (p95 ≤3s met).
Earlier today on the pre-convoy-fix build: 5/21 and 6/21 with steps of 8–56s.

Matching hot sync lines (round 0):

```
hot sync path=…/zz_disksave_… debounce_ms=376 parse_ms=19 embed_ms=335 vectors_ms=72 chunkfile_ms=349 merkle_ms=260 publication_ms=155 sync_ms=1411
hot sync path=…/zz_disksave_… debounce_ms=378 parse_ms=27 embed_ms=285 vectors_ms=11 chunkfile_ms=116 merkle_ms=84 publication_ms=382 sync_ms=1108
hot sync path=…/zz_dsbig_…    debounce_ms=579 parse_ms=1151 embed_ms=3199 vectors_ms=31 chunkfile_ms=148 merkle_ms=98 publication_ms=360 sync_ms=5176
hot sync path=…/zz_dsbig_…    debounce_ms=533 parse_ms=884 embed_ms=469 vectors_ms=21 merkle_ms=176 publication_ms=220 sync_ms=2332
hot sync path=…/mod_….py       debounce_ms=377 parse_ms=23 embed_ms=350 vectors_ms=18 merkle_ms=85 publication_ms=366 sync_ms=1158
hot sync path=…/zz_disksave_… debounce_ms=376 embed_ms=- vectors_ms=2 merkle_ms=123 publication_ms=403 sync_ms=830
hot sync path=…/zz_dsbig_…    debounce_ms=451 parse_ms=1334 embed_ms=- merkle_ms=78 publication_ms=336 sync_ms=2045
```

### Still failing

`new_big` (60 new chunks): embed 3.1–3.2s on DirectML (~19 chunk/s) + parse 0.7–1.2s +
publish ≈ 5.2–7.2s. Getting under 5s needs faster embedding (batching/model), or splitting a
large new file so the first chunks publish before the rest. Not attempted.

---

## 5. First edit after upgrade re-embeds the whole file

**Status: fixed. The cause was not the stored digests.**

### Root cause

The embed decision (`diff_chunk_records`) compares digests computed fresh from the stored
chunk records and the new ones; `chunk_merkle.json` is not consulted, so migrating it would
change nothing. The digest hashed `enriched` minus the file-wide lines, but the body is
capped at 512 chars *after* those lines are prepended: a longer `Exports:` line (one new
function) or an enrichment-format change between builds moves where every chunk's own code
is cut off. `scripts/chunk_digest_drift_probe.py` (read-only: rebuild each unedited file
the way a sync does and diff per chunk): mcp_locate.py 47/114 changed, cli_ui.py 55/95,
context_trace.py 22/94 — with the files unchanged on disk.

### Fix

`chunk_digest` hashes the chunk's raw `text` (first 512 chars — every text cap used so far
is ≥512, so chunks stored by older builds hash the same); empty text falls back to the old
enriched-own-lines digest. After: 0 changed across 6 unedited files (mcp_locate,
cli_ui, context_trace, accel, lifecycle_runtime, graphify/extract).

Tests: `tests/test_chunk_merkle.py` (+2: longer file-wide lines that move the cap;
digest stable across 1200 vs 512 text caps, changes on a real edit).
`test_locate_contract_bounds.py::test_realistic_add_noop_and_delete` updated: its seeded
chunk has the file's exact source, so the first sync now correctly re-embeds nothing.

### Live

Copy of context_trace.py (94 chunks) indexed, engine restarted, one function appended:

```
indexed copy:  embed_ms=5814 upserted=94 removed=0
after append:  embed_ms=680  upserted=1  removed=0
[embed] 1/1 new (+0 cached) 3.17 chunk/s … device=dml
```

---

## 6. Graph catch-up runs on the save keeper

**Status: fixed (option b/c hybrid: merge in a child process, commit on the keeper).**

### Options considered

| option | cost | risk |
|---|---|---|
| a. incremental graph patch (changed file's nodes/edges only) | fastest | whole-graph `dedup` (minhash) semantics change; highest risk |
| b. catch-up on a worker thread | small change | pure-Python merge holds the GIL; saves still stall (see issue 4 convoy) |
| **c. child process merges into a temp file; keeper commits** | +process spawn, one IPC file | picked: no GIL sharing; optimistic commit guards races |

### Sources

- Lucene/Elasticsearch run segment merges on a separate scheduler so indexing is not
  blocked — https://www.elastic.co/guide/en/elasticsearch/reference/current/index-modules-merge.html
- Atomic swap with `os.replace` — https://docs.python.org/3/library/os.html#os.replace

### Root cause

Profile of a one-file catch-up (`scripts/graph_merge_profile.py`): 11.3s = `build(dedup=True)`
6.8s (dedup 3.1s, build_from_json 3.6s) + JSON export/reload 4.3s, all on the keeper thread.

### Fix

`pipeline/graph_merge_worker.py` (new): a below-normal-priority child runs
`extract + build_merge + to_json` into `.graph_catchup.<token>.json`, recording graph.json's
(size, mtime_ns) at start. The keeper keeps serving saves; when the child exits it renames
the file into place (`incremental_sync(graph_precomputed=…)`, retries a sharing violation)
and refreshes merkle/publication. Discarded and re-queued if graph.json changed meanwhile,
a newer save of the same file keeps its own entry, one job at a time, two failures fall
back to the inline merge, `stop()` kills the child, stale temps (incl. old
`.graph.json.*.tmp`) are swept. `graph_pending` is now paid off only for the paths the sync
carried. `CTX_GRAPH_CATCHUP_ASYNC=0` restores the inline merge.

Tests: `tests/test_graph_catchup_async.py` (14, incl. a real child process).

### Live: `graph_catchup_probe.py . 3`

```
before (0.3.131):  SUMMARY 0/3   B 15247 / 17137 / 14975 ms   catch-up 12970 / 14670 / 12520 ms (keeper)
after  (0.3.132):  SUMMARY 3/3   B  3289 /  3208 /  3225 ms   catch-up  8157 /  8159 /  8087 ms (child)
[keeper] graph catch-up done ms=8087 worker_ms=7166 (extract=42 merge=5393 export=1286) commit_ms=357 nodes=15996
```

---

## 7. Reinstall breaks the running MCP server

**Status: fixed. Two causes.**

### Sources

- MCP stdio transport: the server is a child of the host; if it exits the host marks the
  server disconnected and does not respawn it —
  https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- MCP lifecycle (initialize must precede other requests, so a respawned worker needs the
  initialize replayed) — https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle

### Root causes

1. The bridge already respawns its worker (replaying `initialize`) when
   `~/.scubiee/active_build.json` changes, but `sync-uv-install.ps1` never wrote it, so
   workers kept running pre-install code.
2. "Not connected" after the test loop: the test suite killed the bridges (issue 2, cause 5)
   and, in a full-suite run, rewrote this repo's `.cursor/mcp.json` to the `cmd /c exit 0`
   stub (`stub_mcp_commands_to_noop` walks `Path.cwd()`), so every new session died on
   initialize (`server closed stdout while waiting for initialize`). Restored by hand.

### Fix

`sync-uv-install.ps1` writes the build stamp after a verified install
(`[sync] active build stamp: 0.3.132-…`). `conftest._never_touch_the_developers_mcp_configs`
restores the repo's and the home-level Cursor/Kiro MCP configs after any test that
rewrites them and logs the test id to `%TEMP%\conftest_mcp_restores.log`.

### Live: `scripts/reinstall_survival_probe.py` (new)

```
+  4.5s gate #1 ok
+  4.6s running sync-uv-install.ps1 …   install rc=0, active build stamp 0.3.132-1790545388
+ 45.3s … 53.8s  4 mcp_locate workers exit (bridges respawn them); engine, watchdog, bridges untouched
+ 57.7s gate #2 same session: ok=True ms=6282
```

---

## 8. `ConnectionAbortedError` traceback spam

**Status: fixed.** `EngineHTTPServer.handle_error` logs one line
(`[http] client gone mid-response: ConnectionAbortedError port=…`) for
ConnectionAborted/Reset/BrokenPipe and keeps full tracebacks for everything else.
Test in `tests/test_engine_lifecycle_audit.py`. engine.log on 2026-09-28 (17,462 lines,
all probes above): **0 tracebacks**, 460 one-line notes.

---

## 9. Failing unit tests

- `test_final_check_forces_held_publish`: since 0.3.131 only a bulk-size publish is held
  during a locate streak; the test's 1-chunk payload published inline. Test now uses a
  bulk-size payload and asserts the hold before `final_check`.
- `test_requirement_satisfied_for_installed_pip`: skipped when pip is absent.
- Also fixed on the way: `test_5000_event_storm…` (env leak of
  `CTX_SYNC_WAIT_FOR_EMBEDDER` from `_start_keeper`, cleared in conftest),
  `test_incremental_missing_graph_falls_back` (`or force_files` made a missing graph.json
  patch instead of rebuild), `test_prepare_uv_tool_disables_mcp_before_stop` and
  `test_watchdog_skips_auto_start_by_default` (read the developer's live processes),
  `test_search_returns_warming_without_blocking_embedder` (stale expectation since 8c4c7f5).

Full suite: see "Full suite (final)" below.

---

## New findings (not in the handoff list)

- **Embedder wedge after an idle demote (fixed).** Found in the 0.3.132 battery: after
  `memory demote: tier=locate_only`, `/v1/search` answered `dense_embed_loading` forever and
  the keeper logged `embedder cold — defer` every 2s. A `_LazyEmbedder` held outside
  `_ENGINES` kept its weights through `release_embedders()` and served `embed_one` without
  registering, so `embedder_is_loaded()` stayed False (and the demote freed nothing). Fix:
  wrappers are tracked in a WeakSet and all unloaded; a wrapper that still has weights
  re-registers them; the keeper stops deferring after 30s (`CTX_SYNC_COLD_DEFER_MAX_S`).
  Tests: `tests/test_embedder_wedge.py`.
- **Deleted files stayed searchable / ghost re-marks (fixed).** Chunk-only ghosts were
  re-marked as saves every second, which also held every graph catch-up forever.
  `_corpus_ghosts` + force_files treats a missing file as removed. `tests/test_corpus_ghosts.py`.
- **BM25 lag on hot patches (fixed, issue 4 cause 1).**
- Windows canonical paths are lower-case with backslashes; probe files must be named in
  lower case to match merkle keys.
- Two leftover `.graph.json.*.tmp` files (0.6MB, 18.8MB) from crashed writes; now swept
  after 10 minutes by the graph worker.
- `[keeper] deferred vector save failed: [WinError 32] … turboquant.npz` seen once before
  the fixes; not seen in the 0.3.132 battery.
- `scubiee engine stop .` prints five `Win32 exception occurred releasing IUnknown` lines
  (COM teardown in the CLI); the WMI COM objects are now released before
  `CoUninitialize`.
- ~130 per-session stores accumulate under the repo runtime dir; invalidation is cheap now
  but nothing prunes them.

## Files changed (all issues)

New: `packages/pipeline/{index_generation,engine_log,engine_boot,graph_merge_worker,fast_stat}.py`,
`packages/pipeline/upgrade_releases/v0_3_132.py`; scripts `map_staleness_probe.py`,
`engine_bridge_exit_probe.py`, `enable_wer_localdumps.ps1`, `engine_commit_breakdown.py`,
`graph_catchup_probe.py`, `graph_merge_profile.py`, `prewarm_phase_probe.py`,
`keeper_stall_sampler.py`, `keeper_stack_logger.py`, `root_probe_convoy_bench.py`,
`estimate_cost_bench.py`, `chunk_digest_drift_probe.py`, `reinstall_survival_probe.py`.
Changed: `packages/pipeline/{ce_service,repo_runtime,map_result_cache,mcp_locate,mcp_response_lean,daemon,server,process_control,process_job,watchdog,store_lock,engine,resources,settings,embedder,incremental,merkle,store,project_id,artifact_guard,sync_loop,root_probe,ignore,session_store,chunk_merkle,warm_autoload}.py`,
`packages/conductor/bm25_index.py`, `packages/pipeline/upgrade_releases/__init__.py`,
`scripts/sync-uv-install.ps1`, `pyproject.toml`, `npm/package.json`.
New tests: `test_map_cache_generation, test_engine_lifecycle_audit, test_corpus_ghosts,
test_bm25_append, test_hot_lane_ram_guard, test_manifest_reuse, test_graph_catchup_async,
test_prewarm_stamp_locked, test_fast_stat, test_embedder_wedge`.

## Full suite (final)

`pytest tests -q -p no:cacheprovider` (no `-x`, PYTHONPATH unset, engine + bridge live):
**1979 passed, 17 failed, 11 skipped** in 21m54s.

Fail on a clean `HEAD` worktree too (pre-existing, not touched here) — 13:
`test_auto_sessions_observability::test_client_injects_workspace_and_optional_session_telemetry`,
`test_e2e_pipeline::test_full_pipeline_stores_in_faiss_collection`,
`test_lifecycle_ownership::test_attach_mcp_session_is_nonblocking`,
`test_locate_quality_combo::test_polytrace_prefers_poly_trace_over_faction`,
`test_mcp_exploration_regressions::test_client_retries_transient_url_error`,
`test_mcp_lifecycle_universal::test_warm_engine_for_mcp_waits_for_embedder`,
`test_multi_seed_v1` ×3 (`seed_covered_by_heatmap_and_light`, `seed_specs_from_args_dedupes_and_caps`,
`merge_agreement_boosts_shared_nodes`), `test_polytrace` ×2 (`mean_f1_and_recall_hit_95`,
`job_run_follows_generic_execute`), `test_vague_prompts::test_oracle_polytrace_holds_on_vague_prompts`,
`test_verify_board::test_poly_embed_matches_polytrace_correctness`.

Environment only — pass with `PYTHONPATH=<repo>\packages` (the subprocess they spawn cannot
import `pipeline` from the repo `.venv`) — 3:
`test_dashboard_api::test_background_server_reuses_pid_and_stops`,
`test_lifecycle_simulation::test_watchdog_child_stays_alive_then_exits_clean`,
`test_pythonw_mcp_stdio::test_pythonw_mcp_bridge_initialize_roundtrip`.

Order-dependent — passes alone — 1:
`test_mcp_agent_warm_retry::test_client_for_returns_warming_without_force_restart`.

The MCP-config guard logged no restores in this run, so the test that stubbed
`.cursor/mcp.json` in the earlier run was not identified; the guard stays in place.
