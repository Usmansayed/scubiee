# Scubiee sync — bug traces (stage-by-stage)

Companion to `docs/scubiee-sync-bug-register.md`. One section per bug: the full path a change
travels, where it fails, the probe that localizes it, and the fix.

---

## BUG-1 — newcomer over-count → publish refused  ✅ FIXED

### The full path a change travels (dirty → searchable)

```
 editor save / file change
        │
        ▼
 (A) RuntimeManager.mark_dirty           ce_service.py:525   posix-normalizes the rel path
        │                                                    (hot lane uses force_files=…)
        ▼
 (B) /v1/dirty handler                   server.py:~470      filter_dirty_paths (ignore.py:367)
        │                                                    drops ignored/junk, keeps rel keys
        ▼
 (C) BackgroundSyncLoop                   sync_loop.py        1000ms debounce; hot lane vs
        │   ├─ hot save  → incremental_sync(force_files=…)   (SKIPS discover_newcomers)
        │   └─ poll/sync → _sync_unlocked → incremental_sync(self.repo)   ◄── BUG LIVES HERE
        ▼
 (D) incremental_sync                      incremental.py:711
        │   ├─ check_freshness(root, old, …)      freshness.py   → diff.added/modified/removed
        │   │
        │   └─ discover_newcomers branch           incremental.py:~835
        │        newcomers = collect_index_relpaths(root)  -  set(old)
        │                     └ posix / ORIGINAL case          └ canonical: backslash + LOWERCASE
        │        ⇒ on Windows the two key spaces don't intersect
        │        ⇒ ~ALL 1344 indexed files injected as "newcomers"
        ▼
 (E) oversize guard                        incremental.py:~300 / ~1095
        │   changed_count ≈ 2× corpus  >  AUTO_FULL_INDEX_CHUNKS (10000)
        │   ⇒ return strategy="full"/"explicit_full_index_required", error=_confirm_hint(...)
        ▼
 (F) publish                               (NEVER REACHED)   nothing upserted, generation frozen
        │
        ▼
 (G) /v1/search · /v1/grep                 serves STALE index → new file not found
```

### Where it fails
Stage **(D) → (E)**. The `discover_newcomers` set-difference compares non-canonical keys
(`collect_index_relpaths` → posix, original case) against canonical keys
(`load_merkle` → `canonical_relpath` → `os.path.normcase` → backslash + lowercase on Windows).
Nearly every already-indexed file is mis-classified as new, doubling the change-set and tripping
the oversize guard at (E), so (F) publish never runs.

### Localizing probe
`scripts/perf/probe_bug1_newcomers.py` — loads the live on-disk merkle and computes the newcomer
set both ways (current vs canonicalized):

| metric | value |
|---|---|
| indexed files (`collect_index_relpaths`, posix/orig-case) | 1344 |
| merkle keys (`load_merkle`, canonical backslash/lowercase) | 1564 |
| newcomers under CURRENT subtraction | **1328** |
| newcomers under FIXED subtraction | **0** |
| raw key overlap (index ∩ merkle) | 16 |

Every one of the 1328 "newcomers" has `file_exists=True` and `canonical_in_merkle=True` — i.e. it
is already indexed and only *looks* new because of the slash/case key mismatch.

### Root cause (code)
- `packages/pipeline/paths.py` `collect_index_relpaths` → `p.relative_to(root).as_posix()`
- `packages/pipeline/merkle.py` `canonical_relpath` → `os.path.normcase(norm)` (Windows: backslash + lower)
- `packages/pipeline/incremental.py` `incremental_sync` discover_newcomers: raw `set - set`

### Fix
```python
# packages/pipeline/incremental.py  (discover_newcomers branch)
from pipeline.merkle import SyncDiff, canonical_relpath, root_hash as _rh
newcomers = sorted(
    p for p in collect_index_relpaths(root, fast=..., fast_roots=...)
    if canonical_relpath(p) not in old
)
```
Only genuinely new files survive. Downstream `touch_set = {f.replace("\\","/") …}` already
posix-normalizes, so the newcomer keys embed correctly when a file really is new.

