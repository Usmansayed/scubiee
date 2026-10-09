# Scubiee bugs and issues found

Consolidated bug list from a dedicated bug-hunting pass against Scubiee `0.3.112`, testing exclusively through user-facing surfaces — the Scubiee MCP tools (`gate`, `status`, `map`, `pack_context`, `expand_context`, `collect_hot_context`, `workspace`, `expand`) and the `scubiee` CLI — rather than the internal pytest suite, since internal tests can pass/fail against mocked behavior that doesn't reflect what a real user actually experiences.

Full narrative context (including everything that worked correctly, timing data, and the surrounding investigation) lives in `docs/kiros-experience-using-scubiee.md`, sections 11-12. This file is the standalone, action-oriented bug list.

**Update:** bugs 1, 2, 3a, 4, 5, 6, 7, and 8 have all been root-caused and fixed in the checked-out source (`packages/pipeline/*.py`). Full root-cause tracing, the exact diffs applied, and functional verification for each fix are in `docs/scubiee-bugs-root-cause-and-fix-plan.md`. Bug 3's deeper half — the stale AST span past EOF — remains open, deferred as a follow-up (see that file's closing section for why). Status is annotated inline below per bug; this file's original bug descriptions are left unedited below the status line so it stays an honest record of what was actually observed, including one correction (Bug 7's empty-query claim) that didn't hold up on re-verification during the fix.

Repo under test: this repo (`context-engine`, self-hosting its own Scubiee MCP server). Version: `scubiee 0.3.112`. Platform: Windows, PowerShell.

---

## Severity summary

| # | Bug | Surface | Severity | Status |
|---|-----|---------|----------|--------|
| 1 | Stale `embed_ms`/`retrieve_ms` on cached `map` repeats | MCP | Low (telemetry only) | **Fixed** |
| 2 | `pack_context` leaks raw internal error + function name | MCP | Medium | **Fixed** |
| 3a | `expand_context`'s `direction` accepts any string | MCP | Low | **Fixed** |
| 3b | Stale AST span past EOF, presented as fresh by `status` | MCP | High (silent wrong answer) | Open — deferred |
| 4 | `workspace(pin)` accepts nonexistent file paths | MCP | Low | **Fixed** |
| 5 | `expand`'s `max_chars<=0` ignores truncation budget | MCP | Low | **Fixed** |
| 6 | Windows console mojibake for all CLI Unicode output | CLI | Medium (UX, all Windows users) | **Fixed** |
| 7 | `scubiee map` reports `engine_down` for a live server | CLI | Medium (misdiagnosis) | **Fixed** (see correction note in Bug 7 below) |
| 8 | Daemon wedges in infinite prewarm loop; watchdog + `doctor`'s fix don't catch it; `heal` does | CLI / daemon | **High** (live incident, reproduced twice) | **Fixed** (3 coordinated changes) |

---

## Bug 1 — `map` returns stale `embed_ms`/`retrieve_ms` on cached repeat queries

**Surface:** MCP `map`
**Severity:** Low — cosmetic/telemetry only, does not affect correctness of results.
**Status: Fixed.** `packages/pipeline/mcp_locate.py`'s cache-hit branch now overwrites `hit["timings"]` with `{"cached": True, "embed_ms": 0.0, "retrieve_ms": 0.0}` instead of replaying the stale values from the original call. Details: `docs/scubiee-bugs-root-cause-and-fix-plan.md`, Bug 1.

`map` caches full result payloads keyed by query text. On an exact repeat of the same query, every field in the response is identical **except** `elapsed_ms` — including the `timings.embed_ms` and `timings.retrieve_ms` sub-fields, which stay frozen at whatever they measured on the *first* call instead of reflecting the cache hit.

**Repro (reproduced 3x independently, including under concurrent load):**
```
Call 1 (fresh query): embed_ms=132.3  retrieve_ms=251.2  elapsed_ms=713.9
Call 2 (identical query, repeated): embed_ms=132.3  retrieve_ms=251.2  elapsed_ms=86.3
```
```
Two calls fired in true parallel with the same fresh query:
  Call A: embed_ms=114.0  retrieve_ms=234.7  elapsed_ms=661.3
  Call B: embed_ms=114.0  retrieve_ms=234.7  elapsed_ms=574.3
```

