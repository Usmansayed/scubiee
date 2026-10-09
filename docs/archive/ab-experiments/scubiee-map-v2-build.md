# Scubiee map v2: build notes and comparison with the old map

> **Historical build log.** This records the Map **v2** harness prototype (five configs
> `find`/`refs`/`open`/`around`/`outline` in `scripts/claude_sdk_harness/map_v2_bridge.py`).
> It evolved into the shipped **Map V3** product surface — four configs
> `find`/`focus`/`related`/`graph` (+ `gate`/`status`) served by `pipeline.map_v3_server`
> through the `scubiee-mcp-bridge`. For the current surface see the header note in
> `docs/scubiee-map-configs.md`. Kept as a dated record of how the bridge was built and
> validated against the live engine.

**What it is:** one `map` tool with five configs (`find`, `refs`, `open`, `around`, `outline`), built as a standalone MCP bridge.

| | |
|---|---|
| Design | `docs/scubiee-map-configs.md` |
| Status | all 5 configs working against the live engine. Not yet tested with a real agent: no Claude runs, by request. |

## Files

| File | What |
|---|---|
| `scripts/claude_sdk_harness/map_v2_bridge.py` | The new MCP server. Exposes `map` (5 configs) plus `gate` and `status`. |
| `scripts/claude_sdk_harness/mini_mcp_bridge.py` | The old simple map, left unchanged as the comparison baseline. |
| `scripts/claude_sdk_harness/test_map_v2.py` | 28 checks over real MCP stdio against the live engine. |
| `scripts/claude_sdk_harness/compare_map_versions.py` | Runs the old and new map against the same 7 agent needs. Output goes to `research/map_version_compare.json`. |

Core Scubiee is untouched.
- The bridge talks to the running engine over HTTP (`/v1/search` for semantic ranking, `/health`) and reads file text from disk.
- It imports nothing from Scubiee's `mcp_*` modules.

To run:
```text
set MINI_REPO=<repo root>
python scripts/claude_sdk_harness/test_map_v2.py --quiet
python scripts/claude_sdk_harness/compare_map_versions.py
```

## The five configs as built

| config | Arguments | Returns |
|---|---|---|
| `find` | `query`, optional `keywords`, `scope` (default `code`), `k` | Ranked results, each as a `file:start-end` range plus the enclosing symbol and matched lines with line numbers. Each result says whether it matched by keyword or by meaning. A confidence level with its reason. When confidence is high, the top function's code. Related tests on one line. Suggestions when nothing matches. |
| `refs` | `names`, `kind` (`def`/`uses`/`imports`/`all`), `scope` (default `code`) | A count per name (definitions, uses, imports; code/tests/docs). One line per occurrence, saying which function it sits in. Mentions that appear only inside strings or comments are counted separately and not listed. |
| `open` | `targets` (`file::symbol`, `file:line`, `file:a-b`, file), `margin`, `budget_chars` | The code of each target's enclosing symbol, starting at its def line (with decorators and comments directly above), plus a margin after. Several targets in one call. Code already shown this session is skipped or continued. A bare file path returns its outline, never the whole file. |
| `around` | `target`, `want` (`callers`/`callees`/`tests`/`siblings`) | One line per caller, test and callee. Callees are resolved to their definitions in the repo; library calls are listed separately. |
| `outline` | `path`, optional `query`, `depth` | **Directory:** every file name, then one-line summaries as space allows. **Small directory:** symbols too. **File:** symbols with line ranges and signatures. With `query`: fuzzy file-name matches, then matching definitions. |

**Shared defaults for every config:**
- line numbers on every code line
- a hard character budget (4,000 by default; 6,000 for `open`)
- "already shown" tracking per session, reset when a file changes
- code before tests and docs
- ASCII-only output

## Test results: 28 of 28 pass

The checks run over real MCP stdio against the live engine, using known facts about this repo. Examples:
- `find` with keyword `git_dirty_files` ranks `freshness.py:105` first, with high confidence, and includes the body.
- `refs` reports 1 def, the use in `check_freshness`, and both tests, without counting example strings in our own scripts.
- `open` on `server.py:800` returns the enclosing `_retire_self`.
- `around` resolves `is_junk_rel` to `ignore.py:418` and finds the caller at `server.py:926`.
- `outline` of a 228-file directory still lists every file.
- Error paths: unknown name, misspelled symbol, missing file, bad config.

**Bugs found and fixed while building:**

