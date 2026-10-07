# macOS warm-start SIGSEGV — investigation, root cause, and fix

**Platform:** macOS 26.5.2, Apple Silicon (arm64), MLX/Metal.
**Version under test:** scubiee 0.3.143.
**Status:** **FIXED** — 0 crashes in 120 cold restarts after the fix (baseline ~5-17%).

---

## 1. Symptom

On a clean install (`wipe --all` → build → `uv tool install` → `setup` → `init` → `connect --kiro`), the engine intermittently crashed on cold start / warm-up with a macOS "Python quit unexpectedly" dialog:

```
Exception Type:  EXC_BAD_ACCESS (SIGSEGV)
Exception Subtype: KERN_INVALID_ADDRESS at 0x3f9877b7cc15f423
Triggered by Thread: 6
Termination Reason: Namespace SIGNAL, Code 11, Segmentation fault
```

The watchdog auto-restarts the engine, so it self-heals — but the crash is user-visible (crash dialog) and a crashed start delays `dense_ready` from ~2.5s to 20-80s (watchdog detect + retry). Observed rate on the shipped build: **~5-17% of cold starts** (highly variable).

## 2. What it is NOT

- **Not sleep/power related.** Reproduced under `caffeinate -dimsu` (machine prevented from sleeping) at the same rate. The crash report shows the process awake the whole time (`Time Awake Since Boot: 990s`).
- **Not corrupted/partial index state.** Reproduced on a freshly built, clean index.
- **Not a single bug.** Crash top-frames shifted between runs across *different* native subsystems (see §4).

## 3. Reproduction harness

`caffeinate -dimsu` + a loop of: `scubiee engine stop` → `scubiee engine start --wait 0` → poll `/health` for `dense_ready` → diff the `Fatal Python error: Segmentation fault` count in `~/.scubiee/engine.log`. Baseline showed 2-5 crashes per 30 restarts; target was 0 across ≥60.

## 4. Root cause — concurrent native-library initialization during warm

`load_engine` / `_warm_registered` deliberately parallelize the native-heavy warm builders for speed:

```python
with ThreadPoolExecutor(max_workers=3) as pool:
    f_graph = pool.submit(_build_graph)   # graphify / networkx (native)
    f_bm25  = pool.submit(_build_bm25)    # conductor bm25 (native)
    f_cards = pool.submit(_build_cards)
    dense = FaissDenseAdapter(...)        # faiss + turbo_quant numpy-LAPACK (native, main thread)
```
Meanwhile the **MLX/Metal embedder** builds on another thread (`get_embedder`/`_eager_prewarm`), and `/health` handler threads run a **manifest checksum** (`index_is_usable → validate_manifest → _checksum`).

