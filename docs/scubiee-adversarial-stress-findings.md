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

## Harness artifact (not a product bug)

The harness's G4 check originally compared the `/health` `generation` field,
which is a **volatile in-memory counter that resets on every engine restart**.
Since every stop/start scenario restarts the engine, the counter appeared to go
backward (5→3→1). Fixed the harness to read the **durable** generation
`(epoch, counter)` from `index_state.json`, which is monotonic within an epoch
(an epoch change is a legitimate new engine identity). The task-1 monotonic
guarantee was never violated.

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

## How to re-run
```
# engine must be enrolled; harness starts it if down
python scripts/perf/adversarial_mcp_stress.py            # all 8
python scripts/perf/adversarial_mcp_stress.py S1 S6      # a subset
python scripts/perf/adversarial_mcp_stress.py S2 S4 --keep
```
Report: `scripts/perf/_adv_stress_report.json`.
