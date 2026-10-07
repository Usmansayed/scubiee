# Scubiee scenario test matrix — real-world situations the engine must handle

**Purpose.** Enumerate, from a **user's perspective**, every situation the Scubiee engine can land
in during normal (and abnormal) use, state the **expected behavior** for each, and give a concrete
**simulation + pass criteria** so we can test the engine thoroughly before production.

**How to read a row.** Each scenario has: *what the user did*, *what should happen*, *how to
simulate it*, and *pass criteria* (what we assert). Scenarios are grouped by lifecycle phase.

**Harness.** `scripts/perf/prod_sim.py` is the automated gate for the perf/stability dimensions.
Many scenarios below are new and need their own small probes (noted). All HTTP via
`http://127.0.0.1:8765`; CLI via `scubiee`. Engine log: `~/.scubiee/engine.log`.

**Global invariants (must hold in EVERY scenario):**
- G1. The engine process never crashes (no `Fatal Python error` / `Segmentation` / `0xC0000005`).
- G2. `/health` either returns a coherent payload or is cleanly down→restarting (never a torn/500).
- G3. Search never returns a **confident wrong/empty** answer — an incomplete scan reports
  `complete:false`, a warming engine reports `warming`, never silent emptiness.
- G4. The index is never left in a mixed/torn generation (manifest fail-closed).
- G5. No unbounded growth — `graph_pending`, sessions, memory stay bounded over a long run.

---

## A. First-run / enrollment

| # | User did | Expected behavior | Simulate | Pass criteria |
|---|---|---|---|---|
| A1 | Fresh `scubiee setup` on a new machine | Detect accel profile (dml/cuda/mlx/coreml/cpu), download model once, write `accel.json` | clean `~/.scubiee`, run `setup` | profile written; `setup` prints "Ready"; model cached |
| A2 | `scubiee init .` on a medium repo (~1k files) | Full index built; chunks+merkle+graph+vectors+manifest written; project_id assigned | `init` on this repo | `/health` eventually `index_usable:true`; `.scubiee/id.json` exists |
| A3 | `init` on a **very large** monorepo (>25k files) | Hits the `DEFAULT_MAX_TOUCH=25000` safety gate; asks for `--confirm` rather than silently chewing | point init at a huge tree | returns a confirm-required message, not an unbounded index |
| A4 | `init` on a repo with no git | Works (git is a speed hint only; merkle is source of truth) | `init` a non-git folder | indexes normally; `git_available:false` in freshness |
| A5 | Agent calls `map` before `connect` / on unmanaged repo | Refuses locate, tells agent to use native tools (not a crash) | call `/v1/locate` on an unenrolled path | returns managed=false / use-native guidance |

---

## B. Warm-up / lifecycle

| # | User did | Expected behavior | Simulate | Pass criteria |
|---|---|---|---|---|
| B1 | Cold engine start | soft-ready (BM25/locate) in a few seconds; dense-ready later; no crash | `engine stop` → `start` → poll `/health` | soft_search_ready within budget; **0 crashes over 30 restarts** (done: Win 0/30) |
| B2 | Query **during** warm-up | Returns `warming`/retry, OR serves soft (BM25) results; never a torn/empty-as-absent | hit `/v1/locate` right after start | `status:warming` or valid soft hits; G3 holds |
| B3 | Concurrent clients during warm-up | No crash; some calls may stall/timeout during native prewarm (recoverable), engine stays alive | 8 clients hammer during warm | 0 crashes, 0 conn-closed/5xx; engine alive after (done: Win) |
| B4 | Engine idle for a long time, then a query | Engine may demote/standby to save RAM, then re-warm on demand; first query after idle is slower but correct | leave idle > idle window, then query | query succeeds (maybe after a short re-warm); no error |
| B5 | Watchdog restart after a crash | Engine auto-restarts and re-warms without user action | kill the engine PID | watchdog brings it back; `/health` recovers |

---

## C. Editing (the hot path — most common)

| # | User did | Expected behavior | Simulate | Pass criteria |
|---|---|---|---|---|
| C1 | Save one file (new content) | Searchable within ~1s via the hot BM25 lane | create file → `/v1/dirty` → poll `/v1/grep` | visible ≤ a couple seconds; `probe_sync_battery.py` |
| C2 | Modify an existing file | New content searchable; old content gone | rewrite a file, sync | new token visible, old token gone |
| C3 | Partial edit (delete part of a file) | Removed symbol disappears; kept symbol stays | drop one function, keep another | dropped gone, kept present |
| C4 | Delete a file | Its content no longer returned (grep-gone) | delete a tracked file, dirty it | token gone from results |
| C5 | Rename a file | Old path's content gone, new path's content present | git mv or rename, sync | old path absent, new path present |
| C6 | Rapid save burst (same file saved 10× in 2s) | Debounced; not 10 reindexes; final content correct | loop-write a file fast | final content searchable; no error spin |
| C7 | Save many files at once (e.g. formatter touches 200 files) | Batched incremental sync; all become searchable; no oversize refusal under the cap | write 200 files, sync | all visible; strategy incremental/deferred, no oversize |
| C8 | Save a file with non-UTF-8 / exotic bytes | No decode crash; file handled or skipped gracefully | write a cp1252/binary-ish file | no `UnicodeDecodeError`, engine alive (regression guard for the grep UTF-8 fix) |

