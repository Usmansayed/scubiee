# Issue log — how we worked and what we fixed

Chronological enough to avoid repeating mistakes. Files are repo-relative.

---

## Reliability (0.2.5–0.2.6, Windows worktree)

### Search query treated as a repo path / mkdir pollution

**Symptom:** `ctx search . "test query"` created folders; queries became project roots.  
**Cause:** CLI positional mix-up; `resolve_project` mkdir’d non-dirs.  
**Fix:** Directory-first heuristic in `interpret_search_cli`; `write_id_file` requires existing dir; HTTP client ignores non-directory `path`.  
**Files:** `packages/pipeline/__main__.py`, `project_id.py`, `client.py`.

### MCP status vs engine health

**Symptom:** Status said healthy while HTTP unreachable (or the reverse).  
**Cause:** `/v1/status` timeout vs `/health`.  
**Fix:** Health-first status; `ensure_daemon` on MCP use.  
**Files:** `mcp_locate.py`, `daemon.py`.

### Live reindex / FAISS ids after incremental upsert

**Symptom:** Incremental upsert left search IDs wrong; new chunks missing until restart.  
**Fix:** Id mapping + publish generation after incremental (`incremental.py`, `searcher.py`, `engine.py`).

### Doctor exit 1 when only daemon unbound

**Symptom:** Index fine, doctor failed.  
**Fix:** `doctor.py` exit 0 if index OK.  
**Also:** `ctx init --fast` / `--roots`.

### Mac npm / PEP 668 / old PyPI

**Symptom:** `npm install -g scubiee` 404; pip on system Python blocked.  
**Fix:** npm script venv + git pip fallback (`npm/scripts/install-python.cjs`). **npm package still unpublished.**

---

## Mac CoreML GPU (0.2.6–0.2.8)

### Dynamic shapes / E5RT / `runtime shape ({1,6,12,0})`

**Symptom:** `ctx setup` died on CoreML.  
**Cause:** Variable `batch_size=len(batch)` + CodeRank ONNX dynamic axes; CoreML hates rotary/attention with zeros.  
**Approach:** `coreml_mac.py` — static `[batch, seq]`, pad embed batches to 20, `RequireStaticInputShapes=1`.  
**User:** refused `--profile cpu` as the product answer.

### Silent CPU fallback (`Unknown option: UseCPUAndGPU`)

**Symptom:** 0.2.7 printed Ready; calibration ~21 t/s CPU.  
**Cause:** ORT string options included C-API flags `UseCPUAndGPU`, `CreateMLProgram`. EP rejected → FastEmbed/ORT fell back to CPU.  
**Also:** `make_input_shape_fixed(..., shape)` with **undefined** `shape` (swallowed).  
**Fix (0.2.8):** valid options only (`MLComputeUnits`, `ModelFormat`, `RequireStaticInputShapes`, `EnableOnSubgraphs`); `shape = [batch, seq]`.  
**Lesson:** GPU-only must **fail loudly**, not succeed on CPU.

### Strategy change: MLX is the Mac GPU product

CoreML remained too brittle. Mac agent shipped **MLX** CodeRank on Metal (`mlx_mac.py`): convert ONNX weights, FP16 default, `require_mlx_gpu()`, no CPU fallback on that backend. Benches on M5: ~30 chunks/s vs ~13 CPU.

---

## Mac MCP + daemon (0.2.11–0.2.13)

### `ModuleNotFoundError: pipeline` in Cursor MCP

**Cause:** `mcp_install.interpreter()` used `Path(sys.executable).resolve()`. macOS venv python **symlinks into Homebrew Cellar** → no venv site-packages.  
**Fix:** Prefer `CTX_PYTHON`, then `sys.prefix/bin/python`; **do not resolve away the shim**. Same in `__main__.py` MCP write.  
**Files:** `mcp_install.py`, `__main__.py`.  
**Verify:** `.cursor/mcp.json` command is `~/scubiee/bin/python`.

### Stale search after `ctx sync`

