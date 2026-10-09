# Scubiee macOS v0.3.145 — connect→init reliability (deadlock + segfault fixes)

_Platform: macOS 26.5.2, Apple Silicon (M5, arm64), MLX/Metal. Build: scubiee 0.3.145._
_Flow under test: `scubiee connect` first, then `scubiee init` later ("connect-once, init-applies")._

The 0.3.145 "connect-once" model is: `connect` records a tool machine-wide
(`~/.scubiee/connected_tools.json`), and a later `init` applies rules + MCP config
for every connected tool while indexing the repo. On macOS this order was
**unreliable** — two independent bugs made `connect` → `init` hang or crash. Both
are now fixed and verified (8/8 clean inits on a throwaway 2-file repo, plus 5
offline regression tests).

---

## Bug A (BUG) — connect→init deadlock

**Symptom.** With a supervisor already running (started by `connect`), a later
`scubiee init .` hung for 2+ minutes with no indexing progress and had to be
killed. The engine log showed a loop of `[stop] reason=stop_daemon:idle_standby
by=engine supervisor` interleaved with `[stop] by=scubiee init
at=...quiesce_background_indexing`.

**Root cause.** `init` calls `quiesce_background_indexing` to stop the engine so
it can take the exclusive store write-lock (`store_lock.py`, 120s timeout). But
the supervisor's only start/stop gate — `engine_should_be_running()` — had no
awareness of an in-progress rebuild, so the supervisor kept **respawning** (and
idle-stopping) the engine every tick, racing `init` for the lock until it timed
out. `init` never set any flag telling the supervisor to stand down.

**Fix.** A bounded, self-expiring **store hold** (`engine_transition.json`
`store_hold_until`):
- `lifecycle_runtime.py`: `begin_store_hold()` / `clear_store_hold()` /
  `store_hold_active()`. `engine_should_be_running()` returns `False` while held
  (checked FIRST, before pause/desired_mode) → the watchdog gate is a complete
  no-op (neither start nor stop). `enter_standby()` is also guarded (returns
  `store_hold_skip_standby` instead of stopping the engine), as is the
  `run_supervisor` startup standby and the top of `watchdog_loop`.
- `repo_lifecycle.py::initialize_repo`: sets the hold right before
  `quiesce_background_indexing`, clears it in a `finally` after indexing (covers
  the success, sync-error, and exception exits). Skipped when
  `CTX_SCUBIEE_ROLE` is `engine`/`watchdog` (a daemon must not pin itself off).
- `__main__.py::cmd_init`: the post-index `ensure_daemon` handoff is now bounded
  (`wait_s`, default 20s, `CTX_INIT_HANDOFF_WAIT_S`) so a slow engine warm can't
  re-hang init after the index is already durable.

Self-expiring (default 180s window, `CTX_STORE_HOLD_S`) so a crashed `init` can
never leave the engine permanently refused — once the deadline lapses the hold
is ignored and the engine runs normally again.

**Verification.** Repeated `connect`→`init` on a 2-file repo: no hangs; init
returns in ~3–13s. Regression tests: store-hold gates `engine_should_be_running`,
self-expires, and makes `enter_standby` a no-op while held.

---

## Bug B (BUG) — `init` segfaults at "Writing index"

**Symptom.** On a clean first-ever `init`, ~1 in 3 runs crashed at the "Writing
index" (92%) phase. macOS crash reports showed `SIGTRAP` in `libsystem_malloc`
(`_xzm_xzone_malloc_freelist_outlined` → numpy `array_zeros`) and, in a variant,
a `gc_collect` SIGSEGV — i.e. **heap corruption** detected by the allocator
guard, not a plain null-deref.

