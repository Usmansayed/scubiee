# Scubiee open issues — handoff to Kiro (2026-09-27)

Every issue below is **confirmed still open**: seen live, or proven by the code, with no fix
in the tree. Scubiee is not beta-ready until these are closed.

Working split:

- **Kiro:** web research → root cause (with sources) → code → unit tests → script-based
  live testing against the installed engine. Write results to
  `docs/kiro-open-issues-2026-09-27-results.md`.
- **Cursor agent:** final verification through the real Scubiee MCP tools in Cursor.

Rules:

1. Unit tests alone never close an issue. Each fix needs a live script run with measured
   timings and ok flags pasted into the results file.
2. For each issue: links to what you found, a one-or-two-sentence root cause, then code.
3. Do not commit or push. Do not wipe `~/.scubiee` or the project store.
4. Do not edit tracked source while a probe script runs. Delete `packages/pipeline/zz_*`
   leftovers after a killed probe.
5. The working tree has a lot of uncommitted work. Build on it; do not revert it.

---

## 1. `map` returns stale results after an edit (up to 5 minutes)

**Proof (code).**
- `packages/pipeline/mcp_locate.py` ~line 4521 calls
  `get_map_cached(repo=..., query=..., fingerprint="soft_v1")`. The fingerprint is a
  constant, so it never changes when the index changes.
- `packages/pipeline/map_result_cache.py` `get_map_cached`: the `_LAST` path ignores the
  fingerprint entirely and returns anything younger than `CTX_MAP_RESULT_CACHE_TTL_S` (300s).
- `clear_map_cache()` exists but nothing calls it.
- Second cache: `mcp_locate.py` `_map_cache_get` / `_map_cache_put` (session-store
  `map_cache`, used for "duplicate" queries) has no generation or TTL check.
- The MCP locate process and the engine are separate processes, so the engine cannot
  clear the MCP's in-memory cache when it publishes.

Agents often edit, then re-map with the same query to confirm. They get pre-edit cards.

**Build.** Key both caches on the engine's index generation (`/health` → `generation`;
every publish bumps it). Keep the repeat-query fast path fast and measure its cost.

**Research.** Generational cache keys / version-stamped invalidation; how local code
search tools invalidate query caches on reindex.

**Pass.** New `scripts/map_staleness_probe.py`: map query Q → add a function with a
unique token to a scratch file → wait for `generation` to increment → map Q again. The new
function must appear within 1s of the bump, 5/5 runs. An unchanged repeat must still be a
cache hit (report its timing).

## 2. Engine dies silently; ONNX Runtime access violation

**Seen live.**
- During a probe run the engine PID changed twice. Later the engine was gone: no
  `~/.scubiee/engine.lock`, nothing listening on `127.0.0.1:8765`. The watchdog was gone
  too: `~/.scubiee/watchdog.log` went silent after 12:59:40, and nothing restarted the
  engine. `engine.log` has no traceback. Kiro's MCP bridge processes had spawned at
  12:59:20, right at the first PID change.
- Windows Application log:

```
13:34:25  Faulting application: C:\Users\usman\Miniconda3\pythonw.exe (3.13.5150.1013)
          Faulting module: onnxruntime_pybind11_state.pyd   Exception 0xc0000005   pid 28464
```

  This happened around a manual `scubiee engine stop .` + `engine ensure .`. It is likely a
  crash while the ONNX/DirectML session is torn down. The earlier disappearance left no
  crash event, so something probably terminated that process.
- Engine start log shows `[engine] job join note: {'ok': True, 'joined': False, 'reason': 'winerr=5'}`.
- `engine.log` has **no timestamps**, which makes timelines guesswork.

**Find / build.**
1. Add a timestamp to every `engine.log` line.
2. Every code path that stops or kills an engine or watchdog must log a timestamp, the
   caller PID and a reason. Look in `watchdog.py`, `runtime_controller.py`,
   `lifecycle_runtime.py`, `mcp_lifecycle.py`, `warm_contract.py`, and MCP bridge startup.
3. ORT crash on shutdown: research onnxruntime GitHub issues (access violation /
   0xc0000005 / crash on exit / session release, DirectML EP, Windows) and apply the
   mitigation the sources support.