### Fix verification
`scripts/perf/probe_bug1_inline_sync.py` runs the exact `discover_newcomers=True, inline=True` path
in isolation (engine stopped to avoid store-lock contention):

```
incremental_sync: refreshed=True  strategy='incremental'
                  chunks_upserted=4  error=None
VERDICT: oversize refusal : False → PASS
```
Before the fix this path returned `strategy='full'` + `"exceeding the automatic limit of 10000"`.
After rebuild/reinstall of 0.3.142 the live engine is `index_usable=true`, chunks ≈ 9408, and grep
serves real content.

---

## BUG-2 — oversize refusal: weak self-heal + silent-stale  ✅ PARTIALLY FIXED

### The full path

```
 incremental_sync returns oversize refusal
   (strategy='explicit_full_index_required', refreshed=False)
        │
        ├─ hot lane  (sync_loop ~L997)  → self.needs_full = True   ✓
        ├─ bulk path (sync_loop ~L871)  → self.needs_full = True   ✓
        └─ interval  (sync_loop _sync_unlocked ~L1684)
                 last_result = payload                              ✗ needs_full NOT set
                 if result.refreshed: publish                      (skipped — refreshed False)
        │
        ▼
 status derivation
        │  derive_sync_status(last_sync.strategy='explicit_full_index_required') → 'needs_full'  ✓
        │  derive_locate_state(sync_state='needs_full')
        │      stale set = {syncing, overlay_ready, catching_up}   ✗ needs_full missing
        │      ⇒ state='ready', stale=None, agent_ready='yes'      ← SILENT STALE
        ▼
 agent calls locate → "ready" → queries index missing the oversized change
```

### Where it fails
Two spots: (1) the interval path never raised `needs_full`, so only the hot/bulk paths flipped it;
(2) `derive_locate_state` didn't count `needs_full` as stale, so locate reported fully-ready while
the index silently lagged.

### Localizing probe
`scripts/perf/probe_bug2_oversize_selfheal.py` feeds an oversize `last_result` through
`derive_sync_status` / `build_sync_contract` and statically inspects `_sync_unlocked`:

| check | before fix | after fix |
|---|---|---|
| `derive_sync_status(oversize)` | `needs_full` | `needs_full` |
| `contract.locate.state` | `ready` (stale=None) | `ready` (stale=True) |
| `contract.agent_ready` | `yes` | `stale` |
| `_sync_unlocked` sets `needs_full` | False | True |

### Fix
- `sync_loop.py` `_sync_unlocked`: on `strategy=='explicit_full_index_required'` set
  `self.needs_full = True` and `payload["needs_full"]=True`.
- `sync_status.py` `derive_locate_state`: add `needs_full` to the stale branch →
  `state='ready', stale=True, should_use=True, reason='needs_full_stale_ok',
  repair=['scubiee index . --force']`.

### Verification
`tests/test_sync_status_canaries.py` → 10 passed. Probe shows the stale flag + `agent_ready='stale'`.

### Deliberately NOT changed
No automatic full-reindex on `needs_full` — too expensive / thrash-prone to trigger silently. The
engine now serves the current index as explicitly **stale** with the one-shot repair hint instead.

---

## BUG-3 — graph_pending ghost entries never self-clear  ✅ FIXED

### The full path (hot save defers graph → catch-up pays debt)

