# MacBook Handoff — 0.3.28 (idle-shutdown release)

> **SUPERSEDED — read `docs/HANDOFF-MAC-0.3.29.md` instead.**
>
> The header and sections 1–8 below are stale: 0.3.28 *was* published, the last PyPI release
> before it was 0.3.26 (not 0.3.27), and the remote is now `scubiee.git`. **Do not install
> 0.3.28** — its model-cache fix is inert. Sections 9–12 remain accurate and record how each
> fix was found; section 8 is the Mac's own session log.

**Date:** Sep 8, 2026
**Windows state:** `0.3.28` **built but NOT published** — `dist/scubiee-0.3.28-py3-none-any.whl` exists locally
**Last published to PyPI:** `0.3.27` (contains the idle bug described below)
**Git:** `19e89fa` on `upstream/main` (`https://github.com/Usmansayed/new-context-engine.git`)
**Mac verification:** Sep 8, 2026 — Apple Silicon, fresh `.venv`, MLX ~101.8 t/s (see section 8)

---

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

**Done on Mac (Sep 8).** `git pull --ff-only upstream main` landed at `19e89fa`. Local tool-config files (`.claude/CLAUDE.md`, `.codex/AGENTS.md`, Copilot/Pi GATE files) blocked the pull and were moved aside first.

Do **not** `uv tool install` from PyPI — **0.3.28 is not on PyPI yet**. Install from the tree:

```bash
cd /path/to/context-engine
git pull upstream main
uv venv .venv
uv pip install -e ".[mcp]" pytest
export PATH="$PWD/.venv/bin:$PATH"
scubiee --version        # expect 0.3.28
```

Mac used this path after wiping the previous `uv tool` install (`scubiee 0.3.6` at `~/.local/bin`).

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
`packages/pipeline/memory_governor.py` first.

**Mac result (Sep 8):** PASS — MLX 101.8 t/s, `warm_state: ready`, `index_usable: true`, 5679 chunks, `map` rank 1 = `packages/pipeline/memory_governor.py`.

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
   **Mac (Sep 8):** watchdog count was **0** after setup/init. Supervisor (`engine supervisor --logon`) stayed at 1 process. No leak seen in this run.
2. **Setup prints `✓ Runtime installed` twice** — cosmetic, caught by `test_setup_progress`.
3. **`test_t3` hardcodes a project id** — will fail on any machine whose repo id differs.
4. ~~**FastEmbed cache in `$TMPDIR`**~~ **FIXED — see section 10.** Stopped being theoretical:
   the weights were wiped from `%TEMP%` twice inside 24h on Windows.
5. **Embed cache has no model fingerprint** — hash-fallback vectors persist silently.
   Still open, and it is what makes #4 so costly: once the model is gone, the poisoned
   vectors survive in `.embed_cache` with nothing to invalidate them.
6. ~~**Mac: idle policy is correct, automatic reclaim is not.**~~ **FIXED — `9bae058`, see section 9.** The Mac diagnosis was right and the cause was not platform-specific: nothing could kill the engine because `stop_daemon`'s sweep skips `self_or_ancestor`, i.e. the engine's own pid. Manual `apply_idle_policy()` worked only because it ran from an *external* process.
7. **Full `pytest -q` on Mac does not finish.** First crash: `NotImplementedError: cannot instantiate 'WindowsPath' on your system` (a test/pathlib monkeypatch). Retry with `-k "not windows"` segfaulted in FAISS around 85% (`faiss/class_wrappers.py` recursion).
8. **`scripts/e2e_mcp_idle_reconnect.py` is not in this tree** — cannot run Phase 3 as written.
9. **`dense_index.py` RuntimeWarning** on `map` (divide/overflow in matmul) — noisy, did not block ranking.

---

---

## 6. Go / no-go

