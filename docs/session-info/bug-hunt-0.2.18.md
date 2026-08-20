# Bug Hunt Report — scubiee 0.2.18

**Date:** 2026-08-20  
**Method:** Adversarial testing (corrupted state, path edge cases, env manipulation, safety probes)  
**Environment:** macOS Apple Silicon, Python 3.12, MLX FP16, installed from PyPI

---

## Summary

| Severity | Count |
|----------|-------|
| HIGH     | 1     |
| MEDIUM   | 3     |
| LOW      | 1     |
| **Total**| **5** |

---

## Bug 1 — HIGH: `ctx wipe` would delete system directories

**Scenario:** User sets `CTX_HOME=/tmp` (or any system path) and runs `ctx wipe --confirm`.

**Behavior:** Wipe proceeds to `shutil.rmtree(ce_home)` with no safety check on whether `ce_home` is a dangerous path like `/tmp`, `/`, `/home`, etc.

**Impact:** Data loss. Could wipe system temp files, or worse if `CTX_HOME=/` by mistake.

**Expected:** Wipe should refuse paths that:
- Are system directories (`/tmp`, `/var`, `/home`, `/usr`, etc.)
- Are fewer than 2 path components deep from root
- Don't contain a `registry.json` (i.e., aren't actually a CE home)

**File:** `packages/pipeline/wipe.py`

**Fix:** Add a safety check before `shutil.rmtree`:
```python
_DANGEROUS_PATHS = {"/", "/tmp", "/var", "/home", "/usr", "/etc", "/opt"}

def _is_safe_to_wipe(path: Path) -> bool:
    resolved = str(path.resolve())
    if resolved in _DANGEROUS_PATHS:
        return False
    if len(path.resolve().parts) <= 2:
        return False
    if not (path / "registry.json").exists() and not (path / "accel.json").exists():
        return False
    return True
```

---

## Bug 2 — MEDIUM: Empty `CTX_REPO` makes `_is_repo_managed()` return True

**Scenario:** `CTX_REPO=""` (empty string) in the environment.

**Behavior:** `_is_repo_managed()` returns `True` because `_default_repo()` falls through to `Path.cwd()`, which happens to be the workspace (a managed folder). The agent then gets full forced instructions even though no repo was explicitly configured.

**Impact:** Token waste. If an IDE launches the MCP without setting `CTX_REPO`, the agent gets forced CE instructions and may waste calls on a folder that isn't the user's intent.

**Expected:** When `CTX_REPO` is explicitly empty, `_is_repo_managed()` should return `False` — treat it as "no repo configured."

**File:** `packages/pipeline/mcp_locate.py`, function `_is_repo_managed()`

**Fix:**
```python
def _is_repo_managed() -> bool:
    try:
        # If CTX_REPO is explicitly empty, treat as unmanaged
        explicit = os.environ.get("CTX_REPO", "").strip()
        if explicit == "":
            return False
        repo = _default_repo()
        ...
```

---

## Bug 3 — MEDIUM: `ctx migrate` crashes on corrupted meta.json

**Scenario:** The `meta.json` file in a project store is corrupted (invalid JSON).

**Behavior:** `detect_migration_needed()` raises an unhandled `json.JSONDecodeError` that bubbles up to the CLI and crashes the command.

**Impact:** User can't run `ctx migrate --check-all` if any project has a corrupted meta file. The whole command fails instead of reporting the bad project and continuing.

**Expected:** Catch `JSONDecodeError` and return `{"ok": False, "error": "corrupt_metadata", "project_id": ...}`.

**File:** `packages/pipeline/migrate.py`, function `detect_migration_needed()`

**Fix:** Wrap the `json.loads(meta_path.read_text())` in a try/except:
```python
try:
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
except (json.JSONDecodeError, UnicodeDecodeError) as exc:
    return {
        "ok": False,
        "project_id": project_id,
        "error": "corrupt_metadata",
        "detail": str(exc),
    }
```

---

## Bug 4 — MEDIUM: Full CE instructions emitted for empty CTX_REPO

