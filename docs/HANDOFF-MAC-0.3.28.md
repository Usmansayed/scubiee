# MacBook Handoff — 0.3.28 (idle-shutdown release)

**Date:** Sep 8, 2026
**Windows state:** `0.3.28` **built but NOT published** — `dist/scubiee-0.3.28-py3-none-any.whl` exists locally
**Last published to PyPI:** `0.3.27` (contains the idle bug described below)
**Base commit:** `88f6624` — everything below is **uncommitted** working-tree state

---

## 0. Why this release exists

`0.3.27` shipped a bug that defeats the whole "shut the engine down 15s after disconnect"
feature. It was confirmed on the live Windows machine with a runtime probe, not by reading code:

```
is_running(): True     active clients: []     desired_mode: standby
should_idle_stop(require_run_mode=True)  : False   <-- shipped 0.3.27
should_idle_stop(require_run_mode=False) : True    <-- after fix
```

**A running engine with zero clients that never gets reclaimed.** It holds RAM until
reboot or a manual `scubiee stop`.

### Root cause

`should_idle_stop()` returned `False` unless `desired_mode == "run"`. Only two code paths
ever set `run`: `register_client()` (MCP connect) and `scubiee engine start`. So:

- **CLI-started engines never idle-stop.** `scubiee init`, `map`, `pack` start an engine
  and leave the mode at `standby` → the idle sweep skips it forever.
- **Wedge after a partial stop.** `enter_standby()` sets the mode to `standby` *before*
  attempting the stop. If the stop doesn't take, every later sweep hits the
  `already_standby` early-return and never retries.

### The fix (`packages/pipeline/lifecycle_runtime.py`)

1. `should_idle_stop(..., require_run_mode: bool = True)` — new keyword. The engine's own
   idle sweeper passes `False` so a CLI-started engine is reclaimable.
2. `apply_idle_policy()` computes `running = is_running()` first and only short-circuits on
   `already_standby` **when nothing is actually running**. A live engine keeps getting swept.

Verified live on Windows — the fix genuinely reclaimed a stuck engine:

```
apply_idle_policy -> action=standby
  engine stop: {"ok": true, "running": false, "killed": [21096]}
after : is_running = False
```

### Why the tests never caught it

Every pre-existing idle test called `life.set_desired_mode(life.DESIRED_RUN)` in setup, so
the standby path — the one the IDE and CLI actually take — was never exercised.
`tests/test_watchdog.py` was worse: it mocked `is_running` as permanently `True` while
`stop_daemon` reported success, a state that cannot exist.

Both are fixed, plus two new regression tests in `tests/test_idle_shutdown_reliability.py`:

- `test_apply_idle_policy_retries_stop_when_engine_survives_standby`
- `test_apply_idle_policy_noop_when_standby_and_no_engine`

---

## 1. Sync to the Mac

Working tree is large and uncommitted (53 tracked files changed, ~5.6k insertions, plus new
untracked packages). Sync the **whole working tree**, not a patch of `lifecycle_runtime.py`.

```bash
cd /path/to/context-engine
uv tool install --force . --refresh
scubiee --version        # expect 0.3.28
```

New untracked packages/modules that must be present:

```
packages/pipeline/heal_runtime.py
packages/pipeline/mcp_ship_check.py
packages/pipeline/locate_cli.py
packages/pipeline/mcp_plate.py
packages/pipeline/context_trace.py
packages/trace_lab/                 (whole package — eval harness)
fixtures/trace-lab/                 (eval corpus)
```

---

## 2. Read this before running anything destructive

A `pytest` run on Windows **destroyed the working machine setup** — twice. Root cause was
tests escaping `CTX_HOME` isolation and calling `wipe_all`, which sweeps `Path.home()`
defaults on top of `CTX_HOME`. It deleted `~/.scubiee`, the Cursor MCP config, the repo
enrollment, **and the CodeRank ONNX model weights**.

Guards are now in `tests/conftest.py` (`_guard_real_scubiee_home`, `_restore_repo_local_state`)
and `pytest.ini` excludes integration tests by default. **Do not remove these.**

`pytest.ini` now pins:

```ini
python_files = test_*.py          # stops auto-collecting *_production_test.py
addopts = -m "not integration"    # integration tests drive the real ~/.scubiee
```

### If the model weights go missing on Mac