**Expected:** on a cache hit, `embed_ms`/`retrieve_ms` should either be re-measured, zeroed, or omitted — not replayed from the original call.
**Impact:** anyone using these two sub-fields to reason about live embedding/retrieval performance draws wrong conclusions whenever a query happens to hit the cache. `elapsed_ms` alone is trustworthy.

---

## Bug 2 — `pack_context` leaks an unwrapped internal error when `seed_symbol` is given without `seed_file`

**Surface:** MCP `pack_context`
**Severity:** Medium — breaks the error-contract consistency every other tool/path follows; leaks an internal symbol name.
**Status: Fixed.** `seed_file` now has a `""` default instead of being a required-with-no-default field (which is what let FastMCP/Pydantic reject the call before this project's own error handling ever ran), and `pack_impl` now explicitly checks for a missing `seed_file` at the top of its body and returns a clean `_err(...)` envelope. Details: `docs/scubiee-bugs-root-cause-and-fix-plan.md`, Bug 2.

**Repro:**
```
Call: pack_context(mode="lean", seed_symbol="some_symbol_with_no_file", query="<valid 25+ token query>")
Response: MCP tool error: Error executing tool pack_context: 1 validation error for pack_implArguments
seed_file
  Field required [type=missing, input_value={'mode': 'lean', 'seed_sy...}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/missing
```

Two problems in one:
1. It's a raw, unwrapped string, not the tool's normal `{"ok": false, "tool": "...", "error": "...", "hint": "..."}` JSON envelope that every other error path (including this same tool's "seed not found" case, see below) returns.
2. It leaks the private implementation function name `pack_implArguments` — internal to the public `pack_context` tool — directly to the caller.

**Contrast — the correctly-behaved sibling case, tested moments later:**
```
Call: pack_context(mode="lean", seed_file="packages/pipeline/totally_fake_nonexistent_module_xyz.py", query="...")
Response: {"ok":false,"error":"seed not found: file='...' symbol='' line=0",
           "hint":"Pass seed_file + seed_symbol or seed_line covering a function.", ...}
```
(That second case also confirms a *previously found* bug — `pack_context` accepting a nonexistent seed file as a valid hot heatmap card — is now fixed.)

**Expected:** a missing companion argument (`seed_file` required when `seed_symbol` is set) should return the same structured envelope, and should not name internal implementation symbols.

---

## Bug 3 — Stale AST-derived span past end-of-file, presented as fresh by `status`

**Surface:** MCP `expand_context`, `collect_hot_context`, cross-checked against `status`
**Severity:** High — a confidently-wrong answer, not an honest error. Worse than a crash because there's no signal telling the caller not to trust it.
**Status: the stale-span issue itself (3b) is open, deferred.** Root-causing it requires tracing the AST-bundle cache's symbol-boundary computation in `context_trace.py`, a larger and riskier surface than the other fixes in this batch — see `docs/scubiee-bugs-root-cause-and-fix-plan.md`'s closing section for the reasoning. The narrower `direction`-validation gap called out below (3a) **is fixed**: `expand_context` now rejects any `direction`/`intent` value outside the full real accepted vocabulary (including undocumented-but-functional aliases like `flow`/`refs`/`site`/`deps`/`dependents`, confirmed by tracing `context_trace.py`) with a clean structured error, instead of silently accepting anything.

While fuzzing `expand_context`'s `direction` parameter, a returned delta card pointed at a span that does not exist:

```
Call: expand_context(seed_file="packages/pipeline/mcp_locate.py", seed_symbol="ReadArgs", direction="not_a_real_direction")
Response delta includes: {"id":"packages/pipeline/mcp_locate.py::create_mcp",
                           "loc":"packages/pipeline/mcp_locate.py:3022-6070", ...}
```

Verified directly against the file on disk:
```
Get-Content packages/pipeline/mcp_locate.py | Measure-Object -Line
Lines: 5579
```

The reported end line (`6070`) is **491 lines past the actual end of the file**. Re-querying the identical symbol minutes later via a different tool produced yet another, different, still-wrong number:

```
Call: collect_hot_context(threshold=-5)
Response includes: {"id":"...::create_mcp", "loc":"packages/pipeline/mcp_locate.py:3022-6109", ...}
```

`6109` — now 530 lines past EOF, and different from the `6070` seen minutes earlier for the identical symbol in the identical file (inconsistent even with itself across calls). `create_mcp`'s start line (3022) is correct — it's a real factory function defining every MCP tool as a nested closure — but the file's actual last line (5579) sits mid-body of a nested closure inside `expand_context`'s own AST-miss handling, nowhere near either reported end line.

At the same moment, `status` reported:
```json
{"agent_ready":"yes","agent_ready_note":"Locate and index are ready; map/pack_context reflect current repo state.","sync_state":"ready"}
```

**Expected:** either the AST cache should be reconciled for this symbol (this looks like a stale AST cache entry that survived past a sync that otherwise reports itself complete — `map`/`pack_context` results elsewhere in the same session were consistently accurate, so this appears localized rather than systemic), or `status` should not claim full freshness while serving this span.
**Impact:** a caller following the tool's own "Native-Read top heatmap loc spans" instruction for this card would read past the end of the file, or get truncated/wrong content depending on how their read tool handles an out-of-range end line — with no warning that this particular symbol's boundary is unreliable.

**Related, lower-severity gap found alongside this:** `expand_context`'s `direction` parameter accepts any string at all (`"not_a_real_direction"` was silently accepted and echoed back) instead of being validated against the documented set (`callees|callers|effects|config|broad|all`). A typo in `direction=` fails silently instead of erroring.

---

## Bug 4 — `workspace(action="pin")` accepts nonexistent file paths

**Surface:** MCP `workspace`
**Severity:** Low — a pin is just a session hint, not something read from disk immediately, but it's an inconsistency across the same MCP surface.
**Status: Fixed.** `workspace_impl`'s pin branch now checks `(repo / p).is_file()` after the existing empty-path check and returns a clean `_err(...)` for a nonexistent path, matching `pack_context`'s pattern. Details: `docs/scubiee-bugs-root-cause-and-fix-plan.md`, Bug 4.

**Repro:**
```
Call: workspace(action="pin", path="packages/pipeline/this_file_absolutely_does_not_exist_anywhere.py")
Response: {"ok":true,"tool":"workspace","action":"pin",
           "pins":["packages/pipeline/this_file_absolutely_does_not_exist_anywhere.py"], ...}
```

No existence check at all. This is the same class of gap `pack_context`'s `seed_file` used to have before it was fixed (see Bug 2's contrast case) — but `workspace pin` wasn't covered by that same fix, so the two tools now disagree on whether a "repo-relative file path" argument needs to exist.

**What worked correctly on the same tool (for contrast):** empty `path` is rejected cleanly (`{"ok":false,"error":"path required for pin","hint":"workspace(action=pin, path='pkg/x.py')"}`); an invalid `action` value (including a deliberately alarming test value, `"delete_everything"`) is correctly rejected via proper Pydantic `Literal['show','pin','clear']` validation.

---

## Bug 5 — `expand`'s `max_chars` truncation budget is ignored for values `<= 0`

**Surface:** MCP `expand`
**Severity:** Low — no legitimate caller has a reason to pass `0` or negative, but it's a clean, 3-point-reproducible boundary bug.
**Status: Fixed.** `max_chars` now has `Field(ge=1, le=500_000, ...)`, so Pydantic rejects non-positive values before the truncation logic runs; the `max_chars or 50000` truthiness fallback (the actual root cause — `0` is falsy in Python) was removed since it's no longer reachable. Details: `docs/scubiee-bugs-root-cause-and-fix-plan.md`, Bug 5.

**Repro:**
```
expand(handle="packages/pipeline/mcp_locate.py::ReadArgs", max_chars=0)     -> full untruncated 1059-char body
expand(handle="packages/pipeline/mcp_locate.py::ReadArgs", max_chars=-100)  -> full untruncated 1059-char body (identical)
expand(handle="packages/pipeline/mcp_locate.py::ReadArgs", max_chars=50)    -> correctly truncated body, ends with "…"
```

`max_chars=50` truncates exactly as expected, isolating the bug precisely to the `<= 0` boundary. Likely root cause: a falsy-value check in the implementation (e.g. `if max_chars: apply_truncation()`, where `0` is falsy in Python and skips the branch; a negative number then reaches the same code path without a separate `>= 0` guard).

**What worked correctly on the same tool (for contrast):** a path-traversal-style handle (`../../../../etc/passwd::fake_symbol`) and an empty-string handle were both correctly rejected as `"unknown handle"` — handle resolution goes through a session-scoped registry, not raw filesystem path handling, so there's no actual traversal risk despite the string shape.

---

## Bug 6 — Windows console renders all Scubiee CLI Unicode output as mojibake

**Surface:** CLI (`scubiee status`, `scubiee map --help`, and likely every subcommand using box-drawing/checkmarks/em-dashes)
**Severity:** Medium — pure UX/readability, but affects effectively every Windows user in a default PowerShell window.
**Status: Fixed.** `cli_ui.py`'s `_init_windows_console()` (which already correctly did `stream.reconfigure(encoding="utf-8")` + `SetConsoleOutputCP(65001)`) is now called unconditionally on `win32` instead of being gated behind `sys.stdout.isatty() or sys.stderr.isatty()` — that gate was `False` for exactly the redirected/piped/automation scenarios this bug was found in. Verified functionally: `sys.stdout.encoding` flips from `cp1252` to `utf-8` after `init_terminal()` runs even with `isatty()==False`, and Unicode content written afterward (via Python's own file I/O, bypassing shell-redirection re-encoding) renders correctly. Details: `docs/scubiee-bugs-root-cause-and-fix-plan.md`, Bug 6.