**Scenario:** Same root cause as Bug 2, but from the perspective of `_server_instructions()`.

**Behavior:** When `CTX_REPO=""`, the instruction gating check (`_is_repo_managed()`) falls through to cwd-based detection, and if cwd is managed, the full 1138-char instructions are emitted. This forces the agent to use CE tools even though no explicit repo was configured.

**Impact:** Token waste per turn on sessions where the MCP was started without a project context.

**Expected:** Same fix as Bug 2 — treat empty `CTX_REPO` as unmanaged.

**File:** `packages/pipeline/mcp_locate.py`

---

## Bug 5 — LOW: Corrupted registry.json silently returns empty list

**Scenario:** `~/.context-engine/registry.json` contains invalid JSON.

**Behavior:** `list_managed_repos()` returns an empty list `[]` with no error indication. The user sees "no managed repos" and doesn't know their registry is corrupt.

**Impact:** Confusing UX. All repos appear unmanaged. User might re-init everything unnecessarily.

**Expected:** Either:
- Raise/return an error indicating corrupt registry
- Or auto-repair: rename the corrupt file to `.bak` and start fresh, printing a warning

**File:** `packages/pipeline/project_id.py` (wherever `load_registry()` catches parse errors)

---

## What Passed (no bugs found)

| Test | Result |
|------|--------|
| Folder move + `locate_repo` reattach | OK |
| Unicode/emoji/spaces/parentheses in paths | OK |
| `CTX_HOME` override to non-existent dir | OK (empty registry) |
| Double-init same folder (idempotent) | OK |
| Double-remove already-removed repo | OK (returns error) |
| Migrate on unindexed folder | OK (returns not_indexed) |
| Empty folder (no .py files) registration | OK |
| Wipe --include-mcp with missing configs | OK |
| Migrate --force re-stamps metadata | OK |
| Symlink as repo path (resolves correctly) | OK |

---

## Recommendations

1. **Fix Bug 1 immediately** — it's a data-loss risk via user env misconfiguration.
2. **Fix Bugs 2+4 together** — one-line check at the top of `_is_repo_managed()`.
3. **Fix Bug 3** — simple try/except wrap in `migrate.py`.
4. **Bug 5** can wait — it's an unusual scenario and the impact is confusion, not data loss.

---

## Round 2 Findings (2026-08-20, same session)

Second round of adversarial tests: concurrency, path edge cases, self-referential indexing, malicious inputs.

### Bug 6 — MEDIUM: Concurrent init on same folder causes race failures

**Scenario:** 5 threads call `initialize_repo()` simultaneously on the same folder.

**Behavior:** 4/5 threads fail with `project_id_mismatch`. The registry lock prevents corruption, but the contention path returns an error instead of being idempotent.

**Impact:** In theory, if an MCP process and CLI both try to register the same repo simultaneously, one will fail. In practice this is rare (single-user product).

**Status:** FIXED — `initialize_repo` now wraps the registration section in `registry_lock()`. Concurrent calls wait; the first wins, subsequent ones detect "already managed" and return immediately. 5/5 threads succeed with the same project_id.

---

### Bug 7 — LOW: Migrate on non-existent path returns confusing "already_current"

**Scenario:** `ctx migrate /tmp/does_not_exist`

**Behavior (before fix):** Returns `{"ok": true, "reason": "already_current", "project_id": null}`. Confusing — it's not "current," it doesn't exist.

**Fix:** Now propagates the actual reason from detection (`"not_indexed"` or `"no_index_data"`).

**Status:** FIXED.

---

### Bug 8 — MEDIUM: Can init a folder inside ~/.context-engine

**Scenario:** `ctx init ~/.context-engine/some_folder`

**Behavior (before fix):** Succeeds. Indexing CE's own storage could cause infinite loops or corrupt index data.

**Fix:** Added guard in `initialize_repo()` — refuses any path that `is_relative_to(context_engine_home())`.

**Status:** FIXED.

---

### Bug 9 — LOW: migrate_all silently skips corrupt projects

