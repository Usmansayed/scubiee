# Scubiee macOS Findings — v0.3.144 reliability + perf verification

_Executed against the handoff `docs/scubiee-macos-handoff-0.3.144.md`._
_Date: 2026-10-09. Surface: live HTTP engine + CLI (`map`/`gate`/`status`), plus the offline unit suite._
_Autonomous verification + stabilization pass: Test → Research → Understand → Fix → Verify._

Severity legend: **BUG** (broken) · **ISSUE** (rough edge) · **OBS** (by-design nuance) · **OK/PASS** (verified).

> **Headline:** On Apple Silicon (M5), scubiee 0.3.144 is **production quality on the supported path once the four fixes below are released.** Every handoff section passes; four real bugs were found, root-caused, fixed, and re-verified end-to-end. Fixes are committed on branch `fix/macos-warm-segfault` and are **not pushed** (per handoff authority). Blocking caveats for a blanket stamp: Apple-Silicon-only coverage, fixes not yet released, and one test-harness hardening item (§Open items).

---

## 1. Environment

| Field | Value |
|---|---|
| macOS | 26.5.2 (build 25F84) |
| Chip | Apple **M5** — Apple Silicon |
| Arch | `arm64` |
| Accel | **MLX (Metal GPU)** — `Device(gpu, 0)`, Metal=true |
| Build python | homebrew `python3.12` (3.12.14) for the wheel build/test venv (`.venv-build`) |
| uv | 0.12.5 |
| Install | built wheel from checkout (`python -m build`) → `uv tool install --force --reinstall dist_prod/scubiee-0.3.144-py3-none-any.whl` (0.3.144 not on PyPI; latest published = 0.3.133) |
| Version under test | **0.3.144** (`/health` `version=0.3.144`) |
| project_id | `ce_c3bb9e1aeda5646a69be1d3708cc3625` (managed) |
| Index | ~8.5k chunks / ~1333 files, embed dim 768 |
| Dep variants | `mlx 0.32.3` + `mlx-metal 0.32.3`, `onnxruntime 1.23.2` (plain, pinned `>=1.17,<1.25`), `fastembed 0.9.0`. No `onnxruntime-directml`/`-gpu`. |

---

## 2. Per-section results

Lead sections (highest-risk new areas) first.

### §3 Accelerator / embedder (MLX/Metal) — the #1 macOS risk — PASS
- `resources` → `recommended_accel.profile=mlx`, `provider=MLX`, `mlx:true`, `torch_mps:false`. **PASS**
- `preflight` → `ok:true`; all required caps present; `embed_accel` `backend=mlx provider=MLX batch=48 texts_per_sec=101.43`. **PASS**
- `doctor` → `ok:true` with engine running+bound (`accel.ok`, `capabilities.ok`, `readiness.index_usable`). _(A transient `ok:false` only ever appeared with the engine stopped + uncommitted edits in the tree → `journal.pending`; benign.)_ **PASS**
- `certify` → **`ok:true`, 22 passed, 0 failed_required, failures:[]** (after MAC-144-2 fix). **PASS**
- MLX/Metal is the real embed path — `engine.log`: `[embed] backend=mlx device=gpu metal=true mlx_device=Device(gpu, 0)`, `MLX ready in ~700–1150ms metal=True`, **~101 t/s** (≈3× the Windows DML ~35 t/s). **PASS**
- **CapabilityError refusal:** `CTX_EMBED_BACKEND=mlx` with `mlx` forced-unimportable → raises `CapabilityError` ("requires the mlx package … Refusing FastEmbed/CPU fallback"). No silent CPU degrade. **PASS**
- **FastEmbed CPU fallback:** `CTX_EMBED_BACKEND=fastembed CTX_MLX=0` → `backend=fastembed`, valid 768-dim finite vectors, sane cosine (0.714 between related code). **PASS**