4. Why the watchdog died with the engine: check the job object setup (`winerr=5`,
   kill-on-close, breakaway flags).
5. Enable WER LocalDumps so the next crash leaves a dump.

**Pass.** With `scripts/engine_mem_monitor.py` running: zero unexplained PID changes
across 3 rounds of `disk_save_probe.py`, `engine_kill_recover_probe.py`, and 10×
`scubiee engine stop .` / `engine ensure .`. After that, zero new `onnxruntime` APPCRASH
events. Also a 15-minute idle with Cursor and Kiro MCP bridges connected. Every stop or kill
must be logged with a timestamp and reason.

```powershell
Get-WinEvent -FilterHashtable @{LogName='Application'; ProviderName='Application Error'; StartTime=(Get-Date).Date} |
  Where-Object { $_.Message -match 'python' } | Format-List TimeCreated, Message
```

## 3. Low-RAM guard stalls saves for up to 120s; engine commits ~4GB

**Seen live.** `engine.log` filled with
`[resources] embed waiting pressure=critical almost no free RAM — pause to avoid OOM`
while saves did not become searchable. Measured during one probe round on this 15.7GB
machine (Cursor, Kiro and Chrome open):

- system available RAM: min **171MB** (often 2.5–3.2GB)
- engine RSS 0.9–1.34GB; engine private (committed) bytes **3.56–3.98GB** for 7.5k chunks

**Code.** `packages/pipeline/resources.py`: `classify()` returns `critical` when
available RAM < `min_free_ram_mb`. Then `budget()` sets `allow=False` and
`wait_for_capacity()` blocks up to 120s. The threshold defaults disagree: 256 in
`resources.py` (`CTX_RM_MIN_FREE_RAM_MB`) vs 512 in `packages/pipeline/settings.py`.
A hot save embeds 1–45 chunks, a few MB at most.

**Build.** Small hot-lane embeds (e.g. ≤64 chunks) wait at most ~1s on the guard; bulk
indexing keeps the current behaviour. Make the defaults consistent. Find what the ~4GB
commit is: the model, the ORT arena, the vector matrix, or the per-save `np.vstack` copy in
`engine._patch_chunk_delta`. Reduce it.

**Research.** ONNX Runtime memory settings (`enable_cpu_mem_arena`,
`enable_mem_pattern` — off for DirectML, arena extend strategy); FastEmbed session
options; `psutil.virtual_memory().available` semantics on Windows.

**Pass.** Monitor running, normal apps open, 3 rounds of `disk_save_probe.py`: zero
`embed waiting pressure=critical` lines for hot saves. Report engine private bytes before and after.

## 4. Save → searchable is 3–8s (SLA 5s; target ≤3s for small files)

**Seen live** (one round of `disk_save_probe.py`, plain disk writes, no `/v1/dirty`):

| Step | Time to searchable |
|---|---|
| New file in existing folder | 5.5s |
| Edit big file (~1600 lines) | 7.9s |
| New file in a new folder | 5.1s |
| Delete a file | 3.4s |
| Revert the big file | 6.5s |

Stage lines from `engine.log` (`[keeper] hot sync ...`):

| Save | debounce_ms | embed_ms | reconcile_ms | invalidate_ms | sync_ms | total_ms |
|---|---|---|---|---|---|---|
| new small file | 1112 | 319 | 490 | 1789 | 1902 | ~3.7s |
| big file edit (44 chunks) | 3174 | 2373 | 503 | 106 | 4150 | 7859 |
| new file in new folder | 937 | 387 | 644 | 87 | 4102 | 5352 |
| delete | 460 | – | 736 | 122 | 1889 | 3003 |
| revert big file | 3964 | 3 | 658 | 177 | 2385 | 7067 |

**Chase.**
- `debounce_ms` should be ~250ms plus up to 1s of poll interval. 3–4s means the poll or
  keeper was busy; `[keeper] deferred vector save` reached 3684ms. Make sure it cannot
  delay the next save.
- `sync_ms` exceeds the sum of its stages (new-folder case: ~1.5s of stages, 4.1s total).
  Add timers until the stages add up. Suspects: RAM-guard wait (issue 3), GIL contention
  with concurrent `/v1/search`, file I/O.
