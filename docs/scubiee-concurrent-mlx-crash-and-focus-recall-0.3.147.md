# Fresh-init concurrent-MLX crash + focus recall fixes (0.3.147)

Found by running real GitHub repos across 10 languages through a full
`init` → `focus`/`find` cycle (the tiny in-tree fixtures never exercised the
warm/prewarm concurrency, so these only surfaced on real repos).

## Bug 1 (critical): fresh `init` segfaults ~1/3–1/2 of the time on Apple Silicon

**Symptom.** On a fresh `init` of a real repo, the engine SIGSEGV'd during warm.
The faulting frame varied across runs — all symptoms of ONE cross-thread native
race, not three bugs:
- `numpy.linalg.qr` inside `turbo_quant._random_orthogonal` (Accelerate LAPACK)
- `CodeRankMLX.__init__` building the MLX model (`Garbage-collecting` in frame)
- `import fastembed` → `import numpy.typing` on a worker thread

**Root cause.** The warm path builds the turbo-quant codec (numpy→Accelerate
`qr`) on the warm thread, while `_eager_prewarm` runs an MLX `embed_one` on a
Timer thread. MLX Metal kernels and Accelerate BLAS/LAPACK are not safe to run
truly concurrently on Apple Silicon; `_MLX_EMBED_LOCK` only serialized MLX-vs-MLX,
not MLX-vs-Accelerate. A GC pass firing mid-construction and a concurrent heavy
`import fastembed` were two more faces of the same race.

**Fix (three layers, defense in depth):**
1. `mlx_mac`: `_MLX_EMBED_LOCK` is now an `RLock`, and a new `mlx_native_guard()`
   context manager takes that lock + quiesces GPU work. `turbo_quant`'s `qr`
   runs inside this guard, so the Accelerate `qr` and MLX embeds are mutually
   exclusive. No-op/uncontended off MLX; never fatal if the import is absent.
2. `mlx_mac.CodeRankMLX.__init__`: disable cyclic GC across the mmap→MLX array
   construction loop (re-enable + collect once after), so a GC pass can't free a
   superseded mmap view mid-conversion.
3. `embedder._choose_backend`: on an MLX runtime, pick MLX directly via a new
   cheap `_runtime_is_mlx()` instead of calling `_fastembed_available()` (which
   does `import fastembed`, pulling numpy.typing/torch). That import on a worker
   thread while MLX held a live Metal context was the third crash face; the accel
   re-check downstream would flip the choice to MLX anyway, so the import was
   pure risk.

**Result.** 10/10 clean inits on the Python repo and 6/6 on the JS repo that
previously crashed ~1/3–1/2 of the time; 0 segfaults across all 8 sim repos.

## Bug 2: `focus` could not resolve a symbol defined only in a test file

`_resolve_symbol_name` hard-filtered grep hits to `_kind_of == "code"`, so any
symbol living only under `tests/` / `*_test.*` (a test class/helper like
`CacheTest`, Go `*_test.go` helpers) returned "could not resolve" by bare name.
Changed the hard filter to a code-first *ranking* (code → tests → docs) that
keeps test hits. Python focus went 19/26 → 26/26 on the cachetools sim repo.

## Bug 3: `focus` missed definition shapes the keyword grep can't match

C `struct __attribute__((__packed__)) Name` and Rust `mod x;` were missed by the
keyword/decl grep patterns even though the outline captured them. Added a
plain-identifier grep fallback that collects candidate files and confirms each
via the (authoritative) multi-language outline — recall without false positives.
Fixed C `sdshdr5`. (Ultra-common 2-char names like Rust `io`, which flood any
text search, still resolve only by qualified `file::symbol` — an acceptable
limit; `focus_qual` works.)

## Bug 4: `focus` raised when the engine was unreachable

`_resolve_symbol_name`'s final semantic-search fallback hit `/v1/search` over
HTTP unguarded; a down/warming engine made it raise through `focus`. Wrapped it
so bare-name resolution degrades to `None` (the grep+outline passes are
engine-free) instead of propagating an exception.

## Verification

- 8 real repos (Python, Go, Rust, TypeScript, Java, Ruby, C, JavaScript):
  0 init crashes; focus 26/26, 24/24, 7/8, 24/24, 24/24, 24/24, 4/4, 24/24.
- No false positives (junk names stay `None`; outline confirmation guards recall).
- Pre-existing suite failures confirmed unrelated (identical with changes reverted).
