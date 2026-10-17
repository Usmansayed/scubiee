# Scubiee CLI UX audit — command-combination findings

_Audited on Windows against installed scubiee 0.3.149. Focus: the class of issue
where a plausible user command combination produces a bad experience — a raw
Python traceback, a wrong exit code, a leaked internal error, a hang, or a
confusing message. Destructive-command guards and most error paths are solid;
the findings below are the exceptions worth fixing._

## Summary

| # | Severity | Issue | Root cause | Status |
|---|---|---|---|---|
| 1 | **HIGH** | Any command that raises dumps a **raw Python traceback** at the user | `main()` dispatcher has no top-level try/except | open (systemic) |
| 2 | MED | `map` CLI with engine down: **exit 0 on failure + raw `RuntimeError`/`WinError` leak + no auto-start** | `cmd_map` exit-code heuristic + no daemon-ensure | open |
| 3 | MED | `map --names foo "trailing query"` **hangs** | config+args combo blocks on engine call with no timeout | open |
| 4 | LOW | `map` CLI docstring says "four configs find\|focus\|related\|graph" | stale since v0.3.142 (two configs) | open |

Confirmed-good (no fix needed): argparse flag errors (exit 2 + usage), `-h` on
every subcommand, destructive guards (`wipe`/`wipe --all` refuse without
`--confirm`), and `search`/`sync`/`status`/`gate`/`dashboard` degrade or
auto-start cleanly when the engine is down.

---

## Finding #1 — No top-level exception handler → raw tracebacks (HIGH, systemic)

**This is the root cause of the whole class the user keeps hitting** (the `init
C:\typo` traceback was one instance; it was patched inside `cmd_init`, but the
underlying gap is systemic).

`packages/pipeline/__main__.py`, end of `main()`:

```python
    return int(args.func(args))   # <-- no try/except around the dispatch
```

Any of the 41 `cmd_*` handlers that raises an uncaught exception dumps a full
Python traceback at the user. Per-command catches are whack-a-mole; several
commands still leak.

**Reproduced (installed 0.3.149):**
- `scubiee sync C:\nope\xyz` → `Traceback … FileNotFoundError: not a directory`
- `scubiee never-index C:\nope\xyz` → same traceback
- (`scubiee init C:\nope\xyz` → same class; already patched command-locally)

All three come from `resolve_project(root)` raising `FileNotFoundError` on a path
that doesn't exist. Any future handler that raises will do the same.

**Fix (systemic, one place):** wrap the dispatch in `main()`:

```python
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\n  Cancelled.", file=sys.stderr)
        return 130
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        cmd = getattr(args, "cmd", "command")
        msg = str(exc) or type(exc).__name__
        print(f"[scubiee] {cmd} failed: {msg}", file=sys.stderr)
        if not sys.stdout.isatty():
            print(json.dumps({"ok": False, "command": cmd, "error": msg},
                             indent=2, default=str))
        if os.environ.get("CTX_DEBUG") or os.environ.get("SCUBIEE_DEBUG"):
            raise  # full traceback only when the user opts in
        return 1
```

This gives every command a clean error + exit 1 by default, with the full
traceback still available via `CTX_DEBUG=1` for debugging. It does not replace
good per-command messages (e.g. `init`'s "not a directory") — it's the safety net
beneath them.

---

## Finding #2 — `map` CLI fails ugly when the engine is down (MED)

Every other engine-dependent command either **auto-starts** the engine
(`search`) or **degrades cleanly** (`sync`, `status`, `gate`, `dashboard`). The
`map` CLI alone does neither.

**Reproduced:** engine stopped, then `scubiee map --config find "where is auth" <repo>`:
```
map find failed: RuntimeError: engine /v1/search failed: URLError: <urlopen error [WinError 10061] ...>
```
- **Exit code is 0** on a clear failure.
- The message leaks `RuntimeError` / `URLError` / `WinError 10061` — raw
  internals, not a user action.

Root cause, `cmd_map` in `__main__.py`:
```python
    text = tool_map(call)
    ...
    return 0 if not str(text).startswith("error:") else 1
```
The engine-down message starts with `"map find failed"`, not `"error:"`, so the
heuristic returns **0**. And `cmd_map` never ensures the daemon (unlike the
`search`/`sync` paths that go through the daemon-ensuring client).

**Fix:**
1. Ensure the daemon before the call (match `search`: `ensure_daemon(repo)` /
   warm wait), **or** detect the engine-down message and print a friendly line:
   `engine not running — run 'scubiee engine start' (or just retry; your IDE's
   MCP client keeps it warm)`.
2. Fix the exit code: return non-zero whenever the text indicates a failure
   (`failed:` / `error:` / `could not`), not only when it starts with `error:`.

---

## Finding #3 — `map --names foo "trailing query"` hangs (MED)

**Reproduced:** `scubiee map --config focus --names foo "and a query too"` hung
(killed at 40s). Mixing `--names` (focus) with a trailing positional query puts
`tool_map` into a path that calls the engine and blocks without a short timeout
when the engine isn't immediately answering.

A plausible user mistake must never hang. **Fix:** bound the engine call in the
`map` CLI with a timeout (e.g. 10–15s) so it fails fast with Finding #2's
friendly message; optionally warn when both `--names` and a positional `query`
are given for `focus` (ambiguous — focus uses names, find uses query).

---

## Finding #4 — stale `map` CLI docstring (LOW)

`cmd_map` docstring: *"One tool, four configs: find | focus | related | graph."*
The shipped surface is **two configs (find | focus)** since v0.3.142. Harmless at
runtime but drifts from reality. **Fix:** update to "two configs: find | focus".

---

## What is already good (verified, no change needed)

- **Argparse mistakes** — bad flag/value/subcommand/action (`map --k abc`,
  `connect cursor` positional, `setup --frobnicate`, `engine frobnicate`,
  `--unknown`) all exit 2 with a usage message. Clean.
- **`-h` / `--help`** on every subcommand exits 0 with usage.
- **Destructive guards** — `wipe` and `wipe --all` without `--confirm` refuse
  with `confirm_required` (exit 2); non-TTY never deletes without the flag.
- **Engine-down resilience** — `search` auto-starts the engine; `sync` degrades
  to no-op; `status`/`gate` are local-only; `dashboard --status` reports cleanly.
- **Too-broad path guard** — `init`/`never-index` on `C:\`, home, Documents,
  `..\..\..` refuse with `path_too_broad` (the traceback only appears on a
  *deep nonexistent* path that reaches `resolve_project`, which Finding #1 covers).

---

## Recommended fix order

1. **#1 first** — the top-level try/except is one small change that eliminates the
   entire raw-traceback class across all 41 commands (and makes any future
   command safe by default). Highest leverage.
2. **#2 + #3** — the `map` CLI engine-down behavior (exit code, friendly message,
   bounded timeout). Same file, related.
3. **#4** — docstring one-liner, fold into the #2/#3 change.

All four are small, localized to `__main__.py` (+ the map call path), and
testable with the probes used in this audit.
