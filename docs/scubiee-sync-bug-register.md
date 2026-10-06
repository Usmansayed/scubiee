# Scubiee sync — bug register (discovered during 0.3.142 production testing)

All found while testing live sync against the running engine on this repo. Each bug lists the
observed symptom, the concrete evidence, and the suspected code area. Deep traces + stage tests
follow in `docs/scubiee-sync-bug-traces.md` (one section per bug).

Context: a FRESH install syncs fast (new file searchable ~206 ms at session start). The bugs below
accumulate after sustained dirty/sync/delete churn with mixed path forms. Current build 0.3.142.

---

## BUG-1 — Freshness/merkle OVER-COUNTS changes → publish refused (HIGH) ✅ ROOT-CAUSED + FIXED
**Symptom:** after churn, newly added/modified files never become searchable (grep + dense both
null for 50–70 s) even though the engine reports healthy.
**Evidence:**
- `scubiee sync-now --confirm` → `"17308 chunks changed, exceeding the automatic limit of 10000;
  run scubiee index --force"` — but the repo only has ~9,414 indexed chunks. The change-set is
  ~1.8× the entire corpus, which is impossible for a one-file edit.
- `/v1/sync` returns `strategy=deferred debounce_ms=1000 refreshed=false`; generation does not
  advance for the dirty.

**CONFIRMED ROOT CAUSE (not path-dup — a key-space mismatch):**
`incremental.py` `incremental_sync()` `discover_newcomers` branch computed
`newcomers = sorted(collect_index_relpaths(root, ...) - set(old))`.
- `collect_index_relpaths()` (paths.py) returns `p.relative_to(root).as_posix()` →
  **forward-slash, original case** (e.g. `AGENTS.md`, `packages/pipeline/server.py`).
- `old = store.load_merkle()` → `load_snapshot` → `sanitize_file_hashes` → `canonical_relpath()`
  which on Windows does `os.path.normcase` → **backslash + lowercase**
  (e.g. `agents.md`, `packages\pipeline\server.py`).
The two key spaces barely intersect on Windows, so the raw set-difference flagged **~every
indexed file as a newcomer**, roughly doubling the chunk count and tripping the
`AUTO_FULL_INDEX_CHUNKS=10000` guard → `incremental_sync` refused to publish.

**Empirical proof** (`scripts/perf/probe_bug1_newcomers.py`, live on-disk merkle):
- indexed files = 1344 (posix/original-case), merkle keys = 1564 (canonical backslash/lowercase)
- newcomers under CURRENT subtraction = **1328** (all `file_exists=True` AND `canonical_in_merkle=True`)
- newcomers under FIXED subtraction = **0**
- raw key overlap = 16 (only already-lowercase top-level names like `agents.md`)

**Why hot editor-saves were NOT affected:** the hot lane calls
`incremental_sync(..., force_files=paths)`, and the `discover_newcomers` branch is guarded by
`if discover_newcomers and not force_files:`. Only the non-force path (`_sync_unlocked` →
`incremental_sync(self.repo)`, `sync-now`, poll-driven sync) hit the bug.

**FIX (applied):** compare on the canonical key so only genuinely new files survive —
```python
newcomers = sorted(
    p for p in collect_index_relpaths(root, fast=..., fast_roots=...)
    if canonical_relpath(p) not in old
)
```
Same canonicalization pattern already used in `_patch_file_merkle`.

**Fix verification** (`scripts/perf/probe_bug1_inline_sync.py`, isolated inline run on the exact
`discover_newcomers=True` path): `strategy='incremental'`, `refreshed=True`,
`chunks_upserted=4` (just the new temp file), **no oversize error** (was
`strategy='full'` + "exceeding the automatic limit"). Engine rebuilt/reinstalled 0.3.142; post-restart
`chunks=9408`, `index_usable=true`, grep serves real content.

**Suspected area (confirmed):** `pipeline/incremental.py` (`discover_newcomers` subtraction ~L835);
`pipeline/merkle.py` `canonical_relpath`; `pipeline/paths.py` `collect_index_relpaths`.

## BUG-2 — Oversize change-set REFUSED with weak self-heal / silent-stale (HIGH) ✅ PARTIALLY FIXED
**Symptom:** once a change-set exceeds the auto-index cap, the incremental sync is blocked and the
engine silently serves stale results while locate still reported ready.
**Evidence:** `sync-now` oversize error; new content never publishes until a manual `index --force`.

**CONFIRMED (two gaps, via `scripts/perf/probe_bug2_oversize_selfheal.py`):**
1. **Flag not raised on the interval path.** The hot and bulk sync paths set `self.needs_full = True`
   on `strategy='explicit_full_index_required'` (`sync_loop.py` ~L871/L997), but the plain interval
   path `_sync_unlocked` (~L1684) only stored `last_result` and did NOT set the flag. So an oversize
   refusal on the interval path lived only transiently in `last_sync.strategy`.