**Cause:** CLI ran **local** `incremental_sync`; daemon kept old in-memory engine (generation unchanged).  
**Fix:** `cmd_sync` prefers `/v1/sync`; local fallback then `/v1/publish` (`RuntimeManager.publish`, `EngineClient.publish`, `server.py`). `ce_service.sync()` publishes when refreshed.  
**Verify:** unique comment in a **`.py`** file → `ctx sync` → `ctx search TOKEN` rank 1, no restart. `.txt` will never index.

### MLX `There is no Stream(gpu, 0) in current thread`

**Cause:** MLX ≥0.31 streams are thread-local. Model on daemon main thread; embed/sync on worker.  
**Fix:** `mlx_thread_stream()` + lock; wrap `mx.eval`; `embedder._ensure_mlx` uses `threading.local()`.  
**Trap:** CLI sync on main thread can pass while **daemon `/v1/sync` fails**. Test both.

### `embed_one` skipped MLX

**Cause:** Only `coderank`/`fastembed` branches; MLX fell through to Ollama.  
**Fix:** Include `mlx` on batch/embed_one path in `embedder.py`.

### Agents mixed native Grep with MCP

**Cause:** Phase had no MCP grep/glob; host prompts say “use Grep.”  
**Fix:** Phase tools `grep` + `glob` (specific-only). Instructions: native locate **only if** `status()` unhealthy. Packaged short Cursor rule (0.2.13).  
**Do not** put the full trajectory table in the rule.

### Hard map/search/focus caps

**Was:** `_NAV_SOFT_CAP`, thrash_blocked, “map budget 4/4”.  
**Now:** `_record_locate_query` → `usage_hint` only. Hybrid CBM same. Focus already-shown advisory.

---

## Windows install + DML (0.2.14–0.2.17)

### Setup hung at 31% (pip PIPE deadlock)

**Symptom:** `ctx setup` bar stuck ~31%, never finished.  
**Cause:** `pip_install` used `Popen(stdout=PIPE)` and never drained stdout (Windows pipe deadlock).  
**Fix (0.2.14):** drain thread in `accel._run_pip_captured`.  
**Files:** `packages/pipeline/accel.py`, `tests/test_accel_pip_drain.py`.  
**PyPI:** https://pypi.org/project/scubiee/0.2.14/

### Permission error while FastEmbed pulled CPU ORT

**Symptom:** Setup died ~31% replacing onnxruntime while `ctx.exe` held site-packages. Leftover `~cubiee` dist-info noise. Editable `context_engine-0.1.0` shadowed PyPI.  
**Fix (0.2.15):** skip already-satisfied FastEmbed deps; FastEmbed `--no-deps`; clean leftover dist-info / old editable.  
**Lesson:** do not `pip install` ORT while the running `ctx` process has the wheel locked.

### DML crash: CPU ORT wheel, profile `dml`

**Symptom:** ~56% “GPU/CPU engine”; FastEmbed asked for `DmlExecutionProvider`; installed wheel was CPU (`AzureExecutionProvider` / `CPUExecutionProvider`). Leftover `onnxruntime/` folder after mixed uninstall → `ort.get_available_providers` `AttributeError` (`__file__` None).  
**Fix (0.2.16):** uninstall all of `onnxruntime` / `-gpu` / `-directml`, force-install the profile wheel; `_align_profile_to_ort` CPU-fallback only if EP still missing. Manual purge of leftover `site-packages/onnxruntime` then `onnxruntime-directml` on this machine.  
**Verified:** providers `DmlExecutionProvider`, `CPUExecutionProvider`; `ctx setup --repair` 100% Ready; `accel.json` profile `dml` device_id 1 (RX 6500M).  
**PyPI:** https://pypi.org/project/scubiee/0.2.16/

### `ctx init` `No module named 'resource'`