**Scenario:** One project has a corrupted `meta.json`. `ctx migrate --apply-all` runs.

**Behavior (before fix):** Corrupt project counted as "skipped" with no error indication in results.

**Fix:** Corrupt projects now appear in the `results` array with `ok=False` and are counted separately in `"errors"` field.

**Status:** FIXED.

---

## Round 2 — What Passed (no bugs)

| Test | Result |
|------|--------|
| Very long path (269 chars) | OK |
| Registry stress (100+ projects, 0.12s) | OK |
| Wipe dry-run while daemon running | OK |
| Delete id.json → reports unmanaged, re-init assigns new ID | OK |
| Double-pause (idempotent) | OK |
| forget_repo with wrong confirmation → rejected | OK |
| SQL injection / path traversal / null bytes / 10KB query | OK (all survive) |
| Invalid MCP surface name → falls back to default | OK |

---

## Fix Summary

| Bug | Severity | Status | File |
|-----|----------|--------|------|
| 1. Wipe deletes system dirs | HIGH | **FIXED** | `wipe.py` |
| 2+4. Empty CTX_REPO → managed=True | MEDIUM | **FIXED** | `mcp_locate.py` |
| 3. Migrate crashes on corrupt meta | MEDIUM | **FIXED** | `migrate.py` |
| 5. Corrupt registry silent empty | LOW | **FIXED** (warning) | `project_id.py` |
| 6. Concurrent init race | MEDIUM | **FIXED** | `repo_lifecycle.py` |
| 7. Migrate non-existent confusing msg | LOW | **FIXED** | `migrate.py` |
| 8. Init inside ce_home allowed | MEDIUM | **FIXED** | `repo_lifecycle.py` |
| 9. migrate_all skips corrupt silently | LOW | **FIXED** | `migrate.py` |

---

## Round 3 Findings — Chaos Testing (2026-08-20)

Method: Stop/start daemon mid-operation, bulk file changes, corrupt state during warm engine, rapid cycling, giant files, folder rename, file-as-CTX_REPO.

### Bug 10 — HIGH: Daemon stop race — watchdog revives daemon before client detects death

**Scenario:** Stop the daemon, immediately try to use search.

**Behavior:** `engine stop` sends the stop signal, but by the time a client checks `is_running()` ~1s later, the watchdog (15s poll interval) or a stale TCP connection means the daemon appears alive or has already been revived. Search calls can succeed against a daemon that was "stopped."

**Root cause:** The chaos test used `subprocess.run(["ctx", "engine", "stop"])` — the CLI's `cmd_engine("stop")` does call `stop_watchdog()` first, but there's a race window:
1. Watchdog stop signal sent
2. Daemon stop signal sent  
3. Between steps 1-2, the watchdog's last health poll may trigger a restart

Also: `is_running()` checks `/health` which can return 200 from a daemon that is shutting down but hasn't closed its socket yet.

**Impact:** Users who `ctx engine stop` and immediately start another process on the same port may hit "address already in use." MCP processes may briefly succeed against a dying daemon, then fail unpredictably.

**Recommended fix:** `stop_daemon()` should wait until the port is actually free (poll `/health` until connection refused, with a 5s timeout).

**Status:** FIXED — `stop_daemon()` now polls `is_running()` for up to 5s after kill, confirming the port is free before returning.

---

### Bug 11 — MEDIUM: `ctx sync` crashes when meta.json is corrupt on disk

**Scenario:** Daemon is warm (engine loaded in memory). Someone or something corrupts `meta.json` on disk. Then `ctx sync` is called.

**Behavior:** `ctx sync` reads meta.json to determine sync strategy, hits invalid JSON, and the error propagates. The sync fails even though the in-memory engine is perfectly healthy.

**Impact:** If any process (crash, disk issue, race) corrupts meta.json while the daemon is running, all syncs fail until the file is repaired. The daemon remains warm and searchable, but freshness updates stop.

