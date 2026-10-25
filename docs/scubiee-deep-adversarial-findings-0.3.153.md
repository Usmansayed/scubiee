# Scubiee deep adversarial testing: 0.3.153

_An in-depth, bug-hunting session that goes beyond command/sequence coverage into
the nasty corners: concurrency/races, filesystem edge cases, malformed &
injection-style input, state-file corruption, interrupted operations, and
arg/flag fuzzing. ~120 command invocations across 7 categories on an isolated
home (`SCUBIEE_KEEP_OTHER_INSTALLS=1`, dedicated CTX_HOME). Goal was to **find
failures**, not confirm success._

## Bottom line

**Zero tracebacks. Zero true deadlocks. Zero install corruption. Injection-safe.**
The engine is notably robust under abuse. No new shipping blockers found. A
handful of **minor / cosmetic** nits are listed at the end. The earlier
0.3.152/0.3.153 fixes (running-interpreter guard, broad-root bounded cap) held up
under parallel and interrupted stress.

## What was tested & results

### 1. Concurrency / races: PASS
| Scenario | Result |
|---|---|
| Two parallel `init` of the **same** fresh repo | Both exit 0; **one clean enrollment**, single project_id, no duplication |
| `search`/`map`/`status` during a big `init` | search/status exit 0; map exit 1 = clean "engine not running, retry" (transient restart window) |
| Double `engine start` simultaneously | Both exit 0 |
| Parallel `connect --cursor` + `connect --kiro` | Both exit 0, **no package corruption** (the 0.3.152 guard holds under parallel consolidation) |
| `pause` + `search` simultaneously | Both exit 0 |

### 2. Filesystem edge cases: PASS
Empty repo (enrolls; search exit 1 = nothing found), dir name with spaces +
unicode, 12-level deep nesting, single 4000-function file, binary/non-UTF-8 file
alongside real code, **all init + search cleanly (exit 0)**. Nonexistent path /
file-instead-of-dir → clean exit 1. (A "trailing-slash init failed" blip turned
out to be a PowerShell `\"` quoting artifact, **not** a scubiee bug, verified
directly.)

### 3. Malformed / adversarial input: PASS (security highlight)
24 hostile inputs, **zero tracebacks**. Injection-style queries, `foo; rm -rf /`,
`foo | echo`, backticks, `$(calc)`, `%PATH%`, were all treated as **literal
search text** (exit 0, no shell execution). 10k-char query → clean exit 1.
Non-int `--k abc` → exit 2. All malformed flags rejected cleanly.

### 4. State-file corruption + recovery: PASS (robustness highlight)
Every state file corrupted (truncated / garbage / empty / wrong-type) and a
command run against it:
- `connected_tools.json` → **self-heals to valid JSON** via the atomic-write +
  `.bak` mechanism; status/connect exit 0.
- bad / mismatched repo `id.json` → ignored as designed; status/search exit 0.
- broken `registry.json` / `accel.json` → `list`/`status`/`resources` exit 0;
  `doctor` exit 1 (**correctly flags** the problem).
- corrupt store `meta.json` → search exit 1 clean, status exit 0.

No crash under any corruption.

### 5. Interrupted operations: PASS (investigated hard)
Killing `init` mid-index, killing the engine mid-search, planting stale
dirty-markers + dead-pid `engine.json`, and deleting the store dir. Initial batch
flagged two "HANG" timeouts; **deep isolation downgraded both**:
- Re-`init` after a killed init **progresses normally** on a clean repo
  (observed 23%→77%→done), the batch "hang" was a genuinely slow 6000-function
  re-embed, compounded by a corrupt `id.json` left by the test harness itself
  (not scubiee).
- **Recovery is sound:** a repo killed mid-init and re-init'd ends up
  `enrolled / active / chunks=6000`: a fully working index. No poisoned state.
- Stale dirty-marker + dead-pid `engine.json` → search completes fine in
  isolation (returns hits). The batch "hang" was an engine cold-warm wait
  exceeding the 40s harness timeout.
- Killing the parent `init` cascades to its children (no orphans).

### 6. Arg / flag fuzzing: PASS
30 combos: conflicting flags, flag ordering (flags before/after positionals),
repeated flags (last-wins), extra positionals (exit 2), typo flags (all exit 2
clean argparse), `--help`/`-h`/`--version`, `--` separator. No tracebacks.
(`upgrade --pre-release` exit 2 was a wrong-flag-name in the test; the real flag
is `--pre`.)

## Minor / cosmetic nits (non-blocking)

1. **`map --k` accepts non-positive / absurd values** (`-5`, `999999`) → exit 0.
   It clamps gracefully (returns available results, no crash, no resource blowup)
   but doesn't reject at the parser. Ideally validate `--k >= 1`.
2. **`pause` / `resume` on an unmanaged cwd** returns a terse
   `{"error":"unmanaged"}` (exit 1) with no actionable hint. Suggest a friendlier
   message ("run inside a managed repo or pass a repo path").
3. **CLI flag inconsistency:** `connect`/`disconnect` take `--repo`, while
   `map`/`search`/`init`/`status`/`sync` take a positional `path`. Unify or
   document.
4. **`re-init quiesce` on very large repos:** `initialize_repo` →
   `quiesce_background_indexing` waits on the busy engine, which can *feel* like
   a stall (no dedicated progress line) during the quiesce phase. Not a hang, but
   a heartbeat there would help perceived responsiveness.
5. **`init --roots <nonexistent>`** silently indexes nothing (exit 0) rather than
   warning that the roots filter matched no files.

## Verdict

Under heavy adversarial pressure, parallelism, corruption, interruption,
injection, and fuzzing, scubiee 0.3.153 did not produce a single traceback,
deadlock, or corrupted install, and its self-healing (state-file `.bak` recovery,
interrupted-init recoverability, injection-safe literal query handling) is a
genuine strength. The remaining items are cosmetic polish, not reliability bugs.
