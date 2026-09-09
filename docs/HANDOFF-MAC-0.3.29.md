# MacBook Handoff — 0.3.29

**Date:** Sep 9, 2026
**Published:** `scubiee 0.3.29` is **live on PyPI**
**Commit:** `757faaf` on `origin/main` (`https://github.com/Usmansayed/scubiee.git`)
**Supersedes:** `docs/HANDOFF-MAC-0.3.28.md` — that document's header and sections 1–8 are stale.
Read it only for the Mac session log (section 8) and the fix write-ups (sections 9–12).

> **Do not install 0.3.28.** It is on PyPI but ships a fix that does nothing. See §2.

---

## 1. What to do

```bash
cd /path/to/context-engine
git pull                                   # 757faaf or later
uv tool install "scubiee==0.3.29" --force --refresh
scubiee --version                          # 0.3.29
```

Then the clean-slate run, which is what needs verifying:

```bash
scubiee setup
scubiee init .
scubiee connect --cursor
```

---

## 2. The two fixes in this release

### 2a. An idle engine can now stop itself (`0.3.28`, verified)

You reported that `apply_idle_policy()` worked by hand but the engine never stopped on its
own. That diagnosis was right, and the cause was **not** macOS-specific.

The idle sweeper runs *inside* the engine and stopped it via `stop_daemon()`, whose sweep
calls `safe_terminate_pid`, which skips `self_or_ancestor`. The one pid that mattered was
always skipped, so every sweep reported `running: True` and looped against a stop that could
never succeed. Your manual check passed only because a `python -` one-liner is a separate
process. The sweeper also swallowed the result in a bare `except: pass`, so this was invisible
in `engine.log` for as long as it has existed.

`run_server` now registers its `ThreadingHTTPServer`, and a sweep that returns
`action=standby` while still reporting `running` calls `_retire_self()` — `server.shutdown()`
on a side thread, so `serve_forever()` returns and the existing `atexit` hook does
`ce.shutdown()` + `release_lock()`.

### 2b. Model cache pinned out of `$TMPDIR` (`0.3.29`, needs your verification)

`fastembed.common.utils.define_cache_dir()` defaults to `$TMPDIR/fastembed_cache`. A temp
sweep takes the blobs but leaves the Hugging Face snapshot metadata, so **nothing
re-downloads** — the embedder silently falls back to hash vectors and keeps answering.
Retrieval quality collapses with no error. Observed twice on Windows in 24 hours.

**0.3.28 tried to fix this and failed.** It set `FASTEMBED_CACHE_PATH` inside
`fastembed_cache_root()`, so the pin only applied if something called that function first.
The engine's warmup path never does:

```
fastembed...retrieve_model_gcs - Could not find the model tar.gz file at
...\Temp\fastembed_cache\CodeRankEmbed and local_files_only=True
```

`TextEmbedding` resolves its own cache directory, and of seven construction sites only the two
in `embedder.py` passed `cache_dir`.

**0.3.29** moves the root into a dependency-free `pipeline/model_cache.py` and pins it from
`pipeline/__init__`, before anything can import fastembed. `preflight.py` also passes
`cache_dir` explicitly. Anchored to `~/.cache/fastembed`, **not** `~/.scubiee/models`: tests
point `CTX_HOME` at temp dirs, and a `CTX_HOME`-relative cache would re-download every run.

---

## 3. Why this one needs the Mac specifically

`coreml_mac._fastembed_cache_root()` used to call `define_cache_dir()` directly; it now
delegates to `accel`. **That function is in the Apple Silicon model-loading path**, and no
part of 0.3.29 has run on macOS. This is the highest-risk area of the release for you.

macOS is also where `$TMPDIR` is swept most aggressively, so 2b matters more there than on
Windows.