2. **`needs_full` not treated as stale by locate.** `derive_locate_state` only marked
   `{syncing, overlay_ready, catching_up}` as stale; a `needs_full` state fell through to
   `state='ready', stale=None, agent_ready='yes'` — so an agent calling locate got "ready" and
   silently queried an index missing the oversized change.

Probe output (before fix): `locate.state='ready' (stale=None)`, `agent_ready='yes'`,
`_sync_unlocked sets needs_full = False`.

**FIX (applied):**
- `sync_loop.py` `_sync_unlocked`: set `self.needs_full = True` + `payload["needs_full"]=True` on
  `explicit_full_index_required` (consistency with the other 4 call sites).
- `sync_status.py` `derive_locate_state`: add `needs_full` to the stale set → returns
  `state='ready', stale=True, should_use=True, reason='needs_full_stale_ok',
  repair=['scubiee index . --force']`, and `agent_ready='stale'`.
Probe output (after fix): `locate.state='ready' (stale=True)`, `agent_ready='stale'`,
`_sync_unlocked sets needs_full = True`. Existing `tests/test_sync_status_canaries.py` → 10 passed.

**STILL OPEN (by design, not auto-applied):** no *automatic* escalation to a full reindex on
`needs_full`. An auto full-reindex is expensive and could thrash, so the chosen behavior is to serve
the current index as explicitly stale + surface the one-shot repair command rather than silently
rebuild. Note: with BUG-1 fixed, this guard is no longer tripped by phantom newcomers; it now only
fires for genuinely huge changes (branch switch, bulk refactor).
**Area (confirmed):** `incremental.py` oversize branches (L879/L1008); `sync_loop._sync_unlocked`;
`sync_status.derive_sync_status` / `derive_locate_state`.

## BUG-3 — `graph_pending` accumulates GHOST entries that never self-clear (MEDIUM) ✅ FIXED
**Symptom:** `graph_pending` grew to 81 entries, 24 of which are files that no longer exist
(deleted temp files) plus duplicate rel/abs path pairs.
**Evidence:** `scubiee status` meta `graph_pending` list contained e.g.
`scripts/perf/_synctmp/auto_mod.py` (long deleted) and both `_check_rules.py` +
`c:/users/.../_check_rules.py`.

**CONFIRMED (3 independent defects, via `scripts/perf/probe_bug3_graph_pending_ghosts.py`):**
The per-branch prune at `incremental.py` ~L1092 only clears ghosts on the HEALTHY path
(graph.json present AND `patch_and_save_graph` did not raise):
- **A.** graph.json MISSING → full-rebuild branch (~L1069) never assigns `graph_pruned` →
  it stays `set()` → a ghost (not in `touch_set`, not in `graph_pruned`) survives in the
  persisted `left` list forever.
- **B.** `patch_and_save_graph` raises → control goes to `except`, the prune `else:` block is
  skipped → `meta["graph_pending"]` is never rewritten → ghosts persist.
- **C.** the hot-lane union (`{str(p) …} | touch_set`, ~L1042) keeps mixed path forms (absolute +
  relative, backslash + posix) as DISTINCT entries → duplicates accumulate.
The probe also shows the healthy branch DOES prune correctly, confirming the defect is the
conditional coverage, not the prune logic itself.

**FIX (applied):** an UNCONDITIONAL `graph_pending` hygiene pass at the end of the graph section
(`incremental.py` after ~L1104), running regardless of which graph branch executed: normalize every
entry to a posix repo-relative key, strip any absolute-root prefix, drop entries whose file no
longer exists (ghosts), and dedup. Verified by probe: worst-case list
`[real, ghost, abs(real), backslash(real)]` → `[real]` (ghost dropped, dups collapsed).
Regression-guarded by `tests/test_sync_corpus_alignment.py` + `tests/test_graph_catchup_async.py`
(23 passed) which assert exact `graph_pending` contents.

**Area (confirmed):** `incremental.py` graph section (`graph_pending` union ~L1042, per-branch prune
~L1092, new hygiene pass ~L1104).

## BUG-4 — `scubiee index --force` can leave the serving engine DOWN (MEDIUM)
**Symptom:** after a forced full reindex finished (meta rewritten, `graph_pending=0`,
chunks 9484→9414), the HTTP engine did not come back up on its own.
**Evidence:** two idle `pythonw` procs at ~0 CPU / 5 MB RSS, `engine status` → `running:false`,
`watchdog running:false`, `restart_count:47`. Required a manual `engine stop`/`engine start`.
**Suspected cause:** the index path stops the engine for the rebuild but the restart/handoff back
to a serving + warm engine isn't guaranteed (watchdog not re-arming after a `--force` index).
**Suspected area:** `__main__.cmd_index` (post-index restart), `engine_boot.py` / `daemon.py`
(spawn/ensure), `watchdog.py` (re-arm after index).