**Repro:**
```
> scubiee status .
  Γ£ù Engine not running
ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
```
```
> scubiee map --help
  query   Expanded denser code-vocab query (symbols/paths/verbs; ~30û80 tokens)
```

Confirmed this is a console-rendering issue, not a source-encoding bug: `grep_search` against `packages/pipeline/__main__.py:2435` shows the correct source string with a real em-dash (`~30–80 tokens`), and piping the CLI's own output through `Out-File -Encoding utf8` and reading it back as UTF-8 produces perfectly clean text (`✗ Engine not running`, proper `─` rule characters). On this machine `[Console]::OutputEncoding` is `IBM437` (OEM codepage 437); the CLI emits UTF-8 bytes without first ensuring the console codepage matches, and PowerShell's default console then misrenders every non-ASCII character (checkmarks, box-drawing lines, em-dashes) — including inside argparse's own auto-generated `--help` text, not just custom-formatted output.

**Expected:** the CLI should set `sys.stdout`/console encoding to UTF-8 on startup on Windows (e.g. wrapping stdout with `encoding="utf-8"`, or calling the Windows API to set the console codepage), or fall back to plain ASCII-safe characters (`[x]`/`[OK]`/`---`) when it can't guarantee UTF-8 output, similar to how many other cross-platform CLIs handle this.