```bash
python - <<'PY'
import pipeline, os                      # the pin happens at import
from pipeline.accel import fastembed_cache_root, coderank_fp16_onnx_ready
print('env  :', os.environ['FASTEMBED_CACHE_PATH'])   # ~/.cache/fastembed, NOT $TMPDIR
print('root :', fastembed_cache_root())
print('ready:', coderank_fp16_onnx_ready())
PY

du -sh "$TMPDIR/fastembed_cache" ~/.cache/fastembed 2>/dev/null
```

**Pass:** weights under `~/.cache/fastembed`, `$TMPDIR/fastembed_cache` absent or empty, MLX
still warming near ~100 t/s.

If you already have weights in `$TMPDIR`, 0.3.29 **moves** them on first use rather than
re-downloading. Confirm the move rather than a 900 MB download.

---

## 4. Verify the idle fix

```bash
python -m pytest -q tests/test_idle_shutdown_reliability.py tests/test_watchdog.py \
  tests/test_engine_idle_debounce.py tests/test_memory_governor.py
# Windows: 50 passed. Expect 1 Windows-only failure on Darwin:
#   test_windows_hidden_spawn_does_not_use_detached_process
```

Live, **polling the process table — never `/health`**, which counts as activity and holds the
engine open:

```bash
pkill -f "pipeline engine" ; pkill -f "pipeline watchdog"   # orphans fake a "restart"
scubiee engine ensure .
sleep 30
pgrep -fl "pipeline engine run" || echo "reclaimed - PASS"
grep "retiring self" ~/.scubiee/engine.log
```

Then the end-to-end, which is now committed (it was missing from your tree because it had
never been committed — that was my omission):

```bash
python scripts/e2e_mcp_idle_reconnect.py
```

Windows result: engine stopped 22.3s after disconnect, reconnect served, all checks passed.

---

## 5. Windows results for 0.3.29 (full clean slate)

Wiped `~/.scubiee`, repo `.scubiee`, both model caches, and the uv tool, then rebuilt from
PyPI:

| Step | Result |
|------|--------|
| `uv tool install scubiee==0.3.29` | pin active at import |
| `scubiee setup` | **916.7 MB into `~/.cache/fastembed`; `$TMPDIR` copy never created** |
| `scubiee init .` | enrolled, 6132 chunks, `warm_state: ready`, `index_usable: true` |
| `scubiee connect --cursor` | scubiee added, pre-existing `figma` server preserved |
| GATE files | `AGENTS.md` + `.cursor/rules/scubiee.mdc` regenerated with the new project id |
| `scubiee map` | rank 1 `packages/pipeline/memory_governor.py`, score 8.17 (real vectors) |
| Idle reclaim | self-retired unattended, `retiring self` in `engine.log` |
| Targeted suites | 50 idle + 51 cache passed |

Note `wipe --all` cannot delete its own running shims — it exits non-zero and asks for a
re-run. Finish with `uv tool uninstall scubiee`.

---

## 6. Test-suite hygiene — do not remove these

A `pytest` run destroyed the working Windows setup twice: tests escaped `CTX_HOME` isolation
and called `wipe_all`, which sweeps `Path.home()` defaults on top of `CTX_HOME`. It took
`~/.scubiee`, the Cursor MCP config, the repo enrollment, and the model weights.

Guards now live in `tests/conftest.py` (`_guard_real_scubiee_home`, `_restore_repo_local_state`)
and `pytest.ini` pins:

```ini
python_files = test_*.py          # stops auto-collecting *_production_test.py
addopts = -m "not integration"    # integration tests drive the real ~/.scubiee
```

**Measurement warning:** a live engine on port 8765 contaminates a full-suite run. It caused
six spurious failures here, including `test_watchdog.py::test_loop_idle_stop_is_not_watchdogs_job`.
Kill engines before running the suite.

---

## 7. Known open issues

1. **Watchdog spawn leak** — a pair per session that never exits; 8 accumulated in one day on
   Windows. Not investigated. `pgrep -fl "pipeline watchdog" | wc -l`