- `reconcile_ms` 0.5–0.7s on every save and `invalidate_ms` 1.8s on the first. Find out whether
  a hot save needs them synchronously.

**Pass.** 3 rounds of `disk_save_probe.py` (21 samples): all ≤5s, small-file steps
(new_file, edit_small, new_subdir, delete) ≤3s p95. Paste the table and matching `hot sync` lines.

## 5. First edit after upgrade re-embeds the whole file

**Seen live.** The big-file edit re-embedded all 44 chunks (`embed_ms` 2373) although only
one function was added. Reverting the file re-embedded nothing (`embed_ms` 3). Cause:
`chunk_digest` (`packages/pipeline/chunk_merkle.py`) changed format, so every chunk digest
stored before the upgrade mismatches once.

**Build.** A one-time migration: recompute stored chunk digests from the stored chunk
records' `enriched` text (no embedding), guarded by a version field. See
`packages/pipeline/incremental.py` ~line 1053 (`load_chunk_merkle` / `save_chunk_merkle`).

**Pass.** Unit test. Live: restart the engine on an existing store, append one function
to a large copy of a real module. The `[embed] N/N new` line must show ≤3 chunks.

## 6. Graph catch-up takes 8–15s and runs on the save keeper

**Seen live.** After each save the file is re-synced for the graph
(`reason=graph_catchup`, 30s delay, 20s quiet window): `[sync] no chunk delta files=1 ... ms=8060–15599`.
Most of it is `patch_and_save_graph` → `build(dedup=True)`, a whole-graph rebuild (see the
comment in `incremental.py` ~line 926: ~6.7s for 15.9k nodes). The keeper runs one batch at
a time, so a save that lands while a catch-up runs waits behind it.