---

## D. Git operations (the "big pull" class — the user's example)

| # | User did | Expected behavior | Simulate | Pass criteria |
|---|---|---|---|---|
| D1 | `git pull` touching ~50 files | Incremental sync picks up all changes; searchable within seconds | checkout a branch ~50 files different | all changed files reflected; no oversize |
| D2 | **Big `git pull`** / merge touching thousands of files (but < caps) | Incremental handles it; may take longer but publishes; engine stays serving the old gen until done | hard-reset to a commit far behind | eventually all reflected; engine never down (G2); no torn gen (G4) |
| D3 | **Huge pull** exceeding `AUTO_FULL_INDEX_CHUNKS` (10k) / `MAX_TOUCH` (25k) | Does NOT silently publish a half-index; surfaces `needs_full` / asks for `index --force`; keeps serving the old index as **stale** (not down) | reset across a massive change | `sync-now` reports needs_full/oversize (NOT a false publish); locate still serves old index flagged stale |
| D4 | `git checkout` to a different branch | HEAD change detected; the diff since indexed_head is synced | switch branches | changed files reflected; `detection:git_*` |
| D5 | `git stash` / `git stash pop` | Treated as edits; files re-sync both ways | stash then pop | content correct after each |
| D6 | New branch with many **new** files (newcomers) | Newcomer discovery adds them WITHOUT re-flagging existing files (BUG-1 guard) | add files on a branch, sync | FIXED-newcomer count = only the genuinely new files; `probe_bug1_newcomers.py` = 0 false |
| D7 | `git pull` while the engine is mid-warm | Change queued; applied once warm; no loss | pull right after start | changes eventually reflected, no dropped dirty |

---

## E. Reindex / maintenance

| # | User did | Expected behavior | Simulate | Pass criteria |
|---|---|---|---|---|
| E1 | `scubiee index . --force` while engine serving | Zero-downtime: builds new generation in staging, atomic promote, engine serves old gen throughout | poll `/health` 0.5s during force reindex | **0 DOWN polls** (done: Win 2309/0, mac continuous 200); gen advances; new content served |
| E2 | `index --force` with no engine running | Builds in place, then ensures a serving engine (ensure_daemon handoff) | stop engine, run force index | engine comes UP after (BUG-4 fix) |
| E3 | Interrupt a reindex midway (Ctrl-C / kill) | No torn generation; old index still valid (manifest fail-closed); or clean rebuild on next open | kill mid-index | `index_is_usable` true on old gen, or heals; no mixed-gen serve (G4) |
| E4 | `sync-now --confirm` on a clean repo | No-op (`strategy:none`), no oversize error (BUG-1 guard) | run on an unchanged repo | `strategy:none`, `error:null` |
| E5 | Engine upgrade (new version) while a repo is enrolled | Daemon version-adopts/restarts; index re-validated; stale-index rebuild if extraction version changed | install new wheel, reconnect | engine runs new version; index usable |

---

## F. Concurrency / multi-client

| # | User did | Expected behavior | Simulate | Pass criteria |
|---|---|---|---|---|
| F1 | Two IDEs (Cursor + Kiro) on the same repo | Both served; no corruption; shared index | two MCP clients | both get correct results; no crash |
| F2 | Many parallel locate/grep calls (steady state) | All succeed (admission 409s are retryable); no crash | 8 clients, warm engine | error rate ≤2% with retry (done: 100% w/ retry); engine alive |
| F3 | A query arrives during a publish/promote | Served from the previous coherent gen, then the new one; never a torn read | query while reindex promotes | always a coherent result; G4 |
| F4 | Multiple repos enrolled, switching between them | Each repo's runtime isolated; switching doesn't stop the others | enroll 2 repos, alternate queries | correct per-repo results; no cross-talk |

---

## G. Failure / recovery / edge