---

## Bug 7 — `scubiee map` reports `engine_down` for a server that is actually up and serving requests

**Surface:** CLI (`scubiee map`)
**Severity:** Medium — actively misdiagnoses the problem, which can send a user down the wrong troubleshooting path.
**Status: Fixed, with one correction.** `locate_cli.py`'s `cli_map` now surfaces the real exception message in `"error"` instead of overwriting it with the generic `"engine_down"` string (which is preserved as a separate `"reason"` field for repair-command selection). Verified with a mocked `SearchEngineError` — the real message now comes through correctly. **Correction on re-verification:** the "related finding" below about empty query reusing `engine_down` did not hold up — `cli_map(query="", ...)` was tested directly against the current source and already correctly returns `{"ok": false, "tool": "map", "error": "query required"}`. That specific repro appears to have conflated two different test runs from the original session; the primary `engine_down`-mislabeling defect is real and is what got fixed. Details: `docs/scubiee-bugs-root-cause-and-fix-plan.md`, Bug 7.

While the daemon was in the degraded state described in Bug 8, `scubiee map "<valid query>" .` consistently returned:
```json
{"ok":false,"tool":"map","error":"engine_down"}
```

At the same moment, `scubiee search "<same query>" .` against the identical repo succeeded, and the engine log showed the HTTP server actively returning `200`:
```
127.0.0.1 - "GET /health HTTP/1.1" 200 -
127.0.0.1 - "POST /v1/open HTTP/1.1" 200 -
127.0.0.1 - "GET /health HTTP/1.1" 200 -
127.0.0.1 - "POST /v1/search HTTP/1.1" 200 -
```