2. **Embed cache has no model fingerprint.** If the model ever breaks, hash-fallback vectors
   persist in `.embed_cache` with nothing to invalidate them, and survive the repair. This is
   the highest-value remaining fix — it is what turned a recoverable problem into hours of
   confusing test failures, twice.
   ```bash
   rm -rf fixtures/trace-lab/.embed_cache fixtures/trace-lab/.scubiee/cache
   ```
3. **Seven known test failures**, none release-blocking: four from the untracked `trace_lab`
   eval harness, two (`test_venture_stack::test_t3/t4`) hardcoding a stale project id, one
   cosmetic (`setup` prints `✓ Runtime installed` twice).
4. **Full `pytest` did not complete on macOS** on your last run — `WindowsPath` instantiation,
   then a FAISS segfault around 85%. Unresolved; your CLI suite passing 39/39 was the more
   meaningful signal.
5. **npm** `npm/package.json` is at 0.3.29 in lockstep but unpublished — unclear whether it
   needs its own release.

---

## 8. Confidence note

Two fixes were wrong on the first attempt today. The idle fix looked verified until you found
that automatic reclaim never fired, and the cache fix reached PyPI in a state where it did
nothing. Both were caught by exercising the real runtime, not by unit tests — the unit tests
passed in both cases.

So weight your runtime checks over the suite, and treat §3 as the real gate.

---

## 9. Mac results for 0.3.29 — §3 and §4 both pass

Run from source at `ccbc72a` in a venv (`uv pip install -e .`), not the PyPI shim. Killed the
engines and booted out the `com.contextengine.supervisor` launchd agent first — its `KeepAlive`
respawns the supervisor within seconds and fakes exactly the "restart" §4 warns about.
`scubiee setup` re-registers it at the end.

| Check | Result |
|-------|--------|
| §3 pin at import | `FASTEMBED_CACHE_PATH=~/.cache/fastembed`, **not** `$TMPDIR` |
| §3 `coreml_mac._fastembed_cache_root()` | delegates to `accel`, same root — the Apple Silicon path is clean |
| `scubiee setup` | **795 MB into `~/.cache/fastembed`; `$TMPDIR/fastembed_cache` never created** |
| MLX warm | `backend=mlx device=gpu metal=true`, ready in 83ms, **109.8 t/s** |
| `scubiee init .` | enrolled, 5710 chunks, `warm_state: ready`, `index_usable: true` |
| `scubiee connect --cursor` | scubiee added, pre-existing `figma` preserved |
| `scubiee map` | rank 1 `lifecycle_runtime.py::apply_idle_policy`, score 25.05 (real vectors) |
| Idle reclaim, live | **self-retired unattended at ~40s**, `retiring self` in `engine.log` |
| `e2e_mcp_idle_reconnect.py` | **all checks passed**, engine stopped 19.5s after disconnect |
| Targeted idle suites | 49 passed + the predicted Darwin `test_windows_hidden_spawn` failure |
| `test_coderank_fp16.py` | 20 passed |
| CLI combination | 39/39 |
| Full `pytest` | **completes for the first time on macOS** — 1277 passed, 59 failed, 183s |

§2b reproduced here before the fix landed: yesterday's `setup` put the weights in `$TMPDIR`,
and less than a day later that directory was already gone. So there was nothing for 0.3.29 to
migrate — it did a clean ~900 MB download into `~/.cache/fastembed`.

The e2e is worth one warning. With the model missing it reports `engine stopped after
disconnect - 0.0s` as a **PASS**, because an engine that never started is trivially stopped.
Three checks failed and none of them named the real cause. Run it only after `setup`.

### 9a. The FAISS segfault is a real bug, now fixed

`faiss_import_ok()` in `install_health.py` popped `faiss` out of `sys.modules` and re-imported
it as a health probe. The `_swigfaiss` C extension stays cached, so `faiss/__init__` re-applied
`class_wrappers` to the *same* class objects, and `handle_IDSelectorSubset` — which stores
`original_init` as a class attribute and calls it via `self.original_init` — ended up pointing
it at its own `replacement_init`. Every later `IDSelector` construction then recursed until the
C stack died.