**Symptom:** Setup OK; `ctx init` failed immediately (`[resources] index gate skipped` then hard fail).  
**Cause:** `memory_budget.py` imported Unix-only stdlib `resource` at module level. Windows has no `resource`.  
**Fix (0.2.17):** RSS via `psutil` first; `resource` only as Unix fallback.  
**Verified:** `ctx init` on this worktree — 364 files, 2987 chunks, FastEmbed DML ~27 chunk/s, 100% Ready. `mlx_batch` in the log is bootstrap budget field names, not MLX backend.  
**Files:** `packages/pipeline/memory_budget.py`, `tests/test_memory_budget.py`.  
**PyPI:** https://pypi.org/project/scubiee/0.2.17/

### First PyPI 0.2.17 upload hung

Credential script quoting failed; twine waited for a password. Killed; retry uploaded 0.2.17 successfully.

---

## MCP locate honesty + recommendations (0.2.18, tree — not necessarily on PyPI yet)

### Grep only searched `.py` even when glob said otherwise

**Symptom:** `grep(pattern, glob="*.ts")` still walked `iter_py_files` (`.py` only). Default `max_hits=20` with no “more exist” flag → agents treated a miss as absence.  
**Fix:** `grep_scan` / `iter_glob_files` honor the requested glob; return `truncated` / `has_more`. Empty + `truncated=false` = absence **for that glob only**.  
**Files:** `packages/pipeline/capability.py`, `ce_service.py`, `mcp_locate.py`, `tests/test_grep_glob_scope.py`.

### Glob flattened `**` and truncated mid-walk

**Cause:** `**` replaced with `*`; walk stopped at `limit` then sorted → a real file later in the tree never appeared, and empty+truncated was possible.  
**Fix:** globstar matcher; collect all matches, sort, slice; `truncated` means more than `limit`. Known relative path without magic is an exact file check.

### Map treated as exhaustive; phase instructions were bans

**Was:** long STRICT NATIVE BAN / MANDATORY / “ONLY when specific” in MCP server instructions every turn. Cursor rule duplicated trajectory.  
**User:** recommend, let the agent decide; do not imply map miss = not in repo.  
**Fix:** short recommend card (`SERVER_INSTRUCTIONS_PHASE`). `map` payload `ranked_only` + `scope=indexed_chunks`. `focus` may set `truncated` / `language_unsupported` (outline is Python AST). Cursor rule later restored **STRICT native ban** (Grep/Glob/search forbidden; CE MCP only; unhealthy `status()` exception). MCP instructions still recommend *which* CE tool, not native locate.  
**Files:** `mcp_locate.py`, `templates/context-agent.mdc`, `.cursor/rules/context-agent.mdc`.  
**Tests:** `test_mcp_locate.py` (no STRICT BAN / MANDATORY), `test_grep_glob_scope.py`.

### Live reindex probe (this Windows session, CE MCP)

Wrote unique new file + edit on `memory_budget.py`, waited 5s. `grep`/`glob` saw tokens immediately (live disk). `map` rank 1 on both unique symbols. Keeper incremental ~5.2s, 10 chunks upserted. Probe files removed. Hammering `map`/`locate` while measuring can delay sync (`locate_streak`) — poll grep/search, not locate, for timing tests.

---

## Process mistakes (this Windows session)

- Merged feature branch into `main` **and checked this worktree out to `main`**. User wanted Mac commits **on `feat/production-certification` in this worktree**. Undo: this worktree back on the feature branch; `main` force-updated to Mac tip `e59fb8a` (no merge commit).
- Do not assume venv `~/.context-engine/venv` — user created **`~/scubiee`**.
- Session-info logs were written at 0.2.13/0.2.14 and **not updated** through 0.2.15–0.2.18 until this entry. Always append here when we ship a setup/MCP fix.

---

## Still open (see session-summary remaining)

npm publish, `needs_full` / `sync_status=syncing` vs keeper `ready` mismatch, leftover project stores, dump/replace operator UX, foreign-tree indexing, uninstall vs live daemon, README git pin still `v0.2.6` in one place, 0.2.18 not on PyPI until we upload.