```
 hot save of file X
        │
        ▼
 incremental_sync(force_files=[X], hot_lane=True)   incremental.py
        │  graph is expensive on the hot path → DEFER it:
        │  meta["graph_pending"] = sorted({existing…} | touch_set)   ~L1042
        │                                   └ union keeps mixed path forms (defect C)
        ▼
 keeper non-hot catch-up tick            sync_loop.py ~L1038 owed=payload.graph_pending
        │
        ▼
 incremental_sync(self.repo)  (non-hot)            incremental.py
        │  owed = [p for p in meta.graph_pending if (root/p).is_file()]   ~L898
        │         └ ghost (deleted) excluded from `changed`/touch_set
        │
        ├─ graph.json present, patch ok ──► gone_owed computed, graph_pruned=gone_owed,
        │                                   left = pending − touch_set − graph_pruned  ✓ ghost pruned
        │
        ├─ graph.json MISSING (full rebuild) ─► graph_pruned stays set()  (defect A)
        │                                        left keeps ghost  ✗
        │
        └─ patch_and_save_graph RAISES ──────► except; prune else-block skipped (defect B)
                                                meta.graph_pending unchanged  ✗
```

### Where it fails
The ghost-prune is only wired into the single healthy branch. Two alternate branches (missing
graph.json → full rebuild; or a raising patch) bypass it, so a deleted file lingers in
`graph_pending` forever. Independently, the hot union keeps absolute/relative/backslash variants of
the same path as separate entries.

### Localizing probe
`scripts/perf/probe_bug3_graph_pending_ghosts.py` replicates the exact set expressions:

| scenario | ghost in persisted pending? |
|---|---|
| A. graph.json missing (graph_pruned empty) | **survives** |
| B. patch raises (prune else skipped) | **survives** |
| C. hot union abs+rel | duplicate entries |
| healthy branch (graph.json present) | correctly cleared |

### Fix
Unconditional hygiene pass appended after the graph section (runs on every branch, before persist):
```python
if meta.get("graph_pending"):
    seen, kept = set(), []
    root_posix = root.as_posix().rstrip("/") + "/"
    for p in meta["graph_pending"]:
        rel = str(p).replace("\\", "/")
        if rel.lower().startswith(root_posix.lower()):
            rel = rel[len(root_posix):]
        rel = rel.strip("/")
        if not rel or rel in seen or not (root / rel).is_file():
            continue          # dedup + drop ghosts
        seen.add(rel); kept.append(rel)
    meta["graph_pending"] = sorted(kept) if kept else meta.pop("graph_pending", None)
```
Normalizes to posix repo-relative keys, drops non-existent files, dedups mixed forms.

### Verification
Probe: `[real, ghost, abs(real), backslash(real)]` → `[real]`.
`tests/test_sync_corpus_alignment.py` + `tests/test_graph_catchup_async.py` → 23 passed (they
assert exact `graph_pending` contents, so the hygiene pass preserves the healthy contract).

### Side note — regression caught during this fix
Applying BUG-1 originally added a redundant `from pipeline.merkle import … canonical_relpath …`
inside the `discover_newcomers` branch. Because `canonical_relpath` is already a module-level import
(incremental.py L27) and is used earlier in the `force_files` branch (L801), the in-branch import
turned it into a function-local name and raised `UnboundLocalError` on the force_files path. Caught
by the test suite; fixed by dropping the redundant import. Lesson: don't shadow a module-level name
with a conditional in-function import.

---

## BUG-6 — /v1/grep default `**/*` returns false-empty on large repos  ✅ FIXED

### The full path

```
 /v1/grep {pattern, glob='**/*'}        server.py ~L596
        │
        ▼
 ce.grep → grep_scan(root, pattern, glob)   capability.py
        │  rg path: shutil.which('rg') → None on engine PATH → fall through
        │
        ▼
 Python scan over iter_glob_files(root, '**/*')   sorted() alphabetical
        │  for rel in files:
        │     raw = path.read_bytes()     ← reads WHOLE file first (defect 2)
        │     if len(raw) > 2MB: continue  ← too late; 1.6GB onnx already slurped
        │     lines_scanned += …           ← max_lines=250000 cap / 15s deadline
        │
        ▼
 budget exhausted at ~404,160 lines (all before first packages/ file)
        │  → truncated=True, count=0   ← FALSE EMPTY for anything in packages/scripts/tests
```