That is §7.4's unexplained "FAISS segfault around 85%". It is product code, not a test artifact:
any long-lived engine or MCP worker that runs a health probe and later does a vector delete or
compaction is exposed. `faiss_import_ok` now returns `True` when the module is already imported.

Twelve-line reproducer, if it ever regresses:

```python
import sys, numpy as np, pipeline, faiss
from pipeline.install_health import faiss_import_ok
ids = np.array([1, 2, 3], dtype="int64")
faiss.IDSelectorBatch(ids)              # fine
faiss_import_ok()                       # poisons the wrappers
sys.setrecursionlimit(120)
faiss.IDSelectorBatch(ids)              # RecursionError; SIGSEGV at the real limit
```

### 9b. The `WindowsPath` abort was one test, not the platform

`test_merkle_canonical_folds_case_on_windows` patched only `os.name`. But `canonical_relpath`
calls `os.path.normcase`, and `os.path` is bound to `posixpath` off Windows, where `normcase`
is identity — so the folding never happened and the assertion failed. The failure was raised
*while* `os.name == "nt"`, so pytest's own reporter hit `Path(os.getcwd())`, built a
`WindowsPath`, and took down the whole session with an `INTERNALERROR` before it could report
anything. The test now patches `normcase` to `ntpath.normcase`, so it exercises the real intent
on any platform. §7.4 can be closed.

### 9c. Do not spend time on the other 58 failures

Spot-checked and traced; none look release-blocking.

- **~24 connect/MCP tests** fail with `mcp post-write verify failed` / `bad_command` purely
  because `scubiee-mcp-bridge` is not on `PATH` in an editable venv. Traced one end to end and
  the signature matches across the group. Your Windows run used `uv tool install`, which puts
  the shims on `PATH`. *(Not confirmed by a full re-run with `.venv/bin` on `PATH`.)*
- **2 `test_accel_cpu_fallback`** assert the profile drops to `cpu`, but Apple Silicon
  deliberately keeps MLX — `[accel] probe timed out — Apple Silicon keeps MLX Metal GPU`. The
  0.3.29 `accel.py` diff only touches the cache-root functions, so this is not a regression.
- **1 `test_accel_pip_drain`** needs `pip`, which a uv-created venv does not ship.
- **1 `test_watchdog`** is the Windows-only spawn-flags test §4 predicts for Darwin.
- **`venture_stack` t3/t4, `trace_lab`, `setup_progress`** are the stale project id, the
  untracked eval harness, and the duplicate `✓ Runtime installed` already listed in §7.3.

### 9d. Cosmetic: spurious `matmul` warnings on every Mac search

`scubiee map` prints three warnings from `conductor/dense_index.py:50`:

```
RuntimeWarning: divide by zero encountered in matmul
RuntimeWarning: overflow encountered in matmul
RuntimeWarning: invalid value encountered in matmul
```

Not data corruption. The stored matrix is clean — 0 NaN and 0 inf across all 5710 rows, max
abs 0.27 — and numpy 2.2.6 on Apple's `accelerate` BLAS emits all three on freshly generated,
finite, normalized data while returning a finite result. Accelerate sets FP exception flags on
masked SIMD lanes.

Left alone deliberately, since it is a hot retrieval path. The fix, if you want the CLI quiet,
is the `np.errstate(divide="ignore", over="ignore", invalid="ignore")` wrap already used in
`turbo_quant.dequantize`.

### 9e. Suite hygiene notes for Mac

- The CLI combination suite is **destructive**: it de-enrolls the repo and its `disconnect`
  scenario strips the `scubiee` entry from `.cursor/mcp.json`. Follow it with `scubiee init .`
  and `scubiee connect --cursor`. The model cache survives.
- §6's contamination warning holds, plus the launchd agent above. `pkill` alone is not enough
  on macOS.