On Apple Silicon these native libraries + Metal are **not safe to initialize/run concurrently across threads**:
- MLX is not thread-safe for concurrent build/eval ([ml-explore/mlx #1448](https://github.com/ml-explore/mlx/discussions/1448)); MLX ≥0.31 streams are thread-local ([mlx-lm #1181](https://github.com/ml-explore/mlx-lm/issues/1181)); and auto-fused compiled kernels crash on lazy/mmap weights with a null MTLBuffer ([ml-explore/mlx #3329](https://github.com/ml-explore/mlx/issues/3329)).
- The parallel builders + `/health` checksum touch faiss/turboquant (numpy-LAPACK), bm25, graphify, and MLX allocators simultaneously.

The result is a wild-pointer `SIGSEGV` whose **top frame is whichever native lib lost the race** that particular start. Captured signatures across runs:

| Crash | Racing native frames |
|---|---|
| A | `mlx_mac.py` MLX build vs `ce_service._eager_prewarm` MLX inference |
| B | `searcher → turbo_quant.to_float32 → numpy.linalg.qr` vs `artifact_guard._checksum` (`/health → validate_manifest`) |
| C | `conductor.bm25_index` + `graphify/serve` builders |

(_Content rephrased from the upstream issues for licensing compliance._)

## 5. The fix

Three layered changes; the first is the decisive one.

### (1) Serialize the warm build on macOS — `packages/pipeline/engine.py`
Build the native components (`FaissDenseAdapter`, graph, bm25, cards) **sequentially on one thread** on Darwin instead of via the `ThreadPoolExecutor`, so only one native library initializes at a time. Other platforms keep the parallel fast path. Env override `CTX_SERIAL_WARM` (`1`/`0`).

### (2) MLX hardening — `packages/pipeline/mlx_mac.py`
- `mx.disable_compile()` at `CodeRankMLX.__init__` (guard `CTX_MLX_DISABLE_COMPILE`) — removes the #3329 compiled-kernel/null-MTLBuffer variant.
- Hold `_MLX_EMBED_LOCK` across model **construction** (mmap `mx.array` + `mx.eval`), the same lock inference already uses, so build and inference are mutually exclusive.

### (3) Quiet `/health` during warm — `packages/pipeline/project_id.py` + `ce_service.py`
`index_is_usable(..., validate=False)` skips the native `validate_manifest` checksum while `self.warming` is true, so `/health` can't race the warm thread's faiss build. The warm validates before publishing anyway.

## 6. Validation

All under `caffeinate -dimsu` on Apple Silicon, scubiee 0.3.143:

| Build | Restarts | Crashes | Rate | Warm p50 |
|---|---|---|---|---|
| shipped (no fix) | 10-30 | 2-5 | ~5-17% | ~2.4s |
| MLX-only fixes (disable_compile+lock) | 60 | 1-4 | ~2-13% (variable) | ~2.4s |
| single-MLX-owner-thread redesign | 30 | 5 | ~17% (worse) | regressed |
| **full fix (serial warm + MLX + /health)** | **120** | **0** | **0%** | **~2.5-3.3s** |

- **0 segfaults across 120 cold restarts**, 0 never-warmed.
- Warm-up timing preserved (serial build adds negligible cost — the builders are mostly disk/CPU-bound; p50 2.5-3.3s vs ~2.4s baseline).
- Offline unit tests: **38 passed** (`test_warm_path_speedups`, `test_sync_corpus_alignment`, `test_graph_catchup_async`, `test_capability_promotion`, `test_d_channel_best_fast_index`).
- Functional: engine warms to `dense_ready`, `/v1/locate` serves correct hits.

## 7. Failed approaches (so they are not repeated)

| Attempt | Result | Why it failed |
|---|---|---|
| Lock around MLX **construction** only | ~still crashing | race is build-vs-**inference**, not build-vs-build |
| Confine MLX build to the single embed worker thread | ~17%, broke warm | MLX 0.31 streams are thread-local — model built on worker couldn't be driven elsewhere; also unmasked the faiss race |
| `disable_compile` + construction lock (MLX only) | ~2-13% | closes the MLX door but faiss/bm25/graphify still race |
| `/health` checksum skip (alone/with MLX) | ~10% | closes the artifact-guard door but the parallel builders still race each other |
| **Serialize the whole warm (+ above)** | **0/120** | removes cross-library concurrency entirely — the actual root cause |

## 8. Tradeoff & tuning

Serial warm trades a little warm-up parallelism for crash-free starts. In practice warm stayed ~2.5-3.3s p50 (the builders are I/O/CPU-bound, not GPU-bound, so serializing them is cheap). If a specific host wants the old parallel behavior, set `CTX_SERIAL_WARM=0`; to force serial on non-Darwin, `CTX_SERIAL_WARM=1`.

## 9. Files changed
- `packages/pipeline/engine.py` — serial warm on Darwin (`CTX_SERIAL_WARM`).
- `packages/pipeline/mlx_mac.py` — `mx.disable_compile()` + `_MLX_EMBED_LOCK` around construction.
- `packages/pipeline/project_id.py` — `index_is_usable(validate=...)`.
- `packages/pipeline/ce_service.py` — skip manifest checksum in `/health` during warm.
