# Scubiee reliability — real-repo + polyglot findings (0.3.147)

_Platform: macOS 26.5.2, Apple Silicon (M5, arm64), MLX/Metal, Python 3.12._
_Method: clone real GitHub repos (single-language and polyglot), run `scubiee
init`, then `map config=focus` (bare name + `file::symbol`) and `map config=find`
against real symbols discovered from the tool's own outline. The in-tree
fixtures never exercised the warm/prewarm concurrency or mixed-extension
structure, so these only surfaced on real repos._

## Repos exercised

Single-language: Python (cachetools), Go (cast), Rust (byteorder), TypeScript
(ky), Java (JSON-java), Ruby (paint), C (sds), JavaScript (lodash, 608 chunks).

Polyglot:
- **leachim6/hello-world** — one repo, 12+ supported languages mixed
  (C, C++, C#, Go, Java, JS, JSX, Python, Ruby, Rust, TS, …).
- **grpc-ecosystem/grpc-gateway** — large Go-dominant polyglot, **13,007 chunks**
  (Go + JS + sh), symbols across 6 top-level directories.

## Bugs found and fixed (all shipped, with regression tests)

### 1. CRITICAL — fresh `init` concurrent-MLX segfault (~1/3–1/2 of runs)
On a fresh init the engine SIGSEGV'd during warm. The faulting frame varied
(numpy `qr` in `turbo_quant`, `CodeRankMLX` construction mid-GC, `import
fastembed` on a worker thread) — one cross-thread native race: the warm thread's
Accelerate LAPACK (`turbo_quant` codec `qr`) running concurrently with the
`_eager_prewarm` MLX embed. Fixed with a shared `mlx_native_guard()` (RLock +
quiesce) around the `qr`, GC-disable across the MLX mmap build loop, and an
MLX-first backend choice that skips the heavy `import fastembed` probe.
Commit `792314a`. **Verified: 10/10 (Python) + 6/6 (JS) + 6/6 (Java) clean,
0 crashes across every repo including the 13k-chunk grpc-gateway.**

### 2. `focus` could not resolve a symbol defined only in a test file
`_resolve_symbol_name` hard-filtered to `_kind_of == "code"`, dropping every
`tests/` / `*_test.*` symbol. Changed to code-first *ranking* that keeps test
hits. Python focus 19/26 → 26/26.

### 3. `focus` missed definition shapes the keyword grep can't match
C `struct __attribute__((__packed__)) Name`, Rust `mod x;`. Added an
outline-confirmed plain-identifier fallback (recall without false positives).

### 4. `focus` raised when the engine was unreachable
The semantic-search fallback hit `/v1/search` unguarded; a down/warming engine
made `focus` throw. Wrapped so bare-name resolution degrades to `None`.

### 5. Common C++/Node extensions were never indexed
`.cc .cxx .mjs .cjs .mts .cts` routed to real extractors but were missing from
the index extension gate — those files were invisible to find/focus. Added them
(commit `76de9f5`).

### 6. `focus` was Python-only; BOM files broke the outline
Multi-language tree-sitter outline + BOM handling (commits earlier in 0.3.147
line). TS/JS/Go/Rust/Java/C/C++/Ruby/C# now outline and resolve.

## Polyglot results (consistency across languages in ONE repo)

hello-world (12 languages mixed): **focus_bare 16/16, focus_qual 16/16,
find 16/16, 0 crashes.** C, C++, C#, Go, Java, JS, Python, Ruby, Rust, TS all
resolved. grpc-gateway (13k chunks): 0 crashes; Go symbols across 6 directories
resolved 6/6 bare + 6/6 qualified; JS resolved.

## Known, non-actionable limits (documented, not bugs)

- **Ultra-common 2-char names** (e.g. Rust `io`, a `mod io;` re-export) flood any
  text search and resolve only via qualified `file::symbol`. `focus_qual` works.
- **`.jsx` used for DeNA JSX** (a non-React language sharing the extension):
  the JavaScript grammar mis-parses `static function main(...)` and labels the
  method `function`. The symbol still resolves; the name is cosmetically wrong.
  We cannot support a proprietary language that borrows a standard extension.
- **`.kt .swift .php .scala .sh`** have no bundled tree-sitter grammar, so they
  outline via the grep fallback rather than full tree-sitter. Adding those
  grammars as dependencies would upgrade them with no code change.
- Files with **no named symbols** (top-level one-liner programs like a C#/TS
  `console.log("…")`) correctly produce an empty outline — not a failure.

## Environment note (not a scubiee issue)

The `javascript-algorithms` repo ships a Node version-manager config that
intercepts shell commands run inside its directory with an interactive install
prompt; running scubiee from inside it hung the terminal. This is the repo's
tooling, independent of scubiee. JS reliability is covered by lodash (24/24) and
the JS files in both polyglot repos.