| Gate | Windows (Sep 9, `9bae058`) | Mac (Sep 8, `19e89fa`) |
|------|---------|-----|
| Unit suite (1318 passed / 7 known fails) | ✅ | ❌ crashed (WindowsPath, then FAISS segfault) |
| Idle suites | ✅ **50 passed** (47 + 3 new self-retire tests) | ⚠️ 46 passed; 1 Windows-only fail (`test_windows_hidden_spawn_does_not_use_detached_process`) |
| Live **automatic** idle reclaim | ✅ **engine gone ~9s after idle, unattended** | ⚠️ was FAIL — re-run on `9bae058` |
| MCP connect/disconnect/reconnect e2e | ✅ **ALL PASS** — engine stopped 22.3s after disconnect, reconnect served | ⬜ harness now committed, re-run |
| Production test | ✅ | ⬜ not run (`connect --all` / `disconnect --all`) |
| CLI combination suite | ✅ | ✅ **39/39 PASS** |
| MLX/CoreML setup + query | N/A | ✅ MLX 101.8 t/s, map rank 1 `memory_governor.py` |
| Publish 0.3.28 | ✅ **LIVE on PyPI (Sep 9)** — `23e6ebe` | ⬜ **re-verify sections 9 + 10 on Mac** |

**e2e note (resolved Sep 9):** the earlier `engine stops within 180s of disconnect - FAIL`
predated the self-retire fix. Re-run clean on `9bae058` with orphans cleared, it passes:

```
[PASS] engine stopped after disconnect - 22.3s
[PASS] shutdown not premature (>= idle window) - 22.3s vs 15.0s
[PASS] session 2 (reconnect): status tool responds
```

The harness is now committed at `scripts/e2e_mcp_idle_reconnect.py` (it is cross-platform —
`psutil` for the passive liveness check, `shutil.which` for the bridge). Clear stray engines
and watchdogs first, and put the venv on `PATH` so `scubiee-mcp-bridge` resolves.

---

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

---

## 8. Mac session log (Sep 8, 2026)

**Machine:** Apple Silicon MacBook  
**Repo:** `/Users/usmansayed/Downloads/hidden-context-engine-`  
**Remote:** `upstream` = `https://github.com/Usmansayed/new-context-engine.git`  
**HEAD after pull:** `19e89fa` — Release 0.3.28: fix idle shutdown never reclaiming the engine

### What we did

1. **Pulled latest** from `new-context-engine` (`398b9ba` → `19e89fa`). Fast-forward after moving aside local MCP GATE files that would have been overwritten.
2. **Read** `docs/HANDOFF-MAC-0.3.28.md` and followed the destructive-test warnings.
3. **Deleted the old setup:**
   - `pkill` stray `pipeline engine` / watchdog
   - `scubiee wipe --all --confirm --keep-package` (removed `~/.scubiee`; leftover Codex `~/.codex/config.toml` only)
   - `uv tool uninstall scubiee` (removed PATH binary **0.3.6**)
   - removed old venvs: `.venv`, `/tmp/scubiee-bughunt-venv`, `/tmp/scubiee-fresh-venv`
4. **Fresh install from source (not PyPI):**
   ```bash
   uv venv .venv
   uv pip install -e ".[mcp]" pytest
   .venv/bin/scubiee --version   # 0.3.28
   ```
   Confirmed `DEFAULT_IDLE_S = 15.0` and `should_idle_stop(..., require_run_mode=...)` in the installed package.
5. **`scubiee setup`** — MLX profile, CodeRank FP16 convert + warmup, **~101.8 t/s**.
6. **`scubiee init .`** — enrolled this repo, indexed.
7. **Tests run (user-facing CLI + targeted pytest):**