**Recommended fix:** `cmd_sync` / `incremental_sync` should catch `JSONDecodeError` on meta load and either:
- Fall back to a full sync (re-create meta from the in-memory state)
- Or return a clear error: `"meta_corrupt"` with a hint to `ctx rebuild`

**Status:** FIXED — `PipelineStore.load_meta()` now catches JSONDecodeError, prints a WARNING, and returns `{}`. Sync treats it as "no prior state" and proceeds without crashing.

---

### Not-a-bug: Grep "misses" bulk-added files

The chaos test added 20 files and grep returned 10. This is **correct behavior** — `max_hits=10` was set, and grep returned `truncated=True, has_more=True`. The grep honesty contract (0.2.18 feature) correctly signals that more results exist. No bug.

---

### Round 3 — What Passed (no bugs)

| Test | Result |
|------|--------|
| Grep works after daemon kill (live disk, no daemon needed) | OK |
| Daemon restart after kill | OK |
| Grep finds 0 after bulk delete | OK |
| File replacement: grep finds new content, not old | OK |
| Renamed repo path: correctly not managed | OK |
| Corrupt engine.lock: `is_running()` handles gracefully | OK |
| `engine ensure` recovers from corrupt lock | OK |
| Daemon stays warm with corrupt on-disk meta (in-memory) | OK |
| 5x rapid start/stop cycle: all recoveries succeed | OK |
| 5MB Python file: grep handles (capped at max_hits) | OK |
| CTX_REPO pointing to a file: correctly not managed | OK |
| Re-init already-indexed repo: reconciles successfully | OK |

---

## Updated Fix Summary (all rounds)

| Bug | Severity | Status | File |
|-----|----------|--------|------|
| 1. Wipe deletes system dirs | HIGH | **FIXED** | `wipe.py` |
| 2+4. Empty CTX_REPO → managed=True | MEDIUM | **FIXED** | `mcp_locate.py` |
| 3. Migrate crashes on corrupt meta | MEDIUM | **FIXED** | `migrate.py` |
| 5. Corrupt registry silent empty | LOW | **FIXED** (warning) | `project_id.py` |
| 6. Concurrent init race | MEDIUM | **FIXED** | `repo_lifecycle.py` |
| 7. Migrate non-existent confusing msg | LOW | **FIXED** | `migrate.py` |
| 8. Init inside ce_home allowed | MEDIUM | **FIXED** | `repo_lifecycle.py` |
| 9. migrate_all skips corrupt silently | LOW | **FIXED** | `migrate.py` |
| 10. Daemon stop race (watchdog revive) | HIGH | **FIXED** | `daemon.py` |
| 11. ctx sync crashes on corrupt meta | MEDIUM | **FIXED** | `store.py` |


---

## Bug 12 — CRITICAL: SIGSEGV in Python GC during multi-threaded embedding

**Date:** 2026-08-20  
**Crash log:** macOS crash report, Python 3.12.14, ARM64

**Scenario:** MCP daemon is running. Keeper triggers incremental sync on a background thread. While embedding is in progress (tokenizers + numpy + zlib on Thread 7), Python's GC fires on another thread (Thread 5) and traverses a list with a dangling pointer.

**Crash signature:**
```
Thread 5 Crashed:
  visit_decref → list_traverse → deduce_unreachable → gc_collect_main
  EXC_BAD_ACCESS at 0xbf936d30508c749c (garbage address)
```

**Root cause:** The `tokenizers` library (Rust/Rayon) and `numpy` release the GIL during native computation. While the GIL is released, another Python thread can trigger GC. If the GC traverses Python container objects (lists, dicts) that the native code's Python-side is concurrently mutating (building result arrays, appending to lists), it can dereference freed or partially-initialized pointers.

This is a known class of CPython bug with native extensions that create/destroy Python objects rapidly while other threads may trigger GC.

**Thread analysis from crash:**
- Thread 0: MCP stdio poll (main loop)
- Thread 4: OnnxRuntime telemetry (condition_variable wait)
- Thread 5 (CRASHED): GC triggered during frame eval
- Thread 7: zlib.compress + numpy — actively building embedding vectors
- Thread 12-13: tokenizers Rayon worker pool