**Expected:** `map`'s own readiness gate is stricter than what the server actually needs to serve a request (most likely checking the same `warm_phase` state discussed in Bug 8, which doesn't accurately reflect real serving capability). It should either check the same signal `search` and `/health` use, or its error should distinguish "server unreachable" from "server reports itself still warming" — the current single `engine_down` message covers both and is wrong in this case.

**Related finding on the same command:** `scubiee map ""` (empty query) reuses this identical `engine_down` message instead of a clear "query is required" error. The MCP `map` tool, by contrast, correctly rejects an empty query with `"String should have at least 1 character"`. The CLI blames the engine for what is actually client-side bad input.

---

## Bug 8 — Daemon wedges in an infinite `warm_phase:prewarm` loop that its own watchdog does not detect, and `doctor`'s recommended fix does not resolve

**Surface:** CLI + live daemon + MCP transport (cross-cutting)
**Severity:** High. This was a **live incident observed during testing, reproduced twice in one session**, not a constructed edge case.
**Status: Fixed — three coordinated changes.** (1) `warm_autoload.py`'s `idle_busy_reason()` now passes `max_age_s=DEFAULT_PREWARM_MAX_AGE_S` into `read_phase()`, which is the actual root cause of the endless log spam — that call site never let the prewarm phase go stale no matter how long it sat stuck, so the busy-veto never expired. (2) A second, quieter instance of the identical bug pattern was found and fixed in `watchdog.py`'s own fallback staleness check. (3) `daemon.py`'s `_ensure_already_running` now does a cheap, non-blocking hang check before committing to the (previously up-to-120-second) blocking `open_repo(wait=True)` call, returning a fast, honest `hung=True` result instead. All three verified functionally by simulating a stale prewarm state directly — see `docs/scubiee-bugs-root-cause-and-fix-plan.md`, Bug 8, for the exact before/after numbers and why the originally-planned fixes for (2) and (3) were narrowed after tracing the surrounding code more closely (the watchdog's primary hang-check and `ensure_daemon`'s `force_if_hung=False` design were both more deliberate than first assumed).

### Timeline

