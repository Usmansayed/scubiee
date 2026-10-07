# Scubiee scenario test results (HIGH-priority rows)

Executed the HIGH-priority scenarios from `docs/scubiee-scenario-test-matrix.md`
via `scripts/perf/scenario_sim.py` on **Windows / DirectML, scubiee 0.3.143**.
Safe-by-design: all file churn in a throwaway `scripts/perf/_scenario/` dir
dirtied over `/v1/dirty` — real git history and the working tree were untouched.

**Verdict: all 5 HIGH-priority scenarios PASS. One real bug (staging-dir leak on
killed reindex) was surfaced by E3 and fixed.**

| Scenario | What it proves | Result |
|---|---|---|
| D2 big pull (within caps) | a ~300-file pull all becomes searchable, engine never drops, no oversize refusal | **PASS** |
| D3 huge pull (beyond caps) | an over-cap change-set is **surfaced** (refusal), never silently half-published; old index keeps serving | **PASS** |
| E3 interrupted reindex | killing `index --force` mid-run leaves the old generation intact (no torn index); engine recovers | **PASS** (+ leak fixed) |
| B4 idle → requery | first query after an idle gap is correct | **PASS** |
| F3 query during promote | queries during a staged blue/green promote stay coherent (never torn/empty) | **PASS** |

Global invariants held in every scenario: **G1** no crash (0 fatal log lines),
**G2** `/health` coherent, **G3** no confident-empty, **G4** no torn generation.

---

## D2 — big pull within caps  ✅
300 throwaway files created and dirtied at once (a pull-sized batch, well under
the 25k-touch / 10k-chunk caps), then one `/v1/sync`.
- `sync_strategy: deferred`, `sync_error: null`, **no oversize refusal**.
- Sampled 5 tokens across the batch (first/mid/last/quartiles): **5/5 visible**.
- **0 health-down polls** across the 90s settle; engine alive after; 0 fatal.

## D3 — huge pull beyond caps  ✅
The daemon runs with default caps, so the exact guard path was exercised **inline
in a subprocess** with the caps lowered to 5 (env honored at import, store never
mutated because the guard refuses before any write). 16 changed files vs cap 5:
- Engine surfaced the refusal: `Safety pause: 16 files would be indexed (cap 5).
  Re-run with --confirm …` — the `IndexConfirmRequired` touch-cap path.
- `not_false_published: true` (nothing was published).
- The **old index kept serving** before and after (`def grep_scan` found both times).
- This is the explicit anti-regression for the old BUG-1 "17308 chunks exceeding
  10000 → publish nothing silently": the over-cap case now *tells the user* and
  keeps serving, rather than silently going stale.

## E3 — interrupted reindex  ✅ (surfaced + fixed a real leak)
Started `scubiee index . --force`, let it run 20s into the staged build, then
`kill`ed the process.
- **Old index still served** (`def promote_staged_store` found) — the staged
  build writes to `<base>.staging-<pid>/`, never the live store, so a hard kill
  can't produce a torn generation. **G4 held.**
- Engine alive after; 0 fatal lines.

**Real bug found:** a hard kill skips the `finally` cleanup, so the staging dir
(`<base>.staging-<pid>/`) and `<collection>__staging_<pid>` are **orphaned** —
they accumulate on disk over repeated interruptions (a slow leak; small here
because the kill was early, but a kill during embedding leaves hundreds of MB).

**Fix (`packages/pipeline/indexer.py`):** `index_repo_staged` now calls
`_sweep_stale_staging()` at the start — it removes any `*.staging-<pid>` dir and
`*__staging_<pid>` collection whose **owner pid is no longer alive**
(`_pid_alive()`, cross-platform: `OpenProcess`/`GetExitCodeProcess` on Windows,
`os.kill(pid,0)` on posix). Live/concurrent indexes are left alone.
**Verified:** swept 4 pre-existing orphans → 0; after a kill, the next index
sweeps the dead-pid orphan (self-healing); a clean index leaves 0.

## B4 — idle → requery  ✅
60s idle gap, then a locate for `canonical_relpath`: **1 hit in 783ms**, engine
alive, 0 fatal. The demote/re-warm cycle serves correctly after idle.

## F3 — query during promote  ✅
A continuous querier (`def grep_scan`, every 0.3s) ran through a full
`index . --force` staged promote:
- **1217 queries OK, 0 false-empty, 0 errors.**
- The blue/green atomic swap never exposed a torn or empty read — a query either
  saw the old coherent generation or the new one. **G3 + G4 held.**

---

## What's still TODO (from the matrix, lower priority / needs its own harness)
- **G7 / G11** — corrupt-manifest / power-loss (`kill -9` mid-write) recovery.
  Partially covered by E3 (killed reindex is safe), but a kill *during the live
  chunk write* (not the staged build) should be tested against a copied store.
- **F1 / F4** — two IDEs / multi-repo isolation.
- **H2 / H3** — large-repo scale (10k+ files) and all-day edit volume.
- **C5 / C6** — rename, rapid-save debounce burst.
- Re-run this suite on **macOS** via the committed `scenario_sim.py`.

## How to re-run
```
scubiee engine start --wait 90
python scripts/perf/scenario_sim.py            # all 5
python scripts/perf/scenario_sim.py D2 F3      # a subset
```
Report: `scripts/perf/_scenario_result.json`.