### Where it fails
Three compounding defects in `capability.py`:
1. `grep_scan` reads entire files before the 2 MB guard → multi-GB binaries slurped, deadline burned.
2. `iter_glob_files` yields `sorted()` (alphabetical); 404,160 of 640,899 scannable lines sort
   before `packages/`, so the 250k line cap fires before code is ever reached.
3. `iter_glob_files` ignored user `.scubieeignore` (called `is_junk_rel(rel)` without `root`).

### Localizing evidence
- Narrow glob `scripts/perf/**/*.py` → found token instantly; default `**/*` → `count=0, truncated`.
- Repo scan budget audit: total scannable lines 640,899; lines before first `packages/` = 404,160
  (> 250k cap). Largest walked files: `laya_bench/laya_code.onnx` 1.6 GB, `.gguf` 520 MB, `.dll`/`.zip`.

### Fix (capability.py)
1. Stat size + sniff first 8 KB for NUL BEFORE reading the body:
   ```python
   if path.stat().st_size > 2_000_000: continue
   with path.open("rb") as fh:
       head = fh.read(8192)
       if b"\0" in head: continue
       raw = head + fh.read()
   ```
2. Source-roots-first ordering in `iter_glob_files`:
   `sorted(out, key=lambda rel: (0 if rel.startswith(INDEX_WRITE_HINT_ROOTS) else 1, rel))`.
3. Honor `.scubieeignore`: load rules once, `should_index_rel(root, rel, rules=rules)`.

### Verification
`grep_scan('def canonical_relpath','**/*')` → `packages/pipeline/merkle.py:95` (was 0 hits).
Live `/v1/grep` returns the same. `tests/test_grep_glob_scope.py` (8) +
`tests/test_capability_promotion.py` (13) pass.

### Open (perf, not correctness)
Full `**/*` Python scan ≈ 15 s (no `rg` on engine PATH). Correct hits are returned (source-first);
speed follow-up: bundle ripgrep for the engine or raise the line cap now that order guarantees code-first.

---

## BUG-4 — `scubiee index --force` can leave the serving engine DOWN  ⚠️ ROOT-CAUSED (fix recommended)

### The full path

```
 scubiee index . --force     __main__.cmd_index
        │  register_project(index=False) → index_repo(force=True)   indexer.py
        │     rewrites store (merkle/chunks/meta) under the running engine
        │  bar.finish("Ready"); return 0        ← NEVER ensures/restarts a serving engine
        ▼
 running engine's store changes underneath it → it exits / is cycled
        ▼
 watchdog decides whether to restart        watchdog.py
        ├─ demand gate (~L726): if no MCP client AND no start_request → set STANDBY, DO NOT restart
        └─ crash-loop cap (~L738): ≥20 restarts/hour → sleep 600s (pause)
        ▼
 engine stays DOWN until a client demands it (or the 10-min pause ends)
 observed: engine status running=false, watchdog running=false, restart_count=47
```

### Where it fails
`cmd_index` has no post-index engine handoff. `index_repo` (`indexer.py`) never touches the engine/
daemon/watchdog — it only writes the store. Recovery is left entirely to the watchdog, which is
(a) demand-gated (won't restart a ghost engine when no client is attached) and (b) crash-loop-capped
(10-minute pause after 20 restarts/hour — consistent with the observed `restart_count:47`).

### Root cause
A CLI `index --force` rewrites the store out from under the serving engine but delegates recovery to
a watchdog that is intentionally demand-gated, so a bare-CLI reindex with no attached client leaves
no serving engine.

### Recommended fix (not applied — engine-lifecycle change, wants its own review)
After a successful `index_repo`, have `cmd_index` call `ensure_daemon(root)` (the canonical bring-up
helper) to explicitly restore a serving + warm engine, instead of relying on the demand-gated
watchdog. Lower-risk alternative: print an explicit "engine not auto-restarted; run `scubiee engine
start`" hint on completion so the down state is never silent.

### Why not auto-applied here
Touches the engine spawn/lifecycle path (supervisor/watchdog interplay) which is higher-risk than the
in-pipeline fixes above and deserves a focused change + its own test. Documented for follow-up.

---