## BUG-5 (observation) — new content "not searchable after gen advances" ✅ EXPLAINED (two causes)
**Symptom:** post-`resume`, generation advanced yet the just-added file was not grep-visible.
**Resolution — it was TWO overlapping causes, now both fixed:**
1. **BUG-1** kept the new file's chunks out of the published set (oversize refusal). With BUG-1
   fixed, a live test showed the keeper DOES pick up a new file: `generation` advanced 1→5 and
   `chunks` rose 9415→9418 (the 3 new chunks), `dense_ready=true`.
2. **BUG-6** (below) then masked the win: `/v1/grep` with the default `**/*` glob exhausted its scan
   budget before reaching the new file, returning a false-empty `count=0`. With a scoped glob
   (`scripts/perf/**/*.py`) the token was found immediately (`count=1`). Fixing BUG-6 makes the
   default glob find it too.
**Verification:** `scripts/perf/probe_bug5_live_newfile.py` (gen advance + chunk growth) and the
BUG-6 live grep (`def canonical_relpath` → `packages/pipeline/merkle.py:95`).

## BUG-6 — `/v1/grep` default `**/*` returns FALSE-EMPTY on large repos (HIGH) ✅ FIXED
**Discovered while verifying BUG-5.** A pattern that demonstrably exists in `packages/` returned
`count=0, truncated=true` from `/v1/grep`, while a narrow glob found it instantly.
**CONFIRMED ROOT CAUSE (`pipeline/capability.py`):**
- `grep_scan` iterates `iter_glob_files(root, '**/*')` in `sorted()` (alphabetical) order and
  stops at a `max_lines=250000` line cap / 15 s deadline. On this repo there are **640,899**
  scannable lines and **404,160 of them sort before the first `packages/` file** — so the budget was
  always spent in early-alphabet trees and `packages/`, `scripts/`, `tests/` were NEVER reached.
- `grep_scan` did `raw = path.read_bytes()` (whole file) BEFORE the `len(raw) > 2MB` guard, so it
  slurped multi-GB binaries (`laya_bench/laya_code.onnx` 1.6 GB, a 520 MB `.gguf`, large `.dll`/
  `.zip`) into memory just to reject them — burning the deadline.
- `iter_glob_files` called `is_junk_rel(rel)` WITHOUT `root`, so user `.scubieeignore` rules were not
  applied to the grep walk (builtins only).
**FIX (applied):**
1. Stat file size and sniff the first 8 KB for NUL BEFORE reading the body (skip oversize/binaries
   cheaply, never slurp a GB file).
2. Order the walked set source-roots-first (`INDEX_WRITE_HINT_ROOTS`: packages/ src/ scripts/ tests/
   …) so real code is always scanned within budget; deterministic tie-break on path.
3. Honor `.scubieeignore` in `iter_glob_files` by loading rules once and calling
   `should_index_rel(root, rel, rules=…)` so grep's walked set matches what gets indexed.
**Verification:** `grep_scan('def canonical_relpath','**/*')` now returns `packages/pipeline/merkle.py:95`
(was 0); live `/v1/grep` returns the same. `tests/test_grep_glob_scope.py` (8) +
`tests/test_capability_promotion.py` (13) pass.
**STILL OPEN (perf, not correctness):** a full `**/*` Python scan is ~15 s on this repo (no `rg` on
the engine PATH). Correctness is fixed (source hits returned first); speed is a follow-up — install/
bundle ripgrep for the engine, or raise the line cap now that ordering guarantees code-first.
**Area:** `pipeline/capability.py` (`grep_scan` read guard, `iter_glob_files` ordering + ignore).

---

### Severity order + status
1. BUG-1 (over-count → refuse) — root of the "sync doesn't reflect" failure. ✅ FIXED
2. BUG-2 (weak self-heal / silent-stale) — turned BUG-1 into a stuck, healthy-looking state.
   ✅ PARTIALLY FIXED (flag + stale surfaced; auto-reindex intentionally not added).
3. BUG-6 (grep false-empty on large repos) — masked BUG-5; independent HIGH-impact grep bug.
   ✅ FIXED (correctness; perf follow-up open).
4. BUG-3 (ghost graph_pending) — drift contributor + standalone leak. ✅ FIXED.
5. BUG-4 (index --force leaves engine down) — independent robustness gap. ⚠️ ROOT-CAUSED
   (watchdog demand-gate + crash-loop pause; recommend `cmd_index` ensure-engine handoff).
