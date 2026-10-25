# Scubiee Windows/DirectML validation: 0.3.148

_Platform: Windows, AMD Ryzen 7 5800H + Radeon, DirectML (DmlExecutionProvider),
Python 3.13.5 (uv-tool engine), scubiee 0.3.148. All results are from live runs
on this machine, not estimates. Mirrors the macOS 0.3.148 matrix on the Windows
tier._

## TL;DR

On **Windows / DirectML**, scubiee 0.3.148 is solid across repo structures and
languages: `find`/`focus` resolve correctly in Python, JS/TS (`.ts/.mjs/.jsx`),
Go, Rust, Java, C, C++, and a 7-language polyglot repo; every sync lane
reconciles correctly; response times are in the expected range; and **zero
crashes** across the whole matrix, including an adversarial repo with a NUL-byte
source file and an 80k-field minified single line. One new hardening fix landed
this pass (find size-cap). The Mac-side find NUL-byte fix (`098f520`) is present
and confirmed.

## New fix this pass: find size-cap (`map_v3_helpers._lines`)

The macOS 0.3.148 bug-bounty pass fixed a `find` crash on NUL-byte source files
(the C tokenizer raised a `SystemError` that escaped the guard). Reviewing that
fix, two **sibling paths** in the same `find` flow still had the same class of
"pathological file degrades find" exposure that the NUL fix did not cover:

1. `_text`/`_lines` had **no file-size cap** (unlike `_grep`'s 2 MB skip), so a
   huge file in a `/v1/search` hit would be slurped whole into memory by
   `_noncode_spans`/`_code_text`/`_numbered`.
2. `_STRING_RE` ran per physical line in the non-`.py` branch; a pathological
   multi-hundred-KB single line (minified bundle, unterminated literal) made the
   lazy `[\s\S]*?` scan super-linear and could stall `find`.

**Fix:** `_lines` now caps text at `_MAX_FILE_BYTES` (2 MB) and truncates any
single line over `_MAX_LINE_CHARS` (200 KB), the single read point every
non-grep locate helper flows through. Closes both at once; never crashes, never
OOMs, never stalls on a pathological file. A file big enough to exceed these is
generated/minified/vendored and not worth masking precisely.

Tests: `tests/test_focus_adversarial.py` adds `test_lines_caps_huge_file` and
`test_lines_caps_pathological_long_line`. Suite: 17/17 green. Touched-area
suites (focus/outline/resolver/BOM) 48/48 green.

## Languages × structures (find + focus)

Nine test repos covering single-language and polyglot structures. Each was
`init`'d clean (exit 0) and exercised through the live engine.

| Repo | Structure | chunks | find top hit | focus |
|---|---|---|---|---|
| py_app | Python, nested `src/payments`,`src/auth`,`tests/` | 10 | gateway.py / jwt.py ✓ | charge_card, StripeGateway ✓ |
| ts_app | TS/JS, mixed `.ts`/`.mjs`/`.jsx` | 9 | cache.ts / webhook.mjs / component.jsx ✓ | LruCache ✓ |
| go_app | Go | 4 | server.go ✓ | NewRouter ✓ |
| rust_app | Rust | 3 | lib.rs ✓ | TokenBucket ✓ |
| java_app | Java, deep `com/example` package | 5 | UserService/UserRepository ✓ | findUser ✓ |
| cpp_app | C++ `.cc`/`.hpp` | 3 | vector_math.cc ✓ | dot_product ✓ |
| c_app | C | 2 | hashmap.c ✓ | hash_key ✓ |
| polyglot | 7 langs in one repo (py/ts/go/rust/java/cpp/sh) | 9 | all 4 queried langs disambiguated ✓ | - |
| adversarial | NUL-byte file + 80k-field minified line + real symbol | 4 | normal.py ✓ (no crash) | - |

- **find: 15/16** semantic queries returned the correct top file. The one miss
  (java "user service that loads a user by id" → `UserRepository.java` rather than
  `UserService.java`) is a reasonable semantic result, the repository holds the
  `load(id)` method the query describes, not a defect; both files are in the hit
  set.
- **focus: all languages PASS** via the CLI (`map --config focus --names <sym>`),
  each returning `file::symbol`, the line range, and the body, Python, TS, Go,
  Rust, Java, C++, C all resolve bare names correctly.
- **adversarial repo indexed and searched with zero crashes**, exercising both the
  Mac NUL-byte fix and the new size-cap fix end-to-end.

## Response times (measured, Windows/DML)

Small repo (py_app), warm engine:

| Signal | Latency |
|---|---|
| `/health` (backs `gate`/`status`) | p50 **2.1 ms** |
| `tool status` | p50 **14 ms** |
| `tool gate` | p50 **80 ms** (first-call project check) |
| `find` cold-first | **148 ms** |
| `find` warm steady | p50 **150 ms** (135-278) |
| `focus` file::symbol | p50 **<1 ms** |
| `focus` bare name | p50 **1 ms** (small repo) |

Cold start (small repo): **soft-ready 1.8 s, dense-ready 3.0 s**. (The main
~8.9k-chunk workspace repo is ~9 s soft / ~24 s dense, scale-dependent, as
documented in the perf-timings doc.) `focus` bare-name is the known latency
outlier on large repos (whole-tree grep+outline, ~236 ms there); the qualified
`file::symbol` form is far faster.

## Sync: every lane (on a polyglot copy)

| Lane | Result |
|---|---|
| add file | new symbol searchable (`newmod/added.py`) ✓ |
| modify file | appended symbol reconciled, top hit = modified file ✓ |
| delete file | chunk count drops, path pruned ✓ |
| rename (same dir) | search returns the NEW name; old path gone ✓ |
| move (across dirs) | search returns the new location ✓ |
| batch (4 files at once) | all picked up, chunks grow ✓ |
| **auto-watcher** (no explicit `sync`) | new file auto-indexed within ~8 s ✓ |

All lanes correct; renames/moves fully prune the old path, matching the macOS
result.

## Crashes

**Zero** `SIGSEGV`/`SIGTRAP`/`SIGBUS`/`SystemError`/traceback signatures across the
entire matrix (9 repos, every language, all sync lanes, the adversarial repo, and
repeated warm/cold cycles). Engine healthy throughout.

## NOT covered here (same caveats as the macOS handoff)

1. **First-run `scubiee setup`** on a brand-new machine, this pass ran against an
   already-set-up tool. (A prior session validated `setup --repair` end-to-end on
   a clean python.org venv after the numpy no-deps fix.)
2. **Very large monorepos** (100k+ files): largest exercised here is the ~8.9k-chunk
   workspace repo.
3. **Grammar-less languages** (`.kt .swift .php .scala .sh`): index and `find`
   work; `focus` uses the grep fallback, not full tree-sitter.
4. **Linux (CUDA/CPU)**: untested on this machine.

## State

- scubiee 0.3.148, DirectML (`DmlExecutionProvider`), engine Python 3.13.5.
- find size-cap fix + 2 tests added; all touched-area suites green.