- The `conftest.py` guards did their job — `~/.scubiee`, the enrollment, and the weights all
  survived three full-suite runs.

---

## 10. Clean-slate CLI pass on Mac — deleted the venv and rebuilt

Deleted the 576 MB venv outright, built a fresh 3.10 one, installed 79 packages from source,
and drove the real commands with `.venv/bin` on `PATH` so the MCP shims resolve. End state is
healthy: `enrolled: true`, `warm_state: ready`, `index_usable: true`, `0.3.29`, and `map`
returning real vectors (rank 1 `install_health.py::faiss_import_ok`, score 29.63).

Passing: `gate`, `map`, `pack --mode lean`, `expand --node`, `search`, `status`, `list`,
`init` (32.7s, 5710 chunks), `connect --cursor` (pre-existing `figma` preserved),
`pause`→`activate`, `engine ensure`, idle self-retire, both `wipe` confirm gates (exit 2 with
a `--confirm` hint), and the MCP bridge handshake with all 8 tools.

### 10a. The MCP bridge reports the `mcp` SDK version as its own

`initialize` returns `serverInfo` = **`scubiee 1.30.0`**. 1.30.0 is the installed `mcp`
package; scubiee is 0.3.29. So the IDE's MCP panel shows a version that does not exist.

Worth fixing above its cosmetic weight: this project keeps losing time to "which version is
actually live" — 0.3.28 reached PyPI with an inert fix, and §8 says both of that day's fixes
looked verified. The one surface a user checks in the IDE currently cannot answer it. The
`Server(...)` construction needs an explicit `version`.

```
$ printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize",...}' | scubiee-mcp-bridge
initialize ->  scubiee 1.30.0        # expected 0.3.29
```

### 10b. `setup` says "Downloading model…" while downloading nothing

First `setup` in the fresh venv took **3m42s**, sitting on `Preparing MLX FP16 CodeRank
weights` → `Downloading model…` (58–63%) for over two minutes. Nothing was downloaded:
`~/.cache/fastembed` grew 795 MB → 796 MB, and `~/.scubiee/mlx/CodeRankEmbed` kept its
Sep 8 timestamps. It is re-verifying ~800 MB of existing weights. The 100% line then says
`Ready (reused mlx runtime + model cache)`, contradicting the label the user just watched.

A second `setup` is **0.97s** and jumps to `Using saved hardware profile`, so the cost is
one-time per venv — but on a fresh machine it is indistinguishable from the real 900 MB
download, which is exactly the state §2b makes people paranoid about.

### 10c. The logon supervisor is not live in-session on macOS

`setup` prints `Registering logon supervisor` at 94% and writes
`~/Library/LaunchAgents/com.contextengine.supervisor.plist`, but never `launchctl bootstrap`s
it. After a `launchctl bootout` it stays unloaded despite `setup` reporting success:

```bash
ls -la ~/Library/LaunchAgents/com.contextengine.supervisor.plist   # present, freshly written
launchctl list | grep contextengine                                # nothing
```

So the supervisor would not return until next login. Had to bootstrap it by hand. Note this
agent's `KeepAlive` also respawns the supervisor within seconds, which is what fakes the
"restart" §4 warns about — `pkill` alone is not enough on macOS, you need the bootout.

### 10d. Minor

- `scubiee --version` prints `[scubiee] Engine stopped …` to **stderr**. stdout is clean
  (`scubiee 0.3.29`), so piping and scripting are unaffected. `--help` does not print it.
- `doctor` exits 1 on a first-run repo where no engine has ever bound (`binding.ok: false`,
  `lock_pid: null`) and prints the exact repair, `scubiee engine ensure <repo>`. It passes
  afterwards, including once the engine idle-retires again, so it self-heals.
- Only **one** `pipeline engine watchdog` process here, not the 8-way accumulation §7.1 saw
  on Windows. The watchdog leak does not reproduce on Mac.
- `timeout(1)` does not exist on macOS — worth remembering for any harness copied from the
  Windows side.