6. BUG-5 — resolved by BUG-1 (publish) + BUG-6 (grep). ✅ EXPLAINED.

### Files changed
- `packages/pipeline/incremental.py` — BUG-1 (canonical newcomer diff) + BUG-3 (graph_pending hygiene).
- `packages/pipeline/sync_loop.py` — BUG-2 (`_sync_unlocked` sets `needs_full`).
- `packages/pipeline/sync_status.py` — BUG-2 (`needs_full` → stale locate contract).
- `packages/pipeline/capability.py` — BUG-6 (grep read guard + source-first order + ignore).
Probes: `scripts/perf/probe_bug1_newcomers.py`, `probe_bug1_inline_sync.py`,
`probe_bug2_oversize_selfheal.py`, `probe_bug3_graph_pending_ghosts.py`, `probe_bug5_live_newfile.py`.

---

## Hardening pass (research-driven, after the five bugs above)

Guided by how mature tools solve these problem classes (ripgrep, LSP incremental indexers,
Elasticsearch/Redis blue-green promote, systemd supervision). Each item is implemented + verified.

### H1 — Prefer bundled ripgrep for grep (fixes BUG-6 perf + correctness)
`capability.py` `_resolve_ripgrep()` now locates rg via: `SCUBIEE_RG_PATH`/`CTX_RG_PATH` env →
`shutil.which("rg")` → editor-bundled `@vscode/ripgrep` (Kiro/VS Code/Cursor ship it; it is on disk
but not on PATH). Cached. `_grep_via_rg` dropped `--hidden` (it made rg descend the 435k-file
`.ab_workspaces` tree and time out), added `--max-filesize 2M`, builtin-dir excludes
(`_rg_exclude_dirs()` from `BUILTIN_IGNORE_DIRS`), `--ignore-file .scubieeignore`, and only passes a
non-trivial glob as an include. Result: `backend=rg`, `def canonical_relpath` →
`packages/pipeline/merkle.py:95`, 0 `.ab_workspaces` leaks, ~195 ms warm (was ~21 s Python). No new
dependency — reuses rg already on the machine.

### H2 — Loud grep: never report false-empty (fixes the "confident wrong answer" class)
`grep_scan`/`_grep_via_rg` return a `complete` bool. An rg timeout returns `complete=False,
incomplete_reason=timeout` (no silent fall-through to the slower Python scan). The Python path
distinguishes a budget-exhausted scan (`deadline`/`max_lines` → `complete=False,
incomplete_reason=scan_budget`) from merely hitting the hit-cap (`complete=True` — more matches
exist, but the scan looked everywhere). `ce_service.grep` wraps an incomplete result with
`incomplete=True` + a note: *count is a lower bound, NOT proof of absence — narrow with a `glob`*.
The HTTP `/v1/grep` returns this verbatim, so an agent can no longer read `count=0` as "not found."

### H3 — Regression lock for BUG-1 (`tests/test_newcomer_canonical_keys.py`, 5 tests)
Asserts `canonical_relpath` is idempotent and folds slash/case; that already-indexed files are not
re-flagged as newcomers; that a genuinely new file still is; documents the raw `set - set` as the
regression; and a STATIC guard asserts `incremental_sync`'s source still canonicalizes
(`canonical_relpath(p) not in old`) and contains no raw `- set(old)`.

### H4 — `index --force` engine handoff (fixes BUG-4's "engine left DOWN")
`__main__.cmd_index` now, after a successful `index_repo`, calls
`ensure_daemon(root, spawn_owner="direct", wait_s=90)` and (if an engine was already serving)
`EngineClient().publish(root)` to reload the rebuilt generation. Non-fatal: a handoff hiccup can't
fail the index. `spawn_owner="direct"` makes the CLI start/heal the engine itself instead of relying
on the demand-gated / crash-loop-paused watchdog. **Live-verified**: `scubiee index --force` with the
engine serving → the engine came back UP (`chunks=8392, warm, index_usable, watchdog running`),
where it previously stayed DOWN until a manual restart.

**Follow-up (designed, not yet implemented — `docs/scubiee-blue-green-index-design.md`):** B2
stage-then-atomic-promote of the text artifacts and B3 FAISS collection swap, which also close the
*during-rebuild* down window (the engine still goes down mid-`index --force`; H4 only guarantees it
comes back). Deferred as a focused, separately-reviewed change (engine-lifecycle blast radius).

### Verified green
`tests/test_grep_glob_scope.py`, `test_capability_promotion.py`, `test_newcomer_canonical_keys.py`,
`test_sync_status_canaries.py`, `test_sync_corpus_alignment.py`, `test_graph_catchup_async.py`,
`test_incremental_confirm.py` → **53 passed**. Engine rebuilt/reinstalled 0.3.142; live grep
`backend=rg complete=True`.