| Problem | Fix |
|---|---|
| The engine's `/v1/grep` walks files alphabetically and stops at its hit cap, so `docs/` filled the results before `packages/` was reached. Each call also took about 2 s. | The bridge greps itself, code files first, with file text cached per modification time. |
| Names inside strings and comments counted as uses (our own scripts and docs mention `git_dirty_files` in example text). | Python's tokenizer masks strings and comments. Those hits are reported as "only in strings/comments". |
| A grep pre-check missed `^`-anchored patterns, so a definition lookup found nothing. | The pre-check is multiline. |
| Decorated classes showed `@dataclass` as their signature, and `open` started inside the previous function. | Signatures skip decorators. Spans start at the symbol. The margin goes after the code, where agents keep reading. |
| One-line module docstrings outranked real functions. | They're down-weighted. Query words that appear in a symbol's name boost that symbol (`faiss_import_ok` now ranks first for a faiss question). |
| A large-directory outline ran out of budget alphabetically, before `token_meter.py`. | All file names come first, then summaries. |

## Comparison with the old simple map

There are 7 agent needs, taken from the session study. Each version starts each need with a fresh session. A need counts as met when its required facts are in what the agent received.

How each version was measured:
- **Old map:** its real responses, plus the native follow-ups agents made in our recorded sessions when map wasn't enough. Those follow-ups are **simulated**: a 60-line Read from the card start (the median), a whole-file Read when that missed, `Grep -n` and `ls`. Their sizes are computed from the real files on disk.
- **v2:** real responses only.

| Need | Old: calls / chars | v2: calls / chars | Old steps → v2 steps |
|---|---:|---:|---|
| N1 locate + read the code (dirty files) | 3 / 21,666 | **1 / 2,748** | map → Read 60 lines (wrong part of the file) → Read whole file → `find` with the body inline |
| N2 locate by concept, no names (idle self-retire) | 2 / 6,769 | **1** / 3,521 | map → Read → `find` returns the body inline (medium confidence) |
| N3 every use before changing a signature | 2 / 16,923 | **1 / 787** | map (no usages) → Grep → `refs` |
| N4 read two known places | 2 / 4,844 | **1** / 5,022 | Read + Read → `open` with 2 targets |
| N5 callers + tests of a function | 2 / 8,369 | **1 / 584** | map → Grep → `around` |
| N6 what's in this directory | 2 / 4,354 | 2 / 6,073 | `ls` → Read file head → `outline` dir → `outline` file |
| N7 locate the task target (token savings) | 1 / 3,918 | 1 / 3,054 | map → `find` (now with the body) |
| **Total** | **14 calls / 61,580 chars, 7 of 7 met** | **8 calls / 23,778 chars, 7 of 7 met** | |

v2 used **43% fewer calls and 61% fewer characters**, and met the same 7 needs.

The call count is the number that matters most, because each extra call re-reads
the whole transcript (~35–40k tokens in our runs). v2's larger per-call responses
(it returns code inline on find, several targets on open) are the deliberate
trade: spend a few thousand characters to remove a round-trip. See
`docs/scubiee-map-configs.md` section 2.7.

**Where the gain comes from:**
- **N1:** the body comes back inline, with the right span. The old map's top card
  pointed at line 1 of `freshness.py`, so the 60-line Read missed the function and
  a whole-file Read followed.
- **N2:** `find` now returns the top body on **medium** confidence, so what used to
  be find → open is one call.
- **N3 and N5:** relation questions. The old map can't answer them, so the agent
  greps the whole repo: 15–17k characters, including docs and our own scripts.

**Where there's no gain:**
- **N4:** `open` saves a call but returns about the same amount of code (whole
  functions plus margin).
- **N6:** same number of calls; v2 is larger because its directory outline lists
  every file plus summaries, where the old `ls` + one head Read was smaller but
  showed only one file's contents.

## Limits

- **Not tested with a real agent yet.** Whether agents pick the right config, and whether the call and character savings survive real behavior, needs the A/B test in `docs/scubiee-map-configs.md` section 8.
- **The old-map follow-ups are simulated** from the measured session medians. A real agent might do better (a lucky Read range) or worse (grep chains: median 2, up to 10).
- **Latency:**

  | Config | Time per call |
  |---|---|
  | `open`, `outline` | 1–12 ms |
  | `find` | 0.3–3.4 s (engine search, plus a repo grep when keywords are given) |
  | `refs`, `around` | 2.1–2.8 s (the bridge scans all text files in the repo) |

  For `refs` and `around`, a symbol index would bring that well under a second.
- **Outlines are Python-only for now**, from Python's AST. Other languages fall back to the engine's outline route, which is also Python-only. So in non-Python files, `open`, `around` and `outline` fall back to line windows instead of symbols.
- **One repo** (this one), and the test facts were written for it. The spot checks on queries the tests weren't written for were consistent, but a second repo would be a better test.

## Next step

Point a harness arm at `map_v2_bridge.py` (one line in `harness_core.mini_mcp_config`). Then run the section 8 A/B from the design doc: without vs old map + v3 vs map v2.
