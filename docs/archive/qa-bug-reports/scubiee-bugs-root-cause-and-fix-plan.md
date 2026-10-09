# Scubiee bugs — root cause analysis and fix plan

Companion to `docs/scubiee-bugs-found.md` (the symptom-level bug list). This file traces each bug to its exact source location and lays out the fix for each, in the order they'll be applied. Fixes are applied one at a time, each followed by a targeted test before moving to the next.

Repo: this repo (`context-engine`), version under test `scubiee 0.3.112`.

---

## Fix order and rationale

Ordered from simplest/most isolated to most complex/cross-cutting, so early fixes build confidence before tackling the harder ones:

1. Bug 5 — `expand` max_chars boundary (one field annotation)
2. Bug 4 — `workspace pin` missing existence check (few lines)
3. Bug 1 — `map` stale cached timings (few lines)
4. Bug 2 — `pack_context` raw error leak (field default + guard)
5. Bug 3a — `expand_context` direction not validated (type annotation)
6. Bug 6 — Windows console mojibake (remove a TTY gate)
7. Bug 7 — `map` engine_down mislabeling (error message passthrough)
8. Bug 8 — daemon wedge / watchdog blind spot / doctor's fix ineffective (three coordinated changes — most complex, done last)
9. Bug 3b — stale AST span past EOF (deferred — see note at the end)

---

## Bug 5 — `expand`'s `max_chars` ignored for `<= 0`

**File:** `packages/pipeline/mcp_locate.py`
**Root cause, line ~3944-3959** (in `expand_impl`):

```python
def expand_impl(
    handle: Annotated[str, Field(description="Session span handle from read/recall.")],
    max_chars: Annotated[int, Field(description="Body budget.")] = 50000,
    ...
):
    ...
    cap = max(200, min(int(max_chars or 50000), _FOCUS_CHAR_CEILING))
```

Two things wrong: (a) `max_chars` has no `ge=`/`le=` bound, unlike every sibling `max_chars` field in this file (all of which use `Field(default, ge=200, le=...)`). (b) `max_chars or 50000` uses Python truthiness — `0` is falsy, so it's silently replaced with the default `50000` instead of being treated as an explicit (if useless) value.

**Fix:** add matching bounds to the field (`ge=1, le=500_000` — using `1` not `200` since some callers may legitimately want a very small peek, and the existing `max(200, ...)` clamp already provides a sane floor for the *effective* value without rejecting small requests outright), and drop the `or 50000` fallback since Pydantic's `ge=` bound will now reject non-positive values before they ever reach this line.

---

## Bug 4 — `workspace(action="pin")` accepts nonexistent file paths

**File:** `packages/pipeline/mcp_locate.py`
**Root cause, line ~4829-4843** (in `workspace_impl`):

```python
if args.action == "pin":
    p = (args.path or "").replace("\\", "/").strip()
    if not p:
        return _err("workspace", "path required for pin", hint="workspace(action=pin, path='pkg/x.py')")
    ...
    return _dumps({"ok": True, "tool": "workspace", "action": "pin", "path": p, "pins": ...})
```

Only checks the string is non-empty. Never checks the path resolves to a real file under `repo`.

**Fix:** after the empty-check, resolve `repo / p` and confirm it's an existing file before proceeding; return a clean `_err` (matching `pack_context`'s "seed not found" pattern) if it doesn't exist.

---

## Bug 1 — `map` returns stale `embed_ms`/`retrieve_ms` on cached repeat queries

**File:** `packages/pipeline/mcp_locate.py`
**Root cause, line ~4377-4384:**

```python
hit = get_map_cached(repo=str(repo), query=args.query, fingerprint="soft_v1")
if hit is not None and hit.get("dense") is True:
    hit["elapsed_ms"] = round((_time.perf_counter() - _map_t0) * 1000, 1)
    ...
```

Only `hit["elapsed_ms"]` is refreshed on a cache hit. `hit["timings"]` (containing `embed_ms`/`retrieve_ms` from the *original* call) is returned unmodified.

**Fix:** on a cache hit, overwrite `hit["timings"]` with a value that honestly reflects reality — `{"cached": True, "embed_ms": 0.0, "retrieve_ms": 0.0}` — rather than replaying stale numbers. This keeps the field shape stable for any caller reading `timings.embed_ms` while making it obvious the number is not a fresh measurement.

---

## Bug 2 — `pack_context` leaks a raw internal error when `seed_symbol` is given without `seed_file`

