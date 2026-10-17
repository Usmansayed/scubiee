# Scubiee macOS handoff — 0.3.146 → 0.3.148

_Platform validated: macOS 26.5.2, Apple Silicon (M5, arm64), MLX/Metal, Python
3.12.14 / numpy 2.5.x. All results below are from live runs on this machine, not
estimates. This handoff is deliberately explicit about what is NOT covered._

## TL;DR

On **Apple Silicon / MLX**, scubiee 0.3.148 is solid: a critical fresh-init
crash is fixed, `focus`/`find` work across all grammar-supported languages, every
CLI/MCP command and all sync lanes were exercised on real repos, and the full
touched-area test suite is green (126/126). The code and the `v0.3.148` tag are
on GitHub `main`. Two things are genuinely NOT done: the package **publish to
PyPI/npm** (blocked on repo-side registry credentials), and validation of
**first-run `scubiee setup`**, **Intel Macs**, and **non-Mac platforms**.

## What shipped (commits on `upstream/main`)

| Commit | Change |
|---|---|
| `1789490` | focus resolves symbols in files with a leading UTF-8 BOM |
| `69833e6` | focus resolves symbols in **every grammar-supported language**, not just Python (new tree-sitter outline: TS/JS/Go/Rust/Java/C/C++/Ruby/C#) |
| `668fffa` | outline JS/TS arrow + function-expression bindings (`const f = () => {}`, class-field arrows) |
| `76de9f5` | index `.cc/.cxx/.mjs/.cjs/.mts/.cts` (were silently skipped) |
| `792314a` | **CRITICAL**: kill fresh-init concurrent-MLX segfault; harden focus recall |
| `7dd2a85` | focus handles Unicode/`$` identifiers, line-range targets, over-long input |
| `098f520` | find survives source files with NUL bytes (was crashing arbitrary queries) |
| `cf68abf` | doctor stale entries non-blocking + retention-safe prune; map CLI path arg; bump **0.3.148** |
| `4a5fbc0` | health chunk count subtracts tombstones (stops drifting after deletes) |
| docs | polyglot findings, production-readiness matrix, response times, this handoff |

## The critical bug (and why it mattered)

Fresh `scubiee init` on a real repo SIGSEGV'd ~1/3–1/2 of the time on Apple
Silicon. Root cause: a cross-thread native race — the warm thread's Accelerate
LAPACK (`turbo_quant` codec `qr`) running concurrently with the `_eager_prewarm`
MLX embed. MLX Metal and Accelerate BLAS/LAPACK are not safe to run concurrently;
the existing lock only guarded MLX-vs-MLX. Fixed with a shared `mlx_native_guard`
(RLock + quiesce) around the `qr`, GC-disable during the MLX mmap build, and an
MLX-first backend choice that skips a risky concurrent `import fastembed`.
**Verified: 10/10 (Python) + 6/6 (JS) + 6/6 (Java) clean inits, 0 crashes across
every repo tested, including a 13k-chunk one.** This only surfaced on real repos
with enough chunks to trigger the warm/prewarm overlap — the in-tree fixtures
never hit it.

## What was tested on Mac (and passed)

### Languages (focus + find)
Validated on real GitHub repos — single-language (click/mux/serde_json/gson/zod/
stb/sinatra/Catch2) and polyglot (leachim6/hello-world: 12 languages in one repo
→ 16/16; grpc-gateway: 13k chunks, 0 crashes). focus resolves bare names,
`Class.method`, `file::symbol`, line ranges, Unicode (`αβ`, `École`) and `$`
names (`data$`), and symbols defined only in test files. Languages with a bundled
grammar: Python, JS/JSX, TS/TSX, Go, Rust, Java, C, C++, Ruby, C#.

### CLI commands
`init`, `connect`, `search`, `status`, `gate`, `sync`, `remove`, `engine
start/stop`, `map` (find/focus), `preflight`, `certify` (20/20), `doctor`,
`doctor --fix`. All exercised on a clean install.

### MCP tools (live, through the real MCP server)
`gate`, `status`, `map find`, `map focus` — all working end-to-end.

### Sync (exhaustive — every lane)
no-op, add, modify, delete, rename (same dir), move (across dirs), rapid
successive edits (debounce), multi-file batch (4 languages at once), the
automatic keeper/file-watcher (no explicit sync — picked up in ~3 s), and an
oversized 60-file batch. All correct; renames/moves fully prune the old path.

### Response times (measured)
- Warm: `gate`/`status` sub-ms; `map find` ~18 ms; `map focus(file::symbol)`
  ~6 ms; `map focus(bare name)` ~236 ms (disk grep+outline per call — the one
  latency outlier; qualified form is ~40× faster).
- Cold start: 1.7 s soft-ready (find/focus usable), 5.9 s dense-ready.
- Call after short idle (< 80 min): no penalty (~15–19 ms). After idle-standby
  (engine demoted): re-warm ~1.3 s soft / ~5.8 s dense; the supervisor
  auto-restarts so normal idle calls land warm.

### Clean install
Uninstalled the dev tool, deleted the build venv + artifacts, reset state, then
`uv tool install` from the wheel on a fresh numpy — preflight/certify/init/MCP/
sync all green, 0 crashes.

### Test suite
126/126 across every touched area (focus/outline/resolver/doctor/live-reindex/
connect-then-init). Pre-existing failures in the trace-lab/polytrace fixtures and
some DirectML-only tests were confirmed unrelated (identical with changes
reverted) and are out of scope for Mac/MLX.

## Adversarial hardening (bug-bounty pass)

Deliberately attacked with hostile inputs. Found + fixed: Unicode/`$` identifier
resolution, line-range focus targets, over-long target name crash
(`OSError ENAMETOOLONG`), and a NUL-byte source file crashing `find` for
arbitrary queries. Confirmed safe (no crash, graceful degrade): path traversal,
control chars, emoji, 5000-char names, mixed CRLF/LF/CR, BOM-only files, deep
nesting, 20-way parallel calls.

## NOT validated — do these before any broader production claim

1. **First-run `scubiee setup`** — all testing ran against an already-installed
   tool. The very first `setup` on a fresh machine (download MLX weights, pick
   accelerator, write MCP config, register login supervisor) was NOT re-run from
   scratch. This is the least-tested path for a brand-new user.
2. **Package publish** — the `v0.3.148` tag triggers `.github/workflows/
   publish.yml`, which builds the wheel + npm tarball correctly but FAILS at the
   registry push: PyPI "Trusted publishing exchange failure" (no trusted
   publisher configured) and npm empty `NPM_TOKEN`. Every release v0.3.144–148
   failed the same way. This is repo/registry **credentials config**, not code —
   the repo owner must set up PyPI trusted-publishing and the `NPM_TOKEN` secret.
   Until then, `uv tool install scubiee` from PyPI will not get 0.3.148; install
   from a built wheel or git.
3. **Intel Macs** (x86_64) — untested; MLX is Apple-Silicon-only, so Intel takes
   the FastEmbed/ORT path which was not exercised here.
4. **Windows (DirectML) / Linux (CUDA/CPU)** — untested on this machine. Run the
   same matrix there before a cross-platform claim.
5. **Very large monorepos** (100k+ files) — largest tested was ~13k chunks. The
   10k-chunk confirm gate exists but the scale path beyond that is unexercised.
6. **Grammar-less languages** (`.kt .swift .php .scala .sh`) — these index and
   `find` works, but `focus` uses a grep fallback, not full tree-sitter. Adding
   those grammars as deps would upgrade them with no code change.

## Known non-defects (documented so they aren't re-filed as bugs)

- `map focus` bare-name latency (~236 ms) — inherent cost of resolving an
  unqualified name; use `file::symbol` for ~6 ms.
- Ultra-common 2-char names (Rust `io`) resolve only via qualified form.
- A proprietary language sharing a standard extension (DeNA `.jsx`) mislabels;
  real React `.jsx` is correct.
- `doctor replay_dirty_journal` stays blocking while a dirty journal is pending —
  that is a real "sync owed" signal, correct behavior.

## State at handoff

- Branch `main` == `upstream/main` (0/0), tag `v0.3.148` on GitHub.
- Version 0.3.148, `requires-python >= 3.11`, Python 3.12.
- Engine warm on the workspace repo (8642 chunks, 0.3.148).
- Working tree clean (only auto-generated `.kiro/*` + `AGENTS.md` stamps differ).