Symptom: `warm_state: error`, `index_usable: false`, `scubiee init` fails with
`required dependencies unavailable: model_warmup`, and ~12 semantic tests fail.

The FastEmbed cache lives under the OS temp dir, so it is also vulnerable to temp cleanup:

```bash
# macOS location
ls "$TMPDIR/fastembed_cache/models--jamie8johnson--CodeRankEmbed-onnx/snapshots/"*/onnx/
# want: model_fp16.onnx  (>= 180 MB)
```

Repair with `scubiee setup --repair` (re-downloads FP32, converts to FP16, warms, recalibrates).

**Known design risk worth fixing later:** the model cache defaults to `$TMPDIR`, so an OS
temp sweep silently degrades the embedder to hash-fallback vectors. The HF snapshot metadata
survives, so nothing re-downloads — it just returns garbage embeddings. Consider pinning the
cache to `~/.scubiee/models`.

### Poisoned embedding caches

If the model was ever broken, on-disk vector caches hold hash-fallback vectors and there is
**no model fingerprint to invalidate them**. Clear before trusting any semantic result:

```bash
rm -rf fixtures/trace-lab/.embed_cache fixtures/trace-lab/.scubiee/cache
```

---

## 3. Mac test plan

### Phase 1 — Unit suite (~8 min)

```bash
python -m pytest -q --tb=line
```

**Expected on Windows: 1318 passed, 7 failed.** The 7 are all pre-existing and
**do not block release** — confirm you see the same set, and nothing new:

| Test | Verdict |
|------|---------|
| `test_polytrace.py` (2) | Untracked eval harness. F1 0.8637 vs 0.90 threshold, `mean_recall_must: 1.0` |
| `test_vague_prompts.py` (1) | Same harness, same cause |
| `test_verify_board.py` (1) | Same harness (`polytrace correct 18/20`) |
| `test_venture_stack.py::test_t3/t4` (2) | Hardcodes `GATE_PID = ce_d9cb766c…`; repo id is now `ce_541950414d46b26e6054921d4cd1eb86` |
| `test_setup_progress.py` (1) | Real but cosmetic: setup prints `✓ Runtime installed` twice |

All 7 are in **untracked** test files with no git baseline.

### Phase 2 — The idle fix (the point of this release)

Targeted suites first:

```bash
python -m pytest -q tests/test_idle_shutdown_reliability.py tests/test_watchdog.py \
  tests/test_engine_idle_debounce.py tests/test_memory_governor.py
# expect 47 passed
```

Then prove it live. **Poll the process table, never `/health`** — polling `/health` counts as
activity and keeps the engine alive, which invalidates the measurement:

```bash
scubiee init .                     # CLI-started engine => desired_mode stays "standby"
python - <<'PY'
from pipeline import lifecycle_runtime as life
from pipeline.daemon import is_running
print('mode        :', life.load_policy()['desired_mode'])   # expect standby
print('clients     :', life.reconcile_clients())             # expect []
print('is_running  :', is_running())                         # expect True
print('should_stop :', life.should_idle_stop(require_run_mode=False))  # expect True
PY

# wait ~20s with no activity, then confirm the engine is gone
sleep 25
pgrep -fl "pipeline engine run" || echo "engine reclaimed - PASS"
```

**Pass:** the engine exits within ~15–20s of going idle. On `0.3.27` it never does.

### Phase 3 — MCP connect / disconnect / reconnect

```bash
python scripts/e2e_mcp_idle_reconnect.py
```

Drives a real MCP client: handshake → `tools/list` → `status` → disconnect → wait for idle
shutdown → reconnect. **Before running, kill stray engines/watchdogs**, or orphans from
earlier runs will make it look like the engine "restarted itself":

```bash
pkill -f "pipeline engine" ; pkill -f "pipeline watchdog"
```

### Phase 4 — Mac production test

```bash
python tests/mac_production_test.py
```

The Windows twin was fixed this session to **restore your originally-connected MCP tools**
after its `connect --all` / `disconnect --all` round-trip (it used to leave the IDE
disconnected). Verify the Mac copy does the same — check your Cursor MCP still works after.

### Phase 5 — CLI combination suite

```bash
python scripts/run_cli_combination_tests.py --json /tmp/mac-cli.json
```

`unlock-tool` was **moved to the end** because it removes the `uv` tool directory and breaks
every later `scubiee` invocation ("Failed to canonicalize script path"). Keep it last.

