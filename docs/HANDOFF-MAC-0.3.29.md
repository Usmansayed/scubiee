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