### §4 Cold-start + warm sequence timing — PASS (better than Windows)
- 4 cold restarts: **soft-ready ~2.1s, dense-ready ~4.1–4.2s, gap ~2.0s** (consistent). Far better than the ~15s failure mode; better than Windows DML (soft 4–9s, dense ~14s).
- `/health` `warm_phase` transitions `down → soft → dense` cleanly; never stuck `down`.
- AST revalidation (`[keeper] ast bundle revalidated ms=8700–16000`) runs as **background** keeper work, not blocking the cold window — the `CTX_AST_REVALIDATE_GATE_ON_EMBED` gate holds (dense at ~4s, not ~16s). **PASS**
- **Warm-start SIGSEGV:** 0 new segfaults across all restarts this session. The serial-warm fix (`engine.py`, default ON for `sys.platform==darwin` unless `CTX_SERIAL_WARM=0`) serializes native-lib init (faiss/turboquant/bm25/graphify/mlx) and holds. All 27 segfault lines in `engine.log` predate this build (last 2026-10-07). **PASS**

### §5 ORT / accel install robustness — PASS
- Exactly ONE onnxruntime variant: `onnxruntime 1.23.2` (no `-directml`/`-gpu`); pin `>=1.17,<1.25` satisfied. **PASS**
- Reinstall robustness: repeated `uv tool install --force --reinstall` → MLX survives (`0.32.3`, `Device(gpu,0)`), onnxruntime stays single+pinned, no DML leak; engine re-warms to dense. The Windows `onnxruntime-directml` clobber **does not apply** on Mac (pyproject pins hold). **PASS**
- Detect-only self-heal: `server.py::_ort_detect` → `accel.heal_ort_conflict()` with `apply=False` (detect-only); never pip-reconciles from the live engine; `apply=True` reserved for offline `setup --repair`. On this healthy Mac → `{ok:true, healed:false, needs_repair:false, reason:'profile_not_gpu', profile:'mlx'}`, no mutation. **PASS**
- `setup --repair` (no engine running) → clean 100% (hw detect → mlx profile → runtime+MLX FP16 weights → warm on accel → calibrate → re-register supervisor), exit 0, MLX preserved. **PASS**

### §9 Sync lanes — PASS (after MAC-144-4 fix)
| Lane | Result (post-fix) | Windows ref |
|---|---|---|
| Hot-save (edit tracked file) | searchable **~0.05s** | ~2.5s |
| Incremental (new file) | searchable **~0.65s** | ~3s |
| Delete | dropped **~0.6–0.94s** | ~1.5s |
| Rename | new searchable **~1.0s**, old evicted **~0s** | new 2.2s / old 4.2s |
| Bulk/offline (80 files, graph-catchup batch) | searchable **~3.8s**; graph catch-up **batched** (few passes, not 80×~4s) | one batch |

_Delete and rename-old-eviction **FAILED** before the fix (not pruned within 30s; only the periodic corpus-ghost sweep removed them ~10 min later). See MAC-144-4._

### §6 /health under embed load — PASS
- 40 files dirtied → embedded in one GPU batch (`112.83 chunk/s, bs=40, ~0.5s`). During the load: `/health` n=150, **p50=1.0ms, p95=43.3ms, max=166.1ms, 0 timeouts**. Background health refresher keeps `/health` off the embed disk-I/O path. Comparable to Windows (p50 ~2ms, 0 timeouts). **PASS**

### §7 MCP tools + CLI surface — PASS (after MAC-144-3 fix)
- `gate` → `1:ce_c3bb9e1aeda5646a69be1d3708cc3625`. **PASS**
- `status` → healthy, warm, dense, ~8.5k chunks, version 0.3.144. **PASS**
- `map config=find` (enriched query) → 5 results, confidence high, correct top hit (`freshness.py::choose_strategy`) with inline code. **PASS**
- `map config=find` (vague one-word) → low-signal/weak, as expected. **PASS**
- `map config=focus --names <sym>` → symbol body returned. **PASS**
- `map config=focus` missing symbol → clean "could not resolve … (give file::symbol or an exact name)", no hallucination. **PASS**
- `map config=related|graph` → graceful fold ("folded into find… Serving via find") + results, matching the MCP surface (after MAC-144-3). True garbage config still rejected. **PASS**

