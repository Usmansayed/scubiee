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

## Follow-up / improvement opportunities (not yet done)

- **Pre-chunk size guard.** The barren cap bounds the damage to N attempts, but a
  36k-line file still burns ~290s × N before quarantine. A cheap per-file
  line/byte guard in the chunk/collect path (skip + quarantine files over, say,
  ~20k lines) would avoid the wasted work entirely. Deferred to keep the fix
  blast radius small (changing the chunker risks altering indexing for
  legitimately large files).
- **Dense-embed throughput at scale** (300-file / huge-file drain time) is
  dominated by the cold-embedder defer + per-chunk embed cost; worth profiling if
  faster catch-up is desired.
- **Delete/rename prune latency.** An offline folder rename (40 delete + 40 add)
  takes >2 min for the delete-half to fully disappear from search, because the
  removals drain in ~25–45s bulk cycles interleaved with the adds. The content is
  correct throughout (search_usable), but old paths linger longer than ideal.
  Prioritizing the delete-half (prune before/alongside the add-half) would make a
  rename reflect faster. Correctness is fine; this is a latency improvement.

## How to re-run
```
# engine must be enrolled; harness starts it if down
python scripts/perf/adversarial_mcp_stress.py            # all 8
python scripts/perf/adversarial_mcp_stress.py S1 S6      # a subset
python scripts/perf/adversarial_mcp_stress.py S2 S4 --keep
```
Report: `scripts/perf/_adv_stress_report.json`.
