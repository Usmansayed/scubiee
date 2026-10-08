# Scubiee adversarial MCP stress — findings

Ran an adversarial stress harness (`scripts/perf/adversarial_mcp_stress.py`)
against the **real** Scubiee engine + **real** `scubiee-mcp-bridge` (the same
binary/env Kiro launches, via `mcp_host_sim.BridgeHost`). Eight scenarios try to
break the engine in distinct ways; global invariants are checked after each.

All churn happens in a throwaway subtree (`scripts/perf/_adv/`), removed and
reconciled out at the end. The live index/source are never touched.

## Scenarios

| ID | Name | What it attacks |
|----|------|-----------------|
| S1 | big_offline | 300 files added while engine OFF → reopen must reconcile + surface substantial |
| S2 | flap | rapid open/close bridge connect-storm |
| S3 | crash_mid_index | hard-kill the engine mid offline-reconcile drain |
| S4 | concurrent | 3 bridges (distinct hosts) hammer map/status concurrently |
| S5 | rename_storm | rename a whole folder while OFF (40 deletes + 40 adds) |
| S6 | huge_file | one ~36k-line / ~12k-function file added while OFF |
| S7 | churn_in_warm | add files DURING warm to race the reconcile walk |
| S8 | mixed_cycles | 2 back-to-back add+modify+delete offline cycles |

Global invariants (G1 no crash, G2 /health coherent, G3 no confident-empty on a
known symbol, G4 durable generation monotonic, G5 no fatal log lines, G6 pending
contract sane).

## Results

| Scenario | Verdict | Notes |
|----------|---------|-------|
| S2 flap | **PASS** | 8/8 opens OK, no wedge, no crash |
| S4 concurrent | **PASS** | 24/24 map OK, 24/24 status OK, 0 errors across 3 hosts |
| S7 churn_in_warm | **PASS** | both pre-warm and added-during-warm files searchable — no files lost to the race |
| S1 big_offline | **PASS (after fix)** | now surfaces substantial pending for a 300-file paste |
| S6 huge_file | **FIXED** | was an infinite retry loop; now quarantines after a cap |

## Bugs found and fixed

### BUG 1 — large file-count paste under-estimated → stayed silent (fixed)
A 300-file offline paste estimated ~15s of work and classified as **not
substantial**, so the agent-facing `pending` contract stayed silent — yet the
batch genuinely took ~150s to drain. The workload estimate counted only chunk
content and ignored per-file pipeline overhead (parse, graph participation,
session invalidation, publish), which scale with the *number* of files.

**Fix** (`packages/pipeline/workload.py`): added `PER_FILE_OVERHEAD_UNITS`
(default 10 ≈ 0.5s/file at 20 cps) to `estimate_units`. 300 tiny files now
estimate ~165s → substantial; a handful of small edits stay silent. Also set the
pending `total_units` to the estimated embed units (not the raw file count), so
`done/total` is a meaningful progress fraction. Tests:
`tests/test_workload.py` (`test_many_tiny_files_is_substantial_via_per_file_overhead`,
`test_a_dozen_small_files_still_silent`).

### BUG 2 — infinite retry loop on an unindexable file (fixed) — SEVERE
A single pathologically large file (~36k lines, ~12k functions) wedged the
background keeper in an **infinite retry loop**. The engine log showed, forever,
every ~4–5 minutes:

```
[keeper] bulk sync starting: 1 files in ~1 sub-batches [bulk_slice]
[keeper] bulk sync done: 0 upserted, 0 removed in 291071ms (0 sub-batches)
```

The file spent ~291s in `incremental_sync`, produced 0 chunks, was re-queued,
and retried indefinitely — never indexed, keeper pinned.

**Root cause:** `sync_loop._bulk_sync_paths` only escalated when the result
strategy was exactly `"explicit_full_index_required"`. A huge/failing file
returns `strategy="incremental"` (or `"none"`, or raises), so it fell through to
the `else` branch (re-queue `bulk_deferred`) — or the `except` branch (re-queue
`bulk_retry`) — with **no retry cap**. Both branches looped forever. There is no
pre-chunk file-size guard, so the file was never skipped.

**Fix** (`dirty_ledger.py`, `dirty_journal.py`, `sync_loop.py`): added
`DirtyEntry.fail_attempts` + `DirtyLedger.note_barren()`. In both the barren
`else` branch and the `except` branch, a sub-batch that produces 0 upserted / 0
removed (or raises) now increments a barren counter; after
`CTX_BULK_BARREN_CAP` (default 3) attempts the path is **quarantined**
(`complete()`-d out of the ledger) and `needs_full` is set, so the ledger drains
and the keeper stops looping. The file simply stays unindexed (search still
serves everything else) and the gap is surfaced via `needs_full` + an error
string pointing at `scubiee index . --force`.

Resource-pressure deferrals (`strategy="deferred"`) do **not** count toward the
cap — they are expected to clear and must keep retrying.

**Subtlety:** the retry re-queue uses `defer()` not `mark()`. `mark()` on a
non-queued entry creates a fresh `DirtyEntry`, resetting `fail_attempts`, so the
cap could never be reached; `defer()` flips state back to queued in place and
preserves the counter.