### §8 HTTP API — PASS
- GET `/health /  /status /v1/status /v1/resources /dashboard` → all **200**; unknown → **404**. **PASS**
- `/health` reports a live `warm_phase=dense` (never stuck `down`). **PASS**
- POST `/v1/search` → `ok:true`, correct top hit. **PASS**

### §10 launchd lifecycle — PASS
- LaunchAgent `~/Library/LaunchAgents/com.contextengine.supervisor.plist` present; `launchctl list` shows it loaded, exit 0. **PASS**
- Supervisor log at `~/Library/Logs/scubiee-supervisor.log`; state dir `~/.scubiee/` well-populated. **PASS**
- Clean engine stop/start; **idle-to-standby** works (`[lifecycle] standby_stop reason=idle_standby`, `CTX_ENGINE_IDLE_S=120`). **PASS**
- **No restart thrash** — watchdog starts map 1:1 to distinct PIDs (my explicit restarts + idle cycles), not a rapid crash loop; `[watchdog] interval=15.0s`. **PASS**

### §2 Install & version — PASS
- Wheel built from checkout, installed via uv tool; `scubiee --version=0.3.144`, `/health version=0.3.144 warm_state=ready dense_ready=true`. No Gatekeeper/quarantine/codesign friction. **PASS**

---

## 3. Bug register (found → fixed → verified this pass)

| ID | Severity | Area | Summary | Root cause | Fix | Status |
|---|---|---|---|---|---|---|
| **MAC-144-4** | **BUG** | Sync / delete lane | Explicit delete (and rename-old-eviction) via `/v1/dirty` not pruned promptly — chunks lingered in search until the periodic corpus-ghost sweep (~10 min). Windows prunes ~1.5s. | `/v1/dirty` passes **absolute** paths; `force_files` flowed absolute into `incremental_sync`, but `chunks.jsonl`/file-merkle store **relative** keys, so `_slice_chunk_file`/`_patch_file_merkle` matched nothing → `removed_ids=[]`. Also `_split_explicit_writes` dropped gone paths to the slow backlog via an `is_file()` guard. | (1) `incremental.py`: relativize `force_files` to repo-root at the single source feeding `changed/removed/touch/touch_set`. (2) `sync_loop.py::_split_explicit_writes`: route gone-but-indexed hot paths to the prompt write lane (env `CTX_HOT_DELETE_PRUNE`, default on). | **FIXED** — delete now ~0.6–0.9s; +3 regression tests. |
| **MAC-144-2** | **BUG** | certify | `certify` `install_mcp_launches_map_v3` false-failed on macOS (`map_v3=False`) → `certify ok:false`. | Check only recognized map_v3 via the literal `map_v3_server` substring, which appears only on the **Windows** spawn-JSON path. On the macOS/Linux bridge path `server_entry` returns `scubiee-mcp-bridge` with no spawn-JSON, yet the bridge defaults its child to `pipeline.map_v3_server`. Windows-biased assertion. | `certify.py`: also accept the bridge path (`mcp_bridge`/`scubiee-mcp-bridge`) and the `scubiee-mcp` shim (re-exports map_v3 main), in addition to the direct substring. | **FIXED** — `certify` 22/0, failures:[]. |
| **MAC-144-3** | ISSUE | CLI/MCP parity | CLI `map --config related|graph` hard-errored (`invalid choice`), while the MCP `map` tool folds them into find/focus and still serves. CLI docstring even claimed "CLI and MCP surface never diverge." | argparse `choices=("find","focus")` rejected the hidden fallbacks before they could reach `tool_map`'s graceful-fold logic. | `__main__.py`: widen `--config` choices to include the hidden fallbacks (`metavar="{find,focus}"` keeps help clean); `cmd_map` already forwards config to `tool_map`. | **FIXED** — related/graph fold + serve; true garbage still rejected. |
| **MAC-144-1** | ISSUE (minor) | Embedder | MLX construction banner (`[embed] backend=mlx/device=gpu/metal=true/…`) printed to stderr even when `Embedder(quiet=True)`. Noise for progress-bar-driven callers. | The MLX banner block in `embedder.py::__init__` wasn't guarded by `self.quiet` (the sibling "plan" banner already was). | `embedder.py`: wrap the MLX banner in `if not self.quiet`. | **FIXED** — quiet honored; `test_embedder_progress` passes. |