**Fix:** Disable Python GC for the duration of `_encode_batch()`. GC is re-enabled in a `finally` block immediately after the native work completes. This prevents GC from running on any thread while embedding intermediates exist.

```python
def _encode_batch(self, batch):
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        return self._encode_batch_inner(batch)
    finally:
        if gc_was_enabled:
            gc.enable()
```

**File:** `packages/pipeline/embedder.py`

**Status:** FIXED.

**Risk:** Disabling GC during embedding means short-lived objects accumulate until the batch completes. For typical batches (48 texts, <1s), this adds negligible memory pressure. The alternative (SIGSEGV crash) is unacceptable.

---

## Final Tally

| Bug | Severity | Status |
|-----|----------|--------|
| 1. Wipe deletes system dirs | HIGH | **FIXED** |
| 2+4. Empty CTX_REPO → managed=True | MEDIUM | **FIXED** |
| 3. Migrate crashes on corrupt meta | MEDIUM | **FIXED** |
| 5. Corrupt registry silent empty | LOW | **FIXED** |
| 6. Concurrent init race | MEDIUM | **FIXED** |
| 7. Migrate non-existent confusing msg | LOW | **FIXED** |
| 8. Init inside ce_home allowed | MEDIUM | **FIXED** |
| 9. migrate_all skips corrupt silently | LOW | **FIXED** |
| 10. Daemon stop race | HIGH | **FIXED** |
| 11. ctx sync crashes on corrupt meta | MEDIUM | **FIXED** |
| **12. SIGSEGV in GC during embedding** | **CRITICAL** | **FIXED** |

**12 bugs found. All fixed.**


---

## Round 5 Findings — Real-Life User Journeys (2026-08-20)

Method: Simulated actual user scenarios — registry deleted mid-session, accel.json missing, non-git repos, CTX_REPO mismatch, partial index from interruption, disk full, old-format meta, duplicate registry entries, remove mid-session, move ce_home, pip upgrade detection, rapid saves, env injection.

### Bug 13 — MEDIUM: Daemon /health has no version field

**Scenario:** User does `pip install -U scubiee` (upgrades from 0.2.17 → 0.2.18). The daemon is still running from the old version. CLI is now 0.2.18. User has no way to detect the mismatch.

**Impact:** After upgrading, new features/fixes don't take effect until the user manually restarts the daemon. No warning is shown. The version mismatch can cause subtle bugs (old daemon code + new CLI expectations).

**Fix:** Added `"version"` field to the `/health` response. CLI or MCP can now compare `health.version` against its own version and warn if they differ.

**File:** `packages/pipeline/ce_service.py`

**Status:** FIXED.

---

### Round 5 — What Passed (no bugs, scenarios that users will hit)

| Scenario | Result |
|----------|--------|
| Delete registry.json while daemon running | Survives, returns empty |
| Delete accel.json (fresh machine) | Embedder falls back to fastembed/cpu |
| Non-git repo (no .git directory) | Init + sync both work |
| CTX_REPO points to unregistered folder | Correctly not managed, grep works |
| Interrupted init (ctrl+C after 3s) | Re-init recovers cleanly |
| Disk full (read-only store) | PermissionError (graceful) |
| Old-format meta.json (v0.2.6 era) | Migration detects, sync works |
| Duplicate paths in registry | Listed, init picks correct one |
| Remove repo → instructions update | Immediately shows passive |
| Move ~/.context-engine away → restore | Empty list, then full restore |
| setup --repair preserves index | Confirmed (3007 chunks preserved) |
| 50 rapid saves (IDE simulation) | Grep sees latest, old gone |
| Shell injection in CTX_MCP_SURFACE | Validated to known surfaces |

---

## Grand Total (all rounds)