Tests: `tests/test_bulk_barren_quarantine.py`
(`test_barren_file_is_quarantined_after_cap_not_looped`,
`test_resource_deferral_does_not_count_toward_barren_cap`).

## Second batch — S3 crash, S5 rename, S8 mixed cycles

| Scenario | Verdict | Notes |
|----------|---------|-------|
| S3 crash_mid_index | **PASS** | hard-killed the engine mid offline-reconcile of 120 files; watchdog restarted it, reconcile-from-journal recovered, generation monotonic, no fatal logs |
| S5 rename_storm | **PASS** (invariants) | rename detected correctly as delete+add; old-path prune is slow (see below) |
| S8 mixed_cycles | **PASS** | 2 back-to-back add+modify+delete offline cycles, engine coherent throughout |

With the earlier batch, **all 8 scenarios pass invariants** against the real MCP.

### S5 deep-dive — rename detection is correct; prune is slow (not broken)

An initial corrected probe showed the OLD `s5_old/` paths still searchable 128s
after an offline folder rename, which looked like a prune failure. Investigation:

- **Detection is correct.** An isolated repro of `root_probe(discover_newcomers=True)`
  on a renamed folder returns the old paths in `removed` and the new paths in
  `added` (rename = delete + add). The reconciler enqueues both halves.
- **The removals DO publish** — the engine log shows `removed=165` / `removed=200`
  bulk cycles pruning the old paths. They are not lost.
- **They drain slowly**, interleaved with the add-half and (in the contaminated
  multi-scenario run) a large accumulated backlog, so the old content stayed
  searchable past the 128s probe window. This is the **same `search_usable`
  during-reconcile behavior** as the big-batch case: the current generation keeps
  serving old content until the delete-half's generation publishes. Correct, but
  slow — see the drain-throughput follow-up below.

## Harness artifacts fixed (not product bugs)

Three harness weaknesses produced misleading verdicts and were corrected so the
harness is trustworthy:

1. **G4 generation check** compared the `/health` `generation` field — a volatile
   in-memory counter that resets on every engine restart (so stop/start
   scenarios appeared to move it backward 5→3→1). Fixed to read the **durable**
   `(epoch, counter)` from `index_state.json`, monotonic within an epoch. The
   durable guarantee was never violated.
2. **G5 fatal-log filter** matched the literal substring `crash` inside scenario
   FILE PATHS (`s3/crash_0.py`) and flagged benign `client gone mid-response`
   disconnects as fatal. Fixed to match only genuine fatal signals (real
   tracebacks, segfaults, `fatal:`/`unhandled exception`/`panicked`) and skip the
   known-benign lines.
3. **S5 old-path check** snapshotted once at the moment `index_fresh` first
   flipped, before the delete-half had drained. Fixed to poll until the old path
   disappears (up to ~2 min) and to inspect returned PATHS, not shared body text
   (a rename keeps content identical in both paths).

## Reliability hardening — the three follow-ups, now FIXED

### 1. /health stayed responsive under embed load (fixed — GIL investigated, no process split needed)
`/health` used to time out while the engine embedded a large backlog. The
initial hypothesis was GIL starvation: the HTTP thread (ThreadingHTTPServer)
contending with the embed loop. **That hypothesis was tested and disproved.** A
GIL-heartbeat probe (a tight Python-level timer thread sampling its own wake
latency) ran *through* a 9.5s DML embed batch and saw **p99 = 11ms** — the embed
runs in native fastembed/ONNX-Runtime code that releases the GIL, so a pure
Python HTTP handler is **not** starved. A separate `/health` process was
therefore **not** built; it would add failure modes (a second lifecycle, IPC,
split warm-state) for no measured benefit.

The real cost was disk I/O on the hot path: `health()` did two `peek_project`
disk reads + an `index_state.json` read per request. Fix (`ce_service.py` +
`server.py`):
- **Background health refresher** (`_start_health_refresher` /
  `_refresh_health_disk_snapshot`): a daemon thread recomputes the disk-touching
  bits (project ref, `agent_pending`, cold `index_is_usable`) and the full
  `_compute_health()` payload every `CTX_HEALTH_REFRESH_S` (1s). The request path
  does **zero disk I/O** once warm — it serves the prebuilt payload. Rollback:
  `CTX_HEALTH_REFRESHER=0` (falls back to inline TTL-cached compute).
- `_health_disk_snapshot()` TTL-caches the disk bits (`CTX_HEALTH_CACHE_TTL_S=2`)
  and `health()` serves the last payload when <1s stale
  (`CTX_HEALTH_PAYLOAD_TTL_S=1`) as a backstop if the refresher is disabled.
- HTTP transport hardening on `EngineHTTPServer`: access logging gated behind
  `CTX_HTTP_ACCESS_LOG` (default off — no per-request log formatting on the hot
  path), `daemon_threads`, `disable_nagle_algorithm` (TCP_NODELAY), and
  `request_queue_size=128` so connect storms queue instead of resetting.