**Build.** Pick one: make the graph patch incremental (changed file's nodes and edges only);
run catch-ups on a separate worker; or split them so hot work can run between the parts.

**Pass.** Save file A, wait for A's catch-up to start (watch `engine.log`), save file B.
B must be searchable within 5s. Report catch-up duration before and after.

## 7. Reinstall breaks the running MCP server ("Not connected")

**Seen live.** After `scripts/sync-uv-install.ps1`, Cursor's Scubiee MCP reported
`Not connected` until MCP was reloaded. The uv reinstall replaces site-packages under the
running `pipeline.mcp_bridge` / `pipeline.mcp_locate` processes. Beta users upgrading will
hit this.

**Build.** The bridge detects a version change or failed worker import and respawns the
worker while keeping the host's stdio connection. At minimum, the upgrade command tells the user
to reload MCP. Research how MCP hosts (Cursor, Kiro, Claude Code) behave when a stdio
server's child restarts.

**Pass.** With a bridge connected (`scripts/mcp_host_sim.py --lane a --live` or
`scripts/hold_mcp_bridge.py`), run the sync-install. The next tool call through the same
session succeeds without restarting the host.

## 8. `ConnectionAbortedError` traceback spam in `engine.log`

**Seen live.** Each client that disconnects mid-response logs a full traceback:
`packages/pipeline/server.py` `_json` → `handler.wfile.write(body)` → `[WinError 10053]`.
It hides real errors.

**Build.** Catch `ConnectionAbortedError` / `ConnectionResetError` / `BrokenPipeError`
(in `_json` or the server's `handle_error`) and log one short line at most.

**Pass.** Unit test. After a probe run, zero `ConnectionAbortedError` tracebacks in `engine.log`.

## 9. Two failing unit tests

- `tests/test_live_reindexing.py::test_final_check_forces_held_publish` fails on HEAD as
  well. Find out why and fix it.
- `tests/test_accel_pip_drain.py::test_requirement_satisfied_for_installed_pip` fails
  because the repo `.venv` has no `pip`. Skip the test when pip is absent.

Then run the full suite to completion (`pytest tests -q -p no:cacheprovider`, no `-x`) and
report every failure.

---

## How to test

### Environment (Windows, PowerShell)

- Repo `C:\Users\usman\Downloads\context-engine`; tests use `.\.venv\Scripts\python.exe`.
- The engine and MCP run from the uv tool at `%APPDATA%\uv\tools\scubiee`
  (`& "$env:APPDATA\uv\tools\scubiee\Scripts\python.exe"`).
- Clear `PYTHONPATH` before running installed code or probes: `$env:PYTHONPATH=$null`.
- Every command prints two harmless `pydantic ... logfire-plugin` warnings. Ignore them.
- Engine `http://127.0.0.1:8765` (`/health`, `/v1/status`, `/v1/search`).
- Logs `~/.scubiee/engine.log`, `~/.scubiee/watchdog.log`. Store
  `~/.scubiee/projects/ce_3536ac8e8e83bb8e4d888db37847729c`.
- Idle standby stops the engine when no client is connected. Probes touch
  `/v1/client/touch`; for manual sessions run `python scripts/hold_mcp_bridge.py --seconds 1800`.

### Loop for every change

```powershell
# 1. unit tests
.\.venv\Scripts\python.exe -m pytest tests/test_root_probe.py tests/test_live_reindexing.py `
  tests/test_dirty_ledger.py tests/test_chunk_merkle.py tests/test_runtime_publish.py `
  tests/test_open_preservation.py tests/test_sync_corpus_alignment.py tests/test_wipe.py `
  tests/test_watcher_recovery.py tests/test_sync_status_canaries.py -q -p no:cacheprovider

# 2. install into the uv tool; must print "differ: 0  missing: 0" and "OK"
powershell -ExecutionPolicy Bypass -File scripts/sync-uv-install.ps1
#    (after a FULL reinstall instead: scubiee setup --repair --skip-model --skip-bench)

# 3. restart the engine on the new code
$env:PYTHONPATH=$null; scubiee engine stop .; scubiee engine ensure .
Invoke-RestMethod http://127.0.0.1:8765/health   # warm_state=ready, embedder_loaded=True

# 4. monitor in a second terminal for the whole battery
$env:PYTHONPATH=$null; & "$env:APPDATA\uv\tools\scubiee\Scripts\python.exe" scripts/engine_mem_monitor.py $env:TEMP\engine_mem.jsonl

# 5. live scripts, then paste numbers into the results file
```

### Scripts

| Script | Proves | Command | Pass |
|---|---|---|---|
| `scripts/disk_save_probe.py` | Real editor saves (disk writes only) become searchable: new file, second save to it, new big file, big edit, new folder, delete, revert | `$env:PYTHONPATH=$null; .\.venv\Scripts\python.exe scripts/disk_save_probe.py . 3` | `SUMMARY 21/21`, no PID change |
| `scripts/edit_repro.py` | Second save to the same file is picked up (regression check) | `.\.venv\Scripts\python.exe scripts/edit_repro.py .` | generation increments and `zzbeta…` hit within 5s of "wrote v2" |
| `scripts/engine_mem_monitor.py` | Engine PID stability, RSS/private bytes, free RAM | step 4 | no PID change; report min free / max private |
| `scripts/mcp_host_sim.py` | MCP host simulation Lane A (bridge stdio, tools, settle/idle) | `... scripts/mcp_host_sim.py --lane a --live` | all ok flags; report timings |
| `scripts/warm_contract_acceptance.py` | Warm/standby contract | `... scripts/warm_contract_acceptance.py` | ok |
| `scripts/scubiee_mcp_ship_check.py` | MCP ship gate | `... scripts/scubiee_mcp_ship_check.py` | ok |
| `scripts/engine_kill_recover_probe.py` | Watchdog restores a killed engine | `... scripts/engine_kill_recover_probe.py --budget-s 120` | recovers in budget |
| new `scripts/map_staleness_probe.py` | Issue 1 | Kiro writes it | 5/5 |

Log grep after a run:

```powershell
Get-Content $env:USERPROFILE\.scubiee\engine.log -Tail 3000 |
  Select-String "\[keeper\] hot sync|no chunk delta|\[publish\]|embed waiting|Traceback"
```

### Results file

`docs/kiro-open-issues-2026-09-27-results.md`: per issue, the sources used, root cause,
files changed, tests added, and raw script output (per-step ms, ok flags, PID stable,
min free RAM, max engine private bytes) plus the matching `hot sync` log lines. State
plainly what still fails.