| Step | Command / suite | Result |
|------|-----------------|--------|
| Idle unit | `pytest tests/test_idle_shutdown_reliability.py tests/test_watchdog.py tests/test_engine_idle_debounce.py tests/test_memory_governor.py` | **46 passed**, 1 fail: `test_windows_hidden_spawn_does_not_use_detached_process` (CREATE_NO_WINDOW on Darwin) |
| Live idle t=0 after init | `desired_mode=run`, clients `[]`, `is_running=True`, `should_idle_stop(require_run_mode=False)=False` (idle window not elapsed) | expected |
| Live idle t=22s | `mode=standby`, `should_stop=True`, engine still running until **`apply_idle_policy()`** | killed pid 32340, `is_running=False` |
| Auto idle t=25s with supervisor | `engine ensure .` then wait, **no `/health`** | `should_stop=True`, **engine still running** (pid 32448) |
| CLI combo | `python scripts/run_cli_combination_tests.py --json /tmp/mac-cli-0.3.28.json` | **39/39 PASS** (~233s). `unlock-tool` last as designed. |
| MLX map | `scubiee map "memory governor idle demote embedder warm tier"` | rank 1 `packages/pipeline/memory_governor.py` |
| Status | `scubiee status --json` | `warm_state: ready`, `index_usable: true`, **5679 chunks**, enrolled/active |
| Watchdogs | `pgrep -fl "pipeline watchdog"` | **0** |
| Full pytest | `pytest -q --tb=line` | INTERNALERROR `WindowsPath` on Darwin ~21% |
| Full pytest retry | `pytest -q -k "not windows"` | segfault in FAISS ~85% |
| MCP e2e script | `scripts/e2e_mcp_idle_reconnect.py` | **missing** |
| `mac_production_test.py` | connect/disconnect `--all` | **not run** (destructive) |

8. **Restored Cursor MCP:** `scubiee connect --cursor` after wipe. Restart Cursor to pick up the pin.

---

## 9. Windows follow-up — auto-reclaim gate closed (Sep 9, `9bae058`)

The Mac's open issue #6 was the last real blocker, and it was **not** a Mac problem.

### Why `apply_idle_policy()` worked by hand but never on its own

The idle sweeper runs *inside* the engine. It called `apply_idle_policy()` → `enter_standby()`
→ `stop_daemon()`, which sweeps engine pids through `safe_terminate_pid` — and that function
skips `self_or_ancestor`. The one pid that mattered was always skipped, so every sweep
reported `running: True` and the sweeper looped forever against a stop that could not succeed.
The Mac's manual check passed because a `python -` one-liner is a *different process*, so
nothing was skipped.

The old sweeper also swallowed the result in a bare `except: pass`, so this was invisible in
`engine.log` for as long as it has existed.

### Fix (`packages/pipeline/server.py`)

`run_server` registers its `ThreadingHTTPServer` in a module global. When a sweep returns
`action=standby` but still reports `running`, the sweeper calls `_retire_self()`, which runs
`server.shutdown()` on a side thread — `serve_forever()` returns, `run_server` returns, and
the existing `atexit` hook does `ce.shutdown()` + `release_lock()`. The sweep result is now
logged either way.

### Live evidence (Windows, unattended — process table polled, never `/health`)

```
[engine] idle sweep: action=standby engine={'ok': False, 'running': True, 'killed': [9976],
                     'remaining_pids': [9976], 'still_healthy': True, 'stop_reason': 'user'}
[engine] idle sweep: retiring self (external stop cannot kill the engine's own pid)

t=0s  engine pids: 29544,9976
t=9s  ENGINE GONE     → engine.lock released, port 8765 free, index intact (6115 chunks)
```

Note `ok: False` / `remaining_pids: [9976]` — that is the external stop failing to kill
itself, captured live.

### Tests

`tests/test_idle_shutdown_reliability.py` +3 (**50 passed** in the four idle suites):

- `test_retire_self_reports_false_without_a_server`
- `test_idle_sweeper_retires_self_when_stop_cannot_kill_own_pid`
- `test_idle_sweeper_keeps_sweeping_when_engine_actually_stopped`

`_start_idle_sweeper` now takes a `stop_event` and returns its thread so these run
deterministically instead of on wall-clock sleeps.

### For the Mac

1. `git pull` to `9bae058` and re-run the section 2 / Phase 2 live idle check. Expect the
   engine to disappear on its own within ~15–20s, with `retiring self` in `engine.log`.
2. **The 0.3.28 wheel was rebuilt** — the earlier one predates this fix. Verified to contain
   `_retire_self`, `_register_httpd`, `require_run_mode`, `DEFAULT_IDLE_S = 15.0`.