Verified on the **real MCP**: realistic 2s poll cadence **29/29 OK, 0 timeouts,
p50 24ms**; an aggressive 0.2s connect storm held **0 timeouts, p50 19ms** with
only a rare ~1% tail from thread churn (not GIL, not production cadence). The
`test_health_request_path_does_no_disk_io_once_warm` test proves 0 `peek_project`
calls across 50 reads once warm.

### 2. delete/rename prune latency (fixed)
`_additions_before_deletions` returned `present + missing` (adds first), so a
rename's deletes waited behind the embed-heavy add-half. Fix (`sync_loop.py`):
return `missing + present` (deletes first) — a delete carries no embedding, so a
renamed-away path disappears from search almost immediately. Hot saves are still
prioritized (they go through `_split_explicit_writes` as `writes`, ahead of the
backlog, before this ordering matters). Rollback: `CTX_DELETES_FIRST=0`.

### 3. pre-chunk size guard for pathological files (fixed)
A ~36k-line file burned ~290s per sync attempt on the AST walk + chunking before
producing 0 usable chunks (and the barren cap then quarantined it after N
attempts). Fix (`incremental.py`): `_oversized_file()` + a filter right after
`_paths_for_files` drops files over `CTX_MAX_FILE_LINES` (25000) /
`CTX_MAX_FILE_BYTES` (2 MB) **before** `extract()`. The skipped file stays in
`touch_set` so the no-delta branch records its merkle hash (handled —
`root_probe` never re-reports it) and clears any stale chunk-merkle entry.
Verified live: `[sync] skip oversized file …/s6_huge.py (lines>25000) — not
indexed`, skipped in ~2.8s with `parse_ms=0`, hash recorded, not re-reported.

Tests: `tests/test_reliability_hardening.py` (9 — deletes-first ordering + its
rollback, oversized detection by lines/bytes + disable, health TTL cache hit +
refresh, zero-disk-IO request path, refresher payload freshness). 134 pass + 1
skip across the touched suites after the final consolidated regression.

### 4. attach-return latency when the engine is down (fixed)
`start_attach_warm_pipeline` blocked ~1.5s on every attach when the engine was
not running: `runtime_controller.snapshot()` always issued a `/health` HTTP probe
that sat in the OS connect-refused backoff. Fix (`runtime_controller.py`):
`snapshot(fast=True)` skips the health probe entirely on the attach-return path
and reports state from the lockfile/process signals it already has. Attach-return
dropped from ~1.5s to **~23ms**. The slower full probe is still used where a live
health read is actually needed. (An intermediate `_probe_health(fast=)` signature
change was reverted — it broke two ast-hydrated tests whose monkeypatch lambdas
take only `repo`; the fix lives entirely in `snapshot`.)

### 5. offline ghost prune for disappeared files (added)
`_reconcile_offline` now runs an `offline_ghost_prune` pass: it enqueues the
corpus "ghosts" — paths present in `chunks.jsonl` but gone from disk — that the
merkle-diff `root_probe` can miss when a whole subtree vanishes while the engine
was off. This closes the gap where a bulk offline delete left tombstone-less rows
owed. Removals carry no embedding, so they drain fast (deletes-first ordering,
follow-up #2 above).

## Known-open items (documented, not launch-blocking)

### Offline folder-rename: old paths linger in served search (not data loss)
**Repro:** seed a folder online (let it go fresh), rename the folder while the
engine is OFF, reopen. The old paths are correctly **removed from
`chunks.jsonl` on disk** (verified `..._in_chunks_jsonl=0`), the reconcile logs
`removed=N`, and the graph prunes the old nodes — yet `/v1/search` still returns
the OLD paths for a while.

**Root cause (as far as isolated repro took it):** the removal persists to disk
correctly, but the **served in-memory binder** retains the stale rows.
`_ensure_engine` (ce_service.py) returns `runtime.engine` — the *published*
binder — not the `load_engine` cache, so a `clear_engines()` on the cache does
not refresh what search reads. The full `_publish_runtime` reload path *does*
rebuild a clean binder from disk and clears the staleness; a plain engine restart
clears it too.

**Why it is not fixed in this run:** a speculative `clear_engines()` in the
removal lanes was tried and **did not** fix it (reverted both additions, verified
the sync hot path stayed clean), because the served reference is `runtime.engine`
not the cache. Shipping a blind binder-reload on the removal hot path at the tail
of this hardening run carries real regression risk to the verified-good search
path, for a narrow, self-clearing, non-data-loss edge case.

**Impact / mitigation:** `index_usable` / `search_usable` hold throughout (search
keeps serving the current generation), there is **no data loss** — the on-disk
corpus is correct — and the stale rows clear on the next full publish or an
engine restart. Tracked for a follow-up that reloads the published binder from
disk after a bulk offline removal, with a focused test, rather than a hot-path
guess.

## How to re-run
```
# engine must be enrolled; harness starts it if down
python scripts/perf/adversarial_mcp_stress.py            # all 8
python scripts/perf/adversarial_mcp_stress.py S1 S6      # a subset
python scripts/perf/adversarial_mcp_stress.py S2 S4 --keep
```
Report: `scripts/perf/_adv_stress_report.json`.