### Phase 6 — Mac-specific (MLX / Apple Silicon)

```bash
scubiee setup                # expect mlx or coreml profile, not dml
scubiee init .
scubiee map "memory governor idle demote embedder warm tier"
scubiee status --json | grep -E 'warm_state|index_usable|chunks'
```

**Pass:** `warm_state: ready`, `index_usable: true`, chunks > 0, and `map` ranks
`packages/pipeline/memory_governor.py` first. The MLX path is **untested for this release** —
all verification so far was DirectML on Windows.

---

## 4. Also changed this session (needs Mac re-verification)

| Area | File | Change |
|------|------|--------|
| Sync debounce | `sync_loop.py`, `dirty_ledger.py` | 1500→1000ms, 2500→2000ms |
| Idle window | `lifecycle_runtime.py`, `mcp_install.py`, `certify.py` | 25s → **15s** |
| Warm hold | `memory_governor.py` | `_last_activity_at_locked` now takes `max(last_client_left_at, last_semantic_at)` — was demoting the embedder despite recent CLI queries |
| Hot reload | `mcp_hot_reload.py` | `adopt_installed_package_on_connect()` — picks up a new package on MCP reconnect |
| Stop/heal perf | `process_control.py`, `heal_runtime.py` | Name-prefilter before `_pid_is_protected`; sweep went from >90s to ~10s |
| Health probe | `client.py` | Fast-negative loopback check (Windows took ~2s on a closed port) |

**Mac relevance:** the `process_control.py` speedups were Windows-motivated (`psutil` cmdline
walks, `netstat`). Confirm `scubiee stop -y`, `halt`, and `heal` are still fast and correct on
macOS — the prefilters match on process *name*, which differs across platforms.

---

## 5. Known open issues (not fixed)

1. **Watchdog spawn leak** — 8 watchdog processes observed alive across 4 spawn pairs
   (`22:16:50`, `22:16:52` ×2, `22:35:47`). Not investigated. Check on Mac:
   `pgrep -fl "pipeline watchdog" | wc -l` should be small.
2. **Setup prints `✓ Runtime installed` twice** — cosmetic, caught by `test_setup_progress`.
3. **`test_t3` hardcodes a project id** — will fail on any machine whose repo id differs.
4. **FastEmbed cache in `$TMPDIR`** — see section 2.
5. **Embed cache has no model fingerprint** — hash-fallback vectors persist silently.

---

## 6. Go / no-go

| Gate | Windows | Mac |
|------|---------|-----|
| Unit suite (1318 passed / 7 known fails) | ✅ | ⬜ |
| Idle suites (47 passed) | ✅ | ⬜ |
| Live idle reclaim verified | ✅ | ⬜ |
| MCP connect/disconnect/reconnect e2e | ⚠️ see note | ⬜ |
| Production test | ✅ | ⬜ |
| CLI combination suite | ✅ | ⬜ |
| MLX/CoreML setup + query | N/A | ⬜ |
| Publish 0.3.28 | ⬜ | ⬜ |

**⚠️ e2e note:** the MCP e2e still reports `engine stops within 180s of disconnect - FAIL`,
but that run predates the fix and its measurement was contaminated by orphaned `.venv`
watchdogs plus `/health` polling. **Re-run it clean on Mac** — this is the main gate left.

---

## 7. Publish steps (after Mac passes)

Credentials are in the env file (PyPI username/password) — not in the shell, so `uv publish`
fails with `Missing credentials` unless they're exported.

```bash
# already built on Windows; rebuild on Mac if syncing source
uv build

# verify the fix is actually in the wheel before uploading
python - <<'PY'
import zipfile
src = zipfile.ZipFile('dist/scubiee-0.3.28-py3-none-any.whl').read('pipeline/lifecycle_runtime.py').decode()
print('require_run_mode :', 'require_run_mode: bool = True' in src)
print('DEFAULT_IDLE_S   :', [l for l in src.splitlines() if l.startswith('DEFAULT_IDLE_S')])
PY

export UV_PUBLISH_USERNAME=... UV_PUBLISH_PASSWORD=...   # from env file
uv publish
```

Then on each machine: `uv tool install --force scubiee --refresh`.

`npm/package.json` was bumped to 0.3.28 in lockstep — confirm whether npm also needs a
publish or is only kept in sync.