**Root cause.** A full index embeds a batch on **MLX/Metal**, then does a heavy
**numpy-LAPACK / faiss** vector write in the SAME process (`store.upsert_vectors`
→ `turbo_quant` QR / `np.zeros`). MLX's Metal allocator leaves the process heap
in a state that intermittently trips the malloc guard at that next large
allocation. Proven by isolation: **FastEmbed→faiss indexed 4/4 clean; MLX→faiss
crashed ~1/3.** (Consistent with known MLX native-memory issues, e.g.
ml-explore/mlx #3329 and #1332 — content rephrased for licensing compliance.)

**Fix (`indexer.py` + `mlx_mac.py`) — MLX stays the index backend.** The crash is
fixed **on the MLX path**, not by swapping embedders. Before the faiss/
`turbo_quant` vector write, `mlx_mac.quiesce_mlx()` runs on the main thread under
the embed lock: `mx.synchronize()` (flush all in-flight GPU work) → `clear_cache()`
→ a momentary `set_cache_limit(0)` drain → a final `synchronize()`. This releases
MLX's transient Metal buffers back to the OS so the process heap is clean before
numpy-LAPACK / faiss runs, removing the native-allocator race.

> **Reverted — no FastEmbed swap.** An earlier revision defaulted the whole index
> build to FastEmbed/ONNX on Darwin whenever MLX would be used. That was rolled
> back: MLX is the chosen Apple-Silicon accelerator and the index build must stay
> on it. Splitting the embedder (FastEmbed index vectors vs MLX query vectors)
> reversed a deliberate architecture decision and is a silent correctness risk.
> `CTX_INDEX_EMBED_BACKEND` remains an **explicit opt-in escape hatch** (e.g.
> `=fastembed`/`=cpu`) but is OFF by default — the default on Apple Silicon is MLX.
> See `docs/scubiee-macos-handoff-mlx-not-fastembed.md`.

**Open on macOS (for the Mac agent to verify):** confirm that `quiesce_mlx()`
alone makes the MLX index build crash-free — run a clean first `init` ≥20× on
MLX (no FastEmbed swap) and expect 0 crashes at "Writing index". If it still
crashes, escalate the root cause to the owner before any backend workaround; do
not re-introduce the silent swap.

---

## Files changed

- `packages/pipeline/lifecycle_runtime.py` — store-hold flag + predicate;
  `engine_should_be_running` / `enter_standby` / `run_supervisor` guards.
- `packages/pipeline/watchdog.py` — watchdog loop no-ops at the top while held.
- `packages/pipeline/repo_lifecycle.py` — set/clear the hold around the index
  block in `initialize_repo`.
- `packages/pipeline/__main__.py` — bounded post-index `ensure_daemon` handoff.
- `packages/pipeline/indexer.py` — `quiesce_mlx()` before the vector write; index
  build stays on MLX (FastEmbed swap reverted; `CTX_INDEX_EMBED_BACKEND` is an
  opt-in escape hatch only).
- `packages/pipeline/mlx_mac.py` — `quiesce_mlx()` helper (synchronize + clear
  Metal cache under the embed lock).
- `tests/test_connect_then_init.py` — 5 regression tests (store-hold gating,
  self-expiry, enter_standby no-op, index-backend selection + override).

New env knobs (safe defaults): `CTX_STORE_HOLD_S` (180), `CTX_INIT_HANDOFF_WAIT_S`
(20), `CTX_INDEX_EMBED_BACKEND` (unset → MLX stays the index backend on Apple
Silicon; opt-in escape hatch only), `CTX_MLX_QUIESCE` (1).

---

## Status

- **Deadlock (Bug A): fixed and verified** — the store-hold removes the
  connect→init supervisor race; the supported order (`init` → `connect`) also
  continues to work.
- **Index-write segfault (Bug B): fix is `quiesce_mlx()` on the MLX path; the
  earlier FastEmbed swap was reverted.** The MLX-only crash-free claim must be
  re-verified on Apple Silicon with the swap gone (≥20 clean first-inits) — see
  the "Open on macOS" note above and
  `docs/scubiee-macos-handoff-mlx-not-fastembed.md`.
- **Known separate item (not this fix):** the LIVE engine's MLX *warm* path can
  still hit the pre-existing warm-start segfault class (the `CTX_SERIAL_WARM`
  territory) under heavy churn; it is independent of index/connect ordering and
  tracked separately.