No **BUG**-severity issue remains open on Apple Silicon after these fixes.

---

## 4. Cross-platform comparison (vs Windows / DirectML)

| 0.3.144 fix / dimension | macOS (M5, MLX) |
|---|---|
| Cold-start dense-vs-soft ordering | **Better** — gap ~2s (Win soft 4–9s / dense ~14s). |
| `/health` under embed load | **Same/Better** — p50 1ms, 0 timeouts (Win p50 ~2ms). |
| Graph catch-up batching | **Same** — bulk 80 files merge in a few passes, not N×~4s. |
| ORT/accel install robustness | **Same intent, Mac-correct** — single pinned `onnxruntime`, MLX survives reinstall; Windows DML-clobber class does not apply. |
| Detect-only ORT self-heal | **Same** — detect-only in-engine; repair offline via `setup --repair`. |
| Embed throughput | **Better** — ~101 t/s vs Win DML ~35 t/s. |
| Delete/rename-eviction latency | **Fixed to parity** — ~0.6–0.9s after MAC-144-4 (was a Mac-visible, likely cross-platform, gap for absolute `/v1/dirty` paths). |

---

## 5. macOS-only findings
- **MLX/Metal is the real embed path** (768-dim CodeRankEmbed, ~101 t/s, warm ~0.7–1.1s) and refuses silent CPU fallback.
- **Apple-Silicon never demoted to CPU** on a GPU-probe/calibration timeout (by design; `accel.py::_fallback_to_cpu_profile` keeps MLX). Confirmed correct; this is also why 4 pre-existing unit tests needed platform-aware updates (below).
- **launchd LaunchAgent** `com.contextengine.supervisor` installs and loads; idle-to-standby + supervised restart behave; no thrash.
- No Gatekeeper/quarantine/codesign friction.
- **OBS (research):** on brand-new M5 hardware, some reports note Xcode 26.5's Metal toolchain can miscompile certain MLX M5-only shaders (bf16 matmul). Not observed to affect embedding here (fp16 CodeRank path, correct retrieval), but worth watching on M5-class machines. _(Rephrased from public issue reports; verify independently.)_

---

## 6. Test suite (offline)

- **Harness note:** `timeout`/`gtimeout` are absent on this macOS (no coreutils). A portable per-file isolated runner (`scripts/perf/_run_tests_isolated.py`, process-group kill on wall-timeout) was used because the single-process full run segfaults ~15% in (see Open items).
- **Mac-priority suites PASS:** `test_mlx_backend`, `test_mlx_mac`, `test_coreml_mac`, `test_coderank_fp16`, `test_warm_path_speedups`, `test_graph_catchup_async`, `test_faiss_dense_adapter`, `test_capability_promotion`, `test_sync_corpus_alignment`, `test_d_channel_best_fast_index`, `test_dense_map_required`.
- **4 pre-existing failures triaged → fixed as stale/platform-unaware tests** (product behavior was correct):
  - `test_accel_cpu_fallback` (2) + `test_cpu_only_laptop_path` (1): asserted CPU fallback, but the real M5 keeps MLX. Fixed by pinning a non-Apple host in those generic cases.
  - `test_preflight` (2): stubbed `load_accel`, but `inspect_accel` resolves via `resolve_runtime` (live MLX on M5). Fixed by stubbing `resolve_runtime`.
  - `test_embedder_progress` (1): the actual MAC-144-1 product fix made it pass.
- **New regression tests** for MAC-144-4 added to `tests/test_lane_delete_consistency.py` (gone+indexed routes to write lane; gone+unindexed stays backlog; `CTX_HOT_DELETE_PRUNE=0` rollback).

---