**File:** `packages/pipeline/mcp_locate.py`
**Root cause, line ~5673-5690** (in `_make_pack_impl`'s inner `pack_impl`):

```python
def pack_impl(
    query: Annotated[str, ...],
    seed_file: Annotated[str, Field(description="Seed file path relative to repo.")],
    seed_symbol: Annotated[str, Field(description="Seed symbol...")] = "",
    ...
):
```

`seed_file` has no default value. When a caller supplies `seed_symbol` but omits `seed_file`, FastMCP's/Pydantic's own argument-binding validation rejects the call *before* `pack_impl`'s body — and therefore before this codebase's `_err(...)` helper — ever runs. The registration wrapper around every tool (`_tool()`'s `_wrapped`, line ~3044) has a `try/finally` with no `except`, so nothing in this codebase catches or reformats that validation error either; it propagates as FastMCP's raw default error text, which is where the leaked internal name `pack_implArguments` (FastMCP's auto-generated Pydantic model name for this function's parameters) comes from.

**Fix:** give `seed_file` a default of `""` (matching the optional-field style already used for `seed_symbol` and every `seed2_*`/`seed3_*` field in the same function), and add an explicit check at the top of `pack_impl`'s body: if `seed_symbol` is set but `seed_file` is empty, return a clean `_err("pack_context", "seed_file required when seed_symbol is set", hint="Pass seed_file + seed_symbol, or seed_file alone.")`. This moves the validation into code this project controls, producing the same clean envelope as every other error path.

---

## Bug 3a — `expand_context`'s `direction` parameter accepts any string

**File:** `packages/pipeline/mcp_locate.py`
**Root cause, line ~5509-5516:**

```python
direction: Annotated[
    str,
    Field(
        description="callees|callers|effects|config|broad|all (default all). ..."
    ),
] = "all",
```

Plain `str` type, undocumented in the tool description as accepting anything beyond the six listed values.

**Correction after tracing the consumer (`context_trace.py`):** a plain `Literal["callees", "callers", "effects", "config", "broad", "all"]` would be the *wrong* fix. The actual engine (`context_trace.py` lines ~2752-3392) accepts a materially larger alias vocabulary than the six documented values — `deps` (alias for `callees`), `flow` (alias for `callees`), `refs`/`dependents` (aliases for `callers`), `site` (alias for `effects`) all work today and are matched throughout the filtering/ordering logic. A strict `Literal` on just the six documented values would silently break these currently-functional aliases — trading one bug (accepts anything) for a worse one (rejects valid input). The underlying function already degrades reasonably for genuinely unrecognized strings (line ~2752: `d = (direction or "all").lower().strip() or "all"`, with unmatched values falling through to permissive `else` branches rather than crashing) — so the *actual* problem is narrower than initially scoped: only truly-nonsense strings should be rejected, not the real alias set.

**Fix:** validate at the MCP boundary against the full real accepted set (`callees`, `callers`, `effects`, `config`, `broad`, `all`, `deps`, `flow`, `refs`, `site`, `dependents`) case-insensitively, returning a clean `_err` for anything outside it — rather than a `Literal` type annotation, which can't express "this alias list, case-insensitively" as cleanly and would need to enumerate the exact same set anyway. This closes the "any garbage string is silently accepted" gap without breaking any alias that currently works.

---

## Bug 6 — Windows console renders CLI Unicode as mojibake

**File:** `packages/pipeline/cli_ui.py`
**Root cause, line ~56-90:**

```python
def _init_windows_console() -> None:
    """UTF-8 output so block-letter banner renders on cmd/PowerShell."""
    for stream in (sys.stdout, sys.stderr):
        ...
        stream.reconfigure(encoding="utf-8")
    ...
    ctypes.windll.kernel32.SetConsoleOutputCP(65001)

def init_terminal() -> None:
    ...
    any_tty = sys.stdout.isatty() or sys.stderr.isatty()
    if any_tty:
        ...
        if sys.platform == "win32":
            _init_windows_console()
```

The fix logic already exists and is correct — `stream.reconfigure(encoding="utf-8")` plus `SetConsoleOutputCP(65001)`. But it's gated behind `any_tty`, which is `False` whenever stdout/stderr is redirected or piped (a very common case: automation, `| Out-String`, captured terminal sessions, CI logs). `SetConsoleOutputCP` sets the process's console codepage — a property of the console the process is attached to, not of whether a particular stream happens to be a TTY — so there's no correctness reason to gate it on `any_tty`. `stream.reconfigure()` is similarly safe to call on a redirected stream.

**Fix:** call `_init_windows_console()` unconditionally on `win32` (outside the `if any_tty:` block), keeping the *rest* of terminal init (colors, ANSI mode, banners) gated on `any_tty` as before since those genuinely only make sense for an interactive terminal.

---

## Bug 7 — `scubiee map` reports `engine_down` for a server that is actually up

**File:** `packages/pipeline/locate_cli.py`
**Root cause, line ~130-162** (inside the `map` command's `except SearchEngineError` handler):

```python
except SearchEngineError as exc:
    msg = str(exc)
    if wait_s > 0 and not local and "dense_embed_required" in msg and time.monotonic() < deadline:
        time.sleep(1.0)
        continue
    if local or "dense_embed_required" in msg:
        return {"ok": False, "tool": "map", "error": msg, ...}
    return {
        "ok": False,
        "tool": "map",
        "error": "engine_down",
        "detail": msg,
        "repair": ["scubiee engine ensure .", "scubiee heal"],
        ...
    }
```

Any `SearchEngineError` that isn't specifically about `dense_embed_required` gets its real message demoted to a `"detail"` field and replaced at the top level with the generic literal `"engine_down"` — even for something as unrelated as a single transient connection reset. This directly caused the observed contradiction: `search` succeeded and `/health` returned 200 at the same moment `map` reported `engine_down`, because `map`'s classification isn't actually checking server health — it's just relabeling whatever exception text `search_repo()` happened to raise.

**Fix:** stop overwriting the real message. Put the actual exception text in `"error"`, and move `"engine_down"` to a separate `"reason"` field that's only used as a coarse hint for which repair commands to suggest — not as the primary error the caller sees. This preserves the existing `repair` suggestions (still useful much of the time) while no longer asserting something false about the server's state.

**Correction on re-verification:** the empty-query claim in the original bug report (`docs/scubiee-bugs-found.md` Bug 7) does not hold up — `cli_map(query="", ...)` was tested directly against the current source and correctly returns `{"ok": false, "tool": "map", "error": "query required"}`, not `engine_down`. That part of the original write-up conflated two separate test runs from the original session (the empty-query test and a `--k -5` test). The `engine_down`-mislabeling defect itself is real and still fixed above; only the specific empty-query repro claim is retracted. `docs/scubiee-bugs-found.md` will be annotated to reflect this correction rather than silently edited, since the original bug list should stay an honest record of what was actually observed at the time.

---

## Bug 8 — daemon wedges in an infinite `warm_phase:prewarm` loop; watchdog doesn't catch it; `doctor`'s recommended fix doesn't resolve it

Three separate, coordinated root causes, each with its own fix. This is the most invasive change, so it's done last and tested most carefully.

### 8a — the busy/prewarm state never expires on the code path that logs it

**File:** `packages/pipeline/warm_autoload.py`
**Root cause, line ~217-221:**

```python
def idle_busy_reason() -> str | None:
    """Non-None ⇒ disconnect idle sweeper must not stop the engine."""
    snap = read_phase()
    if snap.get("phase") == PHASE_PREWARM:
        return "warm_phase:prewarm"
    return None
```

`read_phase()` is called with no `max_age_s` — so the `stale` flag `read_phase` is capable of setting (see its signature, `read_phase(*, max_age_s: float | None = None)`) never gets computed on this path, no matter how old the snapshot is. Compare `hung_prewarm_should_abort()` elsewhere in the same file, which correctly passes `max_age_s=DEFAULT_PREWARM_MAX_AGE_S` (45.0s) and *does* expire stale prewarm state. `idle_busy_reason()` is the function whose non-`None` return is what makes `server.py`'s idle-sweep loop print `[engine] warm contract: action=busy ... reason: warm_phase:prewarm` on every tick, forever, once prewarm gets stuck.

**Fix:** pass `max_age_s=DEFAULT_PREWARM_MAX_AGE_S` into the `read_phase()` call, and check the returned `stale` flag — if the phase is stale, treat it as no longer a valid "busy" reason (return `None`), which both stops the endless log spam and, more importantly, lets the idle sweeper actually attempt recovery instead of being vetoed by a phase that's been stuck for minutes.

### 8b — a second, quieter instance of 8a's bug inside the watchdog's own restart-decision logic

**File:** `packages/pipeline/watchdog.py`
**Correction after closer tracing:** the watchdog's restart-trigger design is actually sound on inspection — it already calls `hung_prewarm_should_abort(max_age_s=...)` correctly (line ~470) even when `/health` succeeds, and when that returns `True` it force-sets the failure counter to the restart threshold immediately (`fails = fail_limit`) rather than waiting for the normal backoff. So the watchdog was not, as first suspected, unconditionally trusting `/health` — the hang-check does run.

What tracing did find is a **second occurrence of exactly 8a's bug pattern**, a few lines further down the same function: a fallback re-check calls `read_phase()` with no `max_age_s` (line ~508), so if `stale_prewarm` was somehow still `False` going into that block, this fallback couldn't add any new staleness signal either — it would always see `stale=None`/unset from `read_phase()`'s default. Given 8a's fix means `hung_prewarm_should_abort()` (which feeds `stale_prewarm` earlier in the same function) now works correctly, this fallback is largely redundant in practice — but it's the same bug and should be fixed for consistency rather than left as a second copy of the same defect.

**Fix:** pass `max_age_s=DEFAULT_PREWARM_MAX_AGE_S` into that `read_phase()` call too. Also tightened the log message on the `_health_ok()`-but-hung branch to describe what actually happens (falls through toward the restart-eligible path below) rather than implying an abort happens right there, since the prior wording made it easy to misread this branch as a dead end.

### 8c — `ensure_daemon`'s "already running" path has no way to detect or kill a wedged process

**File:** `packages/pipeline/daemon.py`
**Root cause, line ~111-120:**

```python
def is_running() -> bool:
    existing = _read_lock_pid()
    if existing is not None and _pid_alive(existing):
        return True
    return EngineClient().healthy()
```

Satisfied by a live lock PID alone, with no health check at all in that branch, or by a passing `/health`. Neither condition verifies the process is actually making progress. `ensure_daemon`'s "already running" branch (`_ensure_already_running`) then calls `client.open_repo(..., wait=True)` with up to a 120-second timeout against whatever is already there — with no code path to detect "alive but wedged" and escalate to a kill, especially since the CLI's `map` command calls `ensure_daemon(root, force_if_hung=False)`, explicitly disabling the one force-kill branch that does exist (which itself is only reachable when `is_running()` is `False` — never true for a process that's merely wedged, not dead).

**Fix, corrected after reading `ensure_daemon`'s full call chain:** the original plan (route straight into a force-restart whenever hung, ignoring `force_if_hung`) turned out to conflict with a deliberate, documented design choice one call frame up — `ensure_daemon`'s own comment: *"MCP request paths should pass force_if_hung=False — force_restart can block for minutes and looked like agent 'hangs' in A/B runs."* Overriding that from inside `_ensure_already_running` would silently reintroduce the exact problem that comment exists to avoid, for every caller, not just the ones stuck on a wedge.

The corrected fix is narrower and doesn't touch that tradeoff: in `_ensure_already_running`, when `open_wait=True`, do the same cheap, non-network `hung_prewarm_should_abort()` check *before* calling the blocking `client.open_repo(..., wait=True)`. If hung, return immediately with `{"ok": False, "hung": True, "error": "warm_phase wedged (prewarm stale)", "hint": "scubiee heal"}` instead of blocking for up to 120 seconds waiting on a daemon that was never going to finish warming. This fixes the actual observed symptom (a long, silent hang with no useful output) without force-killing anything or changing who is allowed to trigger a restart — the caller still decides what to do with a fast, honest "hung" answer, same as the existing `force_if_hung=False` path already returns for the fully-dead case a few lines below in `ensure_daemon` itself.

### Testing note for Bug 8

This is the one fix in this plan that touches live daemon lifecycle code. Testing will be done by: (1) confirming normal `scubiee engine start`/`status`/`stop` still behave correctly on a clean start, (2) attempting to reproduce the original wedge conditions closely enough to confirm the watchdog or `ensure` now recovers within a reasonable time instead of hanging, and (3) confirming `scubiee heal` still works as an unconditional fallback regardless (its unrelated-and-already-correct hard-kill-first design is not being changed).

---

## Bug 3b — stale AST-derived span past EOF for `create_mcp` (deferred)

Not root-caused to a specific line yet. Unlike the other bugs, this one requires tracing the AST-bundle cache's symbol-boundary computation and cache-invalidation logic in `context_trace.py`/`graphify`-adjacent code, which is a larger surface than the other seven fixes and carries higher risk of a subtle regression in span accuracy for other symbols if changed carelessly. Given the other eight fixes already meaningfully improve correctness and stability, this one will be revisited after the rest are shipped and verified, as a follow-up investigation rather than blocking this fix run. It will remain documented as a known open issue in `docs/scubiee-bugs-found.md`.