| Bug | Severity | Status |
|-----|----------|--------|
| 1. Wipe deletes system dirs | HIGH | **FIXED** |
| 2+4. Empty CTX_REPO → managed=True | MEDIUM | **FIXED** |
| 3. Migrate crashes on corrupt meta | MEDIUM | **FIXED** |
| 5. Corrupt registry silent empty | LOW | **FIXED** |
| 6. Concurrent init race | MEDIUM | **FIXED** |
| 7. Migrate non-existent confusing msg | LOW | **FIXED** |
| 8. Init inside ce_home allowed | MEDIUM | **FIXED** |
| 9. migrate_all skips corrupt silently | LOW | **FIXED** |
| 10. Daemon stop race | HIGH | **FIXED** |
| 11. ctx sync crashes on corrupt meta | MEDIUM | **FIXED** |
| 12. SIGSEGV in GC during embedding | CRITICAL | **FIXED** |
| 13. Daemon /health has no version | MEDIUM | **FIXED** |

**13 bugs found across 5 rounds. All 13 fixed.**


---

## Round 6 Findings — Human Behavior Simulation (2026-08-20)

Method: Simulated real user actions — git branch switch, npm install dump, nested repos, file renames, init home dir, docs-only repos, concurrent IDE windows, 50MB files, stale sessions, i18n queries, mid-session id.json deletion.

### Bug 14 — HIGH: ctx init accepts home directory

**Scenario:** User accidentally runs `ctx init ~/` or `ctx init ~/Downloads`.

**Behavior:** Succeeds. Would index ALL user files including `.ssh/`, credentials, browser data, etc.

**Fix:** Added `_is_too_broad()` guard that refuses home directory, `~/Desktop`, `~/Documents`, `~/Downloads`, filesystem root, and paths with ≤2 components.

**Status:** FIXED.

---

### Bug 15 — HIGH: Nested repo with .git gets parent's project_id

**Scenario:** User clones a second repo inside a managed repo (e.g., `git clone X ./vendor/X`).

**Behavior:** The nested repo inherits the parent's project_id due to git-family reconciliation logic (`git_common_dir` resolves upward).

**Root cause:** `resolve_project()` checks `(root / ".git").exists()` but a nested `.git` that isn't a fully initialized git repo (no objects) causes `git rev-parse --git-common-dir` to walk UP to the parent's real `.git`.

**Partial fix:** Added `has_own_git` detection (requires `.git/HEAD` or git worktree pointer file), and ignore `git_common_dir` if it resolves above root. However, git-family reconciliation is complex and the full fix risks breaking worktree dedup logic.

**Status:** Partially fixed. Works for real `git clone` operations (full .git/HEAD). Fake/empty .git dirs still inherit parent due to git CLI behavior.

---

### Bug 16 — MEDIUM: Subfolder init crashed with ValueError (regression from concurrent fix)

**Scenario:** `ctx init ./some_subfolder` where subfolder has no .git and is inside a managed repo.

**Behavior (before fix):** `mark_registered()` raised `ValueError: project_id_mismatch` because the subfolder resolved to parent's project_id but tried to register with the subfolder path.

**Fix:** Added try/except around `mark_registered` — if it raises ValueError or RegistryConflictError for a subfolder that resolved to parent, gracefully return the parent's project result.

**Status:** FIXED.

---

### Round 6 — What Passed (13/14 scenarios)

| Scenario | Result |
|----------|--------|
| Git branch switch (30 files swap) | Grep sees new, not old |
| npm install (2000 files in node_modules) | Correctly excluded from grep + sync |
| File extension rename (.py → .txt) | Grep reflects correctly |
| Docs-only repo (no code) | Registerable, grep works on .md |
| 10 concurrent health checks | All OK |
| 10KB search query | Handled without crash |
| Same filename in 3 dirs | All found |
| 50MB Python file | Grep handles (5 hits, capped) |
| Stale session data | No crash |
| Glob=* (all files) | Works, 20 hits truncated |
| Delete id.json mid-session | Correctly unmanaged, grep still works |
| Non-English queries (Chinese, Arabic, emoji, Japanese) | Handled |
| Rapid saves (50x in 2.5s) | Latest visible, old gone |