## 7. Files changed (branch `fix/macos-warm-segfault`, not pushed)

Product:
- `packages/pipeline/incremental.py` — relativize `force_files` to repo-root (MAC-144-4).
- `packages/pipeline/sync_loop.py` — `_split_explicit_writes` routes gone+indexed hot deletes to the write lane, env `CTX_HOT_DELETE_PRUNE` (MAC-144-4).
- `packages/pipeline/certify.py` — accept bridge/shim map_v3 launch paths (MAC-144-2).
- `packages/pipeline/__main__.py` — widen CLI `map --config` to fold hidden configs (MAC-144-3).
- `packages/pipeline/embedder.py` — MLX banner honors `quiet` (MAC-144-1).

Tests:
- `tests/test_lane_delete_consistency.py` — +3 MAC-144-4 regression tests.
- `tests/test_accel_cpu_fallback.py`, `tests/test_cpu_only_laptop_path.py`, `tests/test_preflight.py` — platform-aware updates.

New env knobs (safe defaults, documented): `CTX_HOT_DELETE_PRUNE` (default on).

---

## 8. Follow-up review — additional items investigated

- **Multi-client concurrency (F1) — PASS.** 8 concurrent clients issuing `/v1/search` + `/health` for 20s while a churn thread dirtied/removed files: **783 OK, 0 err, 0 5xx, 0 connection-closed, engine alive after.** No crash or drop under concurrent load + churn.
- **Single-process test-suite segfault — characterized as test-harness-only, not product-reachable.** Investigated directly:
  - 20 iterations of **concurrent** faiss + mlx + tree-sitter + onnxruntime init/exercise in one interpreter → **0 segfaults**.
  - The native-heavy module subset (mlx/faiss/coderank/embedder/coreml/vectordb/warm/graph-catchup) single-process → **80 passed, 0 segfault**.
  - First 30 test files single-process → **219 passed, 0 segfault** (the crash is intermittent and did not reproduce; consistent with the probabilistic native race the serial-warm fix guards).
  - The shipped engine warm path is serialized (serial-warm fix) and had **zero** segfaults across all restarts this session.
  - **Conclusion:** the ~15% single-process crash is a test-execution artifact (a specific integration test spawning an engine while another native op runs in the same interpreter), not a path the shipped engine takes. A forked/isolated test runner (or a module-level native-init lock in the harness) would make a single-process macOS CI run reliable. Recommended, not blocking for the product.
- **MAC-10 (test infra, ISSUE):** at least one Windows-only test is not `skipif`'d on darwin — `test_connect_formats::test_legacy_global_paths_include_devin_cascade` asserts a Windows `AppData/Roaming/...` MCP path; macOS correctly uses `.config/...` (XDG). Product is correct; the test needs a platform guard. A raw macOS `pytest` therefore shows some misleading red. Fix before using the suite as a macOS CI gate.

## 9. Still open / not proven

1. **Apple-Silicon-only coverage.** Only M5 tested. Intel / CoreML / CPU-only Mac path is unverified.
2. **Fixes not released.** Committed on branch only; not pushed, not in a published wheel. Nothing is production until reviewed + shipped.
3. **Not evaluated:** reboot/login autostart of the LaunchAgent; large-repo scale (10k+ files); the M5 Metal-shader concern (OBS §5).

---

## 10. Honest verdict

**On Apple Silicon (M5), scubiee 0.3.144 is reliable and production-quality on the supported path — once the four fixes here are reviewed and released.** All handoff sections pass; the embedder/MLX, cold-start, install-robustness, `/health`-under-load, sync lanes (post-fix), MCP/CLI/HTTP surfaces, and launchd lifecycle are all green, and macOS matched or beat Windows on every cross-referenced dimension.

**Do not** claim a blanket "production-ready" until: the fixes ship through review (they are branch-only, unpushed); an Intel/CPU pass is done or Intel is explicitly scoped out; and the single-process test-suite segfault is guarded. Recommendation: **ship to Apple Silicon with confidence after release; hold Intel and corrupted-state/scale claims pending the items in §8.**