1. Mid-session, the MCP connection dropped: `MCP tool call failed: Not connected`. At the same moment, `scubiee engine status` reported "Engine not running" — yet two `pythonw` processes were still alive at the OS process level.
2. Verified directly: `Test-NetConnection -ComputerName 127.0.0.1 -Port 8765` → `TcpTestSucceeded: False`. Process alive, port dead — a genuine zombie.
3. Ran `scubiee engine start`. It reported success (`{"ok": true, "started": true, "pid": 452, ...}`) and explicitly showed `watchdog.already_running: true, restart_count: 0, last_error: null` — **the watchdog process was alive the entire time this daemon was dead, and never noticed or restarted it.**
4. MCP did not reconnect on its own, even several minutes after the CLI confirmed the daemon was healthy again. (`scubiee heal`'s own hint later confirmed this needs an explicit action from the IDE: *"Reload Scubiee MCP in Cursor after heal."*)
5. Shortly after, the engine tipped into a second failure mode — the log filled with the identical line repeating for minutes with no state change:
   ```
   [engine] warm contract: action=busy clients=0 idle={'ok': True, 'action': 'busy', 'reason': 'warm_phase:prewarm'}
   [engine] warm contract: action=busy clients=0 idle={'ok': True, 'action': 'busy', 'reason': 'warm_phase:prewarm'}
   ... (repeats indefinitely, clients=0 throughout)
   ```
6. Ran `scubiee doctor .`. It correctly diagnosed the real problem with a specific, well-formed repair plan:
   ```json
   "binding": {"ok": false, "healthy": false, "matched": false, "bound_repo": null, "lock_pid": null,
               "repair": "scubiee engine ensure C:\\...\\context-engine  # reopen so soft search binds this workspace"},
   "repair_plan": [{"id": "bind_daemon", "kind": "safe", "detail": "scubiee engine ensure ..."}]
   ```
7. Ran the exact recommended repair: `scubiee engine ensure .`. **It hung for the full 60-second timeout with zero output.** The engine log kept repeating the identical stuck `warm_phase:prewarm` line throughout, completely unaffected by the command.
8. Ran `scubiee heal .` instead. This force-kills stuck processes before restarting, rather than trying to gently reuse the existing (wedged) one:
   ```
   [scubiee heal] sweeping engine daemons (+0.0s)
   [scubiee heal] restoring MCP pins (+2.3s)
   [scubiee heal] ensuring daemon (+2.9s)
   [scubiee heal] opening repo (+9.0s)
   [scubiee heal] reconnecting MCP tools (+9.3s)
   [scubiee heal] health check (+9.4s)
   [scubiee heal] done ok=True healthy=True (+9.7s)
   ```
   ```json
   "engine_sweep": {"ok": true, "killed": [8236, 9840, 10740], "remaining_pids": [], "still_healthy": false, "port": 8765}
   ```
   This worked — but had to force-kill **three** separate stuck PIDs first, confirming both the earlier `engine start` and the watchdog had left dead/wedged processes behind rather than cleaning them up.
9. The daemon wedged into the **exact same** `warm_phase:prewarm`/`clients=0` state again within about a minute of completely normal use (one `map` call, one `search` call). The second `search` call crashed outright:
   ```
   ConnectionResetError: [WinError 10054] An existing connection was forcibly closed by the remote host
   ```
   printed as a full raw Python traceback straight to the console, not a caught/clean error.
10. A second `scubiee heal .` recovered it again in under 9 seconds.

### Expected

- The watchdog should detect a daemon that is alive-but-unresponsive (port closed, or stuck in an unchanging `warm_phase`) and either restart it or at minimum flag `last_error`/increment `restart_count` — right now it silently reports `restart_count: 0, last_error: null` throughout an incident it should have caught.
- `doctor`'s repair plan should recommend `scubiee heal` (or something equally forceful) for this specific failure signature, not `scubiee engine ensure`, since `engine ensure` demonstrably does not resolve it (hangs for 60s+ against the wedged process instead of detecting and killing it).
- `search`'s CLI command should catch `ConnectionResetError`/connection-level exceptions from its HTTP client and surface a clean `{"ok": false, "error": "..."}` message instead of an unhandled traceback.

### Impact

A real user hitting this exact sequence — daemon silently wedges, MCP goes dark, they run `scubiee doctor` and follow its own recommended fix — would stay stuck, because the recommended fix doesn't work for this failure mode. Only `scubiee heal` reliably resolves it (confirmed twice, both times in well under 10 seconds), but it is not the tool the official diagnostics point to.

---

## What was tested and did *not* break (for completeness)

Recorded so this reads as a real audit, not just a list of failures:

- `map`: out-of-bounds `k` (`0`, `-5`, `999999`) and empty `query` are all rejected cleanly via proper Pydantic bounds/length validation, no crashes.
- A SQL-injection/XSS/log4shell/path-traversal payload string passed as a `map` query was safely treated as plain search text — no injection risk, no crash (though it did coincide with the single slowest `map` call observed in this whole review, `elapsed_ms: 8632` — possibly incidental to the specific embedding, not necessarily the payload shape).
- `pack_context`: a garbage `mode` value silently falls back to default `lean` behavior rather than crashing; `max_bodies=999999` is gracefully clamped to the number of cards actually available.
- `expand_context`: with no seed/node given at all, correctly falls back to the session's last-touched hot card per its documented behavior.
- `expand`: path-traversal-style and empty-string handles are both correctly rejected as `"unknown handle"` — no actual traversal risk since handle resolution is session-registry-based, not raw filesystem access.
- Concurrency: five parallel `gate`/`status` calls and two genuinely-parallel identical `map` calls all returned consistent, uncorrupted results with the same session id throughout — no race-condition crashes observed.
- `scubiee doctor .` is otherwise strong: thorough, well-structured, and it proactively caught a real, independent install-drift issue on its own (`install.binaries_match: false` — the invoked `scubiee` binary differs from the one the active Python environment would use) with a specific, correct hint about fixing PATH.
- `scubiee heal .` is robust and effective at what it does — reliable, fast (<10s both times it was needed), and it correctly restores MCP config pins and IDE tool registrations alongside the daemon restart.
- Bad-path input handling is solid: `scubiee map "test" nonexistent_repo_path_xyz` returns a clear `"not a directory: ..."` error.
