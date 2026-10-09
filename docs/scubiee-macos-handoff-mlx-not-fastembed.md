# macOS handoff — DO NOT swap MLX → FastEmbed for the index build

_Audience: the macOS agent working on Apple Silicon (MLX/Metal)._
_Context: commit `984e8a5` ("fix(macos): make connect-then-init reliable")._
_Status: Bug A fix = KEEP. Bug B fix (FastEmbed index swap) = REVERT to MLX-first._

---

## TL;DR — the decision you must respect

**MLX is the chosen embedder on Apple Silicon. Keep it.** The owner picked MLX on
purpose (Metal GPU, fast local embeds). The index build must stay on MLX. Do
**not** route the one-time index build through FastEmbed/ONNX on Darwin. The
previous change did exactly that and it is being rolled back.

If MLX crashes at the vector write, **fix the crash on the MLX path** — do not
run away to a different embedder.

---

## What went wrong in 984e8a5

Two bugs were fixed in one commit. One fix is good; the other is a bad decision.

### Bug A — connect→init deadlock → **the fix is correct, keep it**
The supervisor started by `connect` kept respawning/idle-stopping the engine
while `init` tried to take the exclusive store write-lock, so `init` wedged. The
fix is a bounded, self-expiring **store hold** (`engine_transition.json`
`store_hold_until`) that makes `engine_should_be_running()` return `False` while
an outside writer owns the lock. This is clean, platform-agnostic, self-expiring,
and verified on Windows (68 lifecycle/watchdog tests pass). **Leave this alone.**

Files for Bug A (keep): `lifecycle_runtime.py` (store-hold flag + guards),
`watchdog.py` (loop no-op while held), `repo_lifecycle.py` (set/clear around the
index block), `__main__.py` (bounded `ensure_daemon` handoff).

### Bug B — index-write segfault → **the FastEmbed swap is the wrong fix**
A full index embeds on MLX/Metal, then does a numpy-LAPACK / faiss vector write
(`store.upsert_vectors` → `turbo_quant` QR / `np.zeros`) in the same process.
MLX's Metal allocator leaves the heap in a state that trips the malloc guard
(~1/3 of inits SIGTRAP/SIGSEGV at "Writing index"). That root cause is real.

The fix shipped two things:
1. `mlx_mac.quiesce_mlx()` — synchronize + clear the Metal cache under the embed
   lock **before** the faiss/numpy write. **This is the right idea.**
2. `indexer.py` — default the entire index build to **FastEmbed/ONNX on Darwin**
   whenever MLX would otherwise be used. **This is the wrong idea** and must go.

The problem: with (2) in place, `embedder.backend` is `"fastembed"`, so the
`quiesce_mlx()` guard in `indexer.py` (`if ... embedder.backend == "mlx"`) never
runs. The two fixes were never tested independently — the backend swap masks
whether `quiesce_mlx()` alone already solves the crash. It very likely does.

Why the swap is bad regardless:
- **It overrides a deliberate architecture choice.** MLX was chosen on purpose.
- **It splits the embedder within one install** — index vectors produced by
  FastEmbed/ONNX, queries produced by MLX. Same model + 768-dim, but two native
  code paths generating vectors that must stay numerically comparable. That is a
  silent correctness risk you do not want in the retrieval path.
- **It is slower** on a large repo and adds a one-time ONNX model download.
- **It treats the symptom, not the cause.** The cause is "MLX didn't release
  Metal buffers before the next native allocator ran." Fix that.

---

## What to do

1. **Revert the backend swap in `indexer.py`.** Remove the Darwin block that sets
   `index_backend = "fastembed"` when MLX would be used. The index build stays on
   whatever `Embedder` resolves normally (MLX on Apple Silicon). Keep the
   `CTX_INDEX_EMBED_BACKEND` override knob if you want an *escape hatch*, but the
   **default on Apple Silicon must be MLX**, not FastEmbed.

2. **Make `quiesce_mlx()` the actual fix — and make sure it runs on the MLX
   path.** Keep the `quiesce_mlx()` call before `store.upsert_vectors`, but with
   MLX as the index backend the `embedder.backend == "mlx"` branch will now
   actually execute. Confirm it is called on the main thread, under the embed
   lock, with a full `synchronize()` + `clear_cache()` (+ a momentary
   `set_cache_limit(0)` drain) before the numpy/faiss write.

3. **Prove the MLX path alone is crash-free.** Run the first-ever `init` on a
   clean repo **≥20 times** on MLX with `quiesce_mlx()` active (no FastEmbed
   swap). Expectation: 0 crashes at "Writing index". If it still crashes >0/20,
   escalate the real root cause before considering any backend workaround — and
   bring it back to the owner, because dropping MLX is the owner's call, not the
   agent's.

4. **If and only if MLX genuinely cannot be made stable**, the fallback is still
   not a silent swap. Document the exact failure, the MLX versions, the crash
   signature, and propose the workaround explicitly to the owner for sign-off.
   A deliberate architecture reversal does not get made inside a bug-fix commit.

---

## Guardrails for the Mac agent (standing)

- **Do not change the embedder backend to work around a crash.** MLX is the
  decision. Fix crashes on the MLX path (quiesce / synchronize / allocator
  ordering), not by switching embedders.
- A workaround that reverses an owner architecture decision is **not** an
  autonomous call. Flag it, document it, get sign-off.
- Keep bug fixes scoped: a supervisor-lock deadlock fix and an embedder swap do
  not belong in the same commit.
- The connect→init *feature* (connect records tools machine-wide; init applies
  MCP + rules for each) already works. The only Mac-specific defect there was the
  supervisor deadlock (Bug A), which is now fixed. Do not re-architect the
  connect feature.

---

## Reference — what the connect feature actually is (keep it this simple)

- `scubiee connect <tool>` → append the tool slug (e.g. `kiro`, `cursor`) to the
  machine-wide state file `~/.scubiee/connected_tools.json` (atomic write + `.bak`
  self-heal). One connect per machine, per tool.
- `scubiee init` → read that file and, for each connected tool: write its MCP
  config (if the tool has one) and install its rule files into the repo. Per-tool
  isolation so one failing tool can't block the others.
- `scubiee disconnect <tool>` → remove the slug from the state file.

That is the whole feature. No embedder decisions live here.
