# MacBook Handoff — 0.3.28 (idle-shutdown release)

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
4. **FastEmbed cache in `$TMPDIR`** — see section 2.
5. **Embed cache has no model fingerprint** — hash-fallback vectors persist silently.
6. **Mac: idle policy is correct, automatic reclaim is not.** After 15–25s with zero clients, `should_idle_stop(require_run_mode=False)` is True and `apply_idle_policy()` kills the engine. The supervisor/watchdog **did not** stop `pipeline engine run` on its own within 25s. This is the remaining Mac gate vs Windows.
7. **Full `pytest -q` on Mac does not finish.** First crash: `NotImplementedError: cannot instantiate 'WindowsPath' on your system` (a test/pathlib monkeypatch). Retry with `-k "not windows"` segfaulted in FAISS around 85% (`faiss/class_wrappers.py` recursion).
8. **`scripts/e2e_mcp_idle_reconnect.py` is not in this tree** — cannot run Phase 3 as written.
9. **`dense_index.py` RuntimeWarning** on `map` (divide/overflow in matmul) — noisy, did not block ranking.

---

---

## 6. Go / no-go

| Gate | Windows | Mac (Sep 8) |
|------|---------|-----|
| Unit suite (1318 passed / 7 known fails) | ✅ | ❌ crashed (WindowsPath, then FAISS segfault) |
| Idle suites (47 passed) | ✅ | ⚠️ 46 passed; 1 Windows-only fail (`test_windows_hidden_spawn_does_not_use_detached_process`) |
| Live idle reclaim verified | ✅ | ⚠️ policy + `apply_idle_policy()` PASS; automatic supervisor reclaim FAIL within 25s |
| MCP connect/disconnect/reconnect e2e | ⚠️ see note | ⬜ script missing from tree |
| Production test | ✅ | ⬜ not run (`connect --all` / `disconnect --all`) |
| CLI combination suite | ✅ | ✅ **39/39 PASS** |
| MLX/CoreML setup + query | N/A | ✅ MLX 101.8 t/s, map rank 1 `memory_governor.py` |
| Publish 0.3.28 | ⬜ | ⬜ **do not publish yet** — auto idle reclaim still open |

**⚠️ e2e note:** the MCP e2e still reports `engine stops within 180s of disconnect - FAIL`,
but that run predates the fix and its measurement was contaminated by orphaned `.venv`
watchdogs plus `/health` polling. Script was **not present** on Mac at `19e89fa`.

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

### Binary to use

```bash
export PATH="/Users/usmansayed/Downloads/hidden-context-engine-/.venv/bin:$PATH"
scubiee --version   # 0.3.28
```

### Publish decision

**Do not publish 0.3.28 yet.** MLX + CLI combo + idle *policy* are good. Automatic idle reclaim via supervisor/watchdog on Mac is still the open gate. Fix that, then rebuild the wheel, verify `require_run_mode` is in the wheel, and `twine`/`uv publish` from `.env` (`pipy_username` / `pipy_password`).