| # | User did | Expected behavior | Simulate | Pass criteria |
|---|---|---|---|---|
| G6 | Disk full / write fails mid-sync | Fails safe; doesn't corrupt the index; surfaces an error | simulate ENOSPC (hard) or read-only store | old index still usable; clear error; no corruption |
| G7 | Corrupt / partially-written manifest (killed mid-write) | `index_is_usable` fails closed; republish-if-coherent or heal on next open | truncate the manifest | engine heals or rebuilds; never serves mixed gen |
| G8 | `.scubieeignore` / `.gitignore` changes | New ignore rules honored on next sync; previously-indexed now-ignored files handled | add an ignore rule, sync | ignored files drop from results |
| G9 | A massive generated file (multi-GB) appears | Skipped by size guard; does not stall grep or blow memory | drop a 2GB file in the tree | grep stays fast; no OOM (regression guard for the stat-before-read fix) |
| G10 | Huge repo with a giant ignored dir (e.g. node_modules, .ab_workspaces) | Not walked; grep stays fast and complete | the current repo already has `.ab_workspaces` 435k files | grep p95 < 1s, no false-empty |
| G11 | Engine killed hard (power loss sim) while writing chunks | On restart: heals or rebuilds; no crash loop | kill -9 mid-write | clean recovery; watchdog doesn't crash-loop past the cap |
| G12 | Clock skew / mtime weirdness | Merkle hash (content) is source of truth, not mtime | touch files to future mtime | correct freshness by content hash |

---

## H. Scale / longevity

| # | User did | Expected behavior | Simulate | Pass criteria |
|---|---|---|---|---|
| H1 | 8-hour coding session (sustained churn) | No memory leak, no latency drift, no `graph_pending` ghost buildup | long soak (prod_sim E, extended) | latency drift ≤ ~1.5x; `graph_pending` ghosts = 0; RSS stable |
| H2 | Thousands of tiny edits over a day | Hot lane keeps up; graph catch-up stays bounded | repeated edit/sync cycles | each edit visible ~1s; no backlog explosion |
| H3 | Large repo (10k+ files, 50k+ chunks) | Index builds; search stays fast; memory within budget | index a large repo | map/grep p95 < ~1s warm; dense works |

---

## I. The user's headline examples, spelled out

**"A big pull — how does Scubiee respond?"** → scenarios **D2 / D3**. Expected: for a pull within
the caps, incremental sync absorbs it and the engine keeps serving the old generation until the new
content publishes (seconds to minutes depending on size), never going down. For a pull *beyond* the
auto caps (10k changed chunks / 25k touched files — a massive rebase or submodule bump), Scubiee
**refuses to silently publish a half-index**: it flags `needs_full`, keeps serving the previous
index as explicitly **stale**, and tells the user to run `scubiee index . --force` (which is then
zero-downtime). The failure mode we explicitly prevent is the old BUG-1 "17308 chunks exceeding
10000 → publish nothing silently."

**"Lots more such scenarios"** → the matrix above (A–H), 50+ situations, each with a simulation and
a pass criterion.

---

## J. Status of each scenario (what's already verified vs TODO)

| Group | Verified this session | Needs a new probe |
|---|---|---|
| A (enroll) | A2 (init works) | A1, A3 (big-repo confirm gate), A4, A5 |
| B (warm) | B1 (Win 0/30, mac 0/120), B3 (concurrent-during-warm no crash) | B2, B4 (idle→requery), B5 (watchdog) |
| C (editing) | C1–C4, C7 (battery), C8 (UTF-8 fix) | C5 (rename), C6 (debounce burst) |
| D (git) | D6 (newcomer BUG-1) | **D1, D2, D3 (the big-pull trio — HIGH priority), D4, D5, D7** |
| E (reindex) | E1 (zero-downtime), E2 (handoff), E4 (sync-now clean) | E3 (interrupt), E5 (upgrade) |
| F (concurrency) | F2 (parallel+retry) | F1 (two IDEs), F3 (query during promote), F4 (multi-repo) |
| G (failure) | G9 (GB file), G10 (huge ignored dir) | **G6, G7, G11 (crash/corrupt recovery — HIGH priority), G8, G12** |
| H (scale) | H1 partial (soak) | H2, H3 (large-repo scale) |

**Pre-production priority order (highest risk, user-visible):**
1. **D2 / D3 — the big-pull trio** (the user's explicit example; the BUG-1 class lived here).
2. **G7 / G11 — crash/corrupt recovery** (does the engine heal, or crash-loop?).
3. **E3 — interrupted reindex** (torn generation safety).
4. **B4 — idle→requery** (does the demote/re-warm cycle serve correctly?).
5. **F3 — query during promote** (coherent-read-during-swap).
6. Remainder (C5/C6, F1/F4, H2/H3, A-group) as time allows.

---

## K. How we'll run this before production

1. Extend `prod_sim.py` (or add `scenario_sim.py`) with runners for the HIGH-priority TODO rows
   (D2/D3, G7/G11, E3, B4, F3), each asserting its pass criterion + the global invariants G1–G5.
2. Run on **both** Windows and macOS (the macOS agent re-runs via the committed harness).
3. Each scenario emits PASS/FAIL + the measured numbers into a JSON report.
4. A scenario is "production-signed-off" only when it passes on both platforms with the global
   invariants intact.
5. Record results in `docs/scubiee-scenario-test-results.md` (one section per scenario).