3. `scripts/e2e_mcp_idle_reconnect.py` (open issue #8) was a scratch script and never
   committed — that is why it was missing. **Now committed**, and passing on Windows.
4. **Watchdog leak (open issue #1) reproduces on Windows:** 8 orphans found at session start,
   and each `engine ensure` leaves a pair behind. Untouched by this release.

### Binary to use

```bash
export PATH="/Users/usmansayed/Downloads/hidden-context-engine-/.venv/bin:$PATH"
scubiee --version   # 0.3.28
```

### Publish decision

**Do not publish 0.3.28 yet.** MLX + CLI combo + idle *policy* are good. Automatic idle reclaim via supervisor/watchdog on Mac is still the open gate. Fix that, then rebuild the wheel, verify `require_run_mode` is in the wheel, and `twine`/`uv publish` from `.env` (`pipy_username` / `pipy_password`).

---

## 10. Model cache pinned out of the OS temp dir (Sep 9)

Open issue #4 stopped being a design risk and became the top cost of this release: the
CodeRank weights were wiped from `%TEMP%` **twice inside 24 hours** on Windows. Each time it
cost a full `setup --repair` plus a confusing round of "failing" embed tests.

### Why it is worse than a plain cache miss

`fastembed.common.utils.define_cache_dir()` defaults to `$TMPDIR/fastembed_cache`. A temp
sweep removes the blobs but leaves the Hugging Face snapshot metadata, so **nothing
re-downloads** — the embedder just falls back to hash vectors and keeps answering. Retrieval
quality collapses with no error anywhere. Worse, those hash vectors get written into
`.embed_cache`, which has no model fingerprint, so they outlive the repair (open issue #5).

Our own `default_fastembed_cache_root()` already returned a safe `~/.cache/fastembed`, but
`fastembed_cache_root()` preferred `define_cache_dir()` — so the safe path only applied when
fastembed was *not installed*, i.e. never in production.

### Fix

- `fastembed_cache_root()` now returns the durable root and publishes it as
  `FASTEMBED_CACHE_PATH`. That matters because `TextEmbedding` resolves the directory itself
  at load time — six construction sites, none of which passed `cache_dir`.
- The two in `embedder.py` now pass `cache_dir=` explicitly as well.
- `coreml_mac._fastembed_cache_root()` delegates to accel instead of resolving its own.
- One-time migration adopts an existing temp cache instead of re-downloading, and never
  overwrites a durable copy.
- An explicit `FASTEMBED_CACHE` / `FASTEMBED_CACHE_PATH` still wins.

Anchored to `~/.cache/fastembed`, **not** `~/.scubiee/models`: tests point `CTX_HOME` at temp
dirs, so a `CTX_HOME`-relative cache would re-download the model on every run. `wipe.py`
already sweeps both locations, so `wipe --all` is unchanged.

### Verified live on Windows

```
BEFORE   temp: 785.1 MB   durable: absent
AFTER    temp:     0 MB   durable: 785.1 MB      # migrated, not re-downloaded
coderank_fp16_onnx_ready() -> True
```

62 passed across `test_embed_power`, `test_seeded_compare`, `test_venture_stack`,
`test_coderank_fp16`, `test_coreml_mac`, `test_mlx_mac`, `test_wipe` — only the two known
hardcoded-project-id failures remain. Tests added in `tests/test_coderank_fp16.py`:

- `test_cache_root_is_not_the_os_temp_dir`
- `test_cache_root_is_published_to_the_environment`
- `test_cache_root_honors_an_explicit_override`
- `test_existing_tmp_cache_is_adopted_not_redownloaded`
- `test_migration_never_clobbers_the_durable_copy`

### For the Mac — this one needs your verification most

macOS is where `$TMPDIR` is most aggressively swept, and the MLX/CoreML paths resolve the
cache through `coreml_mac._fastembed_cache_root()`, which this change rewires.

```bash
python - <<'PY'
from pipeline.accel import fastembed_cache_root, coderank_fp16_onnx_ready
print('root :', fastembed_cache_root())      # expect ~/.cache/fastembed, NOT $TMPDIR
print('ready:', coderank_fp16_onnx_ready())  # expect True, migrated not re-downloaded
PY
du -sh "$TMPDIR/fastembed_cache" ~/.cache/fastembed 2>/dev/null
scubiee map "memory governor idle demote embedder warm tier"   # still rank 1 memory_governor.py
```

Confirm MLX still warms at ~100 t/s and that `scubiee setup --repair` writes to the durable
root rather than recreating the temp one.

---

## 11. Published (Sep 9, 2026)

`scubiee 0.3.28` is **live on PyPI**, built from `23e6ebe`. Contents verified by downloading
the published wheel back from PyPI, not by trusting the local build:

```
_retire_self (engine self-stop) : True
require_run_mode (idle policy)  : True
DEFAULT_IDLE_S = 15.0
FASTEMBED_CACHE_PATH pinned     : True
_migrate_legacy_tmp_cache       : True
```

Note: the previous latest on PyPI was **0.3.26**, not 0.3.27 as section 0 assumed — 0.3.27
was only ever a local build. So 0.3.28 carries the 0.3.27 changes too.

Upgrade any machine with:

```bash
uv tool install --force scubiee --refresh
scubiee --version    # 0.3.28
```

On first run after upgrading, `fastembed_cache_root()` migrates an existing
`$TMPDIR/fastembed_cache` into `~/.cache/fastembed` — a move, not a re-download.

**Still to do on Mac:** sections 9 and 10 remain unverified on Apple Silicon. Publishing was
a deliberate call to stop blocking on cross-machine verification; if the Mac finds a problem
in the MLX/CoreML cache path, it needs a 0.3.29.

`npm/package.json` is at 0.3.28 in lockstep but **was not published** — still unclear whether
the npm package needs its own release or is only kept in sync.

---

## 12. 0.3.29 — do NOT verify 0.3.28, its cache fix is inert (Sep 9)

**Skip 0.3.28. Install `scubiee==0.3.29`.**

Section 10's fix set `FASTEMBED_CACHE_PATH` *inside* `fastembed_cache_root()`, so the pin only
applied if something called that function first. The engine's warmup path never does. Caught
on the live engine right after publishing 0.3.28:

```
fastembed...retrieve_model_gcs - Could not find the model tar.gz file at
C:\Users\usman\AppData\Local\Temp\fastembed_cache\CodeRankEmbed and local_files_only=True
```

Still `$TMPDIR`, and `status` reported `warm_state: error`. `TextEmbedding` resolves its own
cache dir, and four `accel.py` sites plus the `preflight.py` warmup never passed `cache_dir` —
only the two in `embedder.py` were fixed.

**0.3.29** moves the root into a dependency-free `pipeline/model_cache.py` and pins it from
`pipeline/__init__`, before anything can import fastembed. `preflight` also passes `cache_dir`
explicitly. The regression test shells out to a **fresh interpreter**, because the test process
is already pinned and would have passed against the broken build.

### Full clean-slate validation on Windows (0.3.29)

Wiped everything — `~/.scubiee`, repo `.scubiee`, both model caches, the uv tool — then:

| Step | Result |
|------|--------|
| `uv tool install scubiee==0.3.29` | 0.3.29, `FASTEMBED_CACHE_PATH=~/.cache/fastembed` at import |
| `scubiee setup` | **916.7 MB in `~/.cache/fastembed`; `%TEMP%/fastembed_cache` never created** |
| `scubiee init .` | enrolled, 6132 chunks, `warm_state: ready`, `index_usable: true` |
| `scubiee connect --cursor` | scubiee added, **existing `figma` server preserved**, build pin `0.3.29-…` |
| GATE files | `AGENTS.md` + `.cursor/rules/scubiee.mdc` regenerated with the new project id |
| `scubiee map` | rank 1 `packages/pipeline/memory_governor.py`, score 8.17 (real vectors) |
| Idle reclaim | self-retired unattended, `retiring self` in `engine.log` |
| Cache after full run | still 916.7 MB, temp still absent |

Note `wipe --all` cannot delete its own running shims — it exits non-zero and asks you to
re-run. Follow it with `uv tool uninstall scubiee`.

Watchdog leak (open issue #1) still reproduces: 2 per session on Windows.
