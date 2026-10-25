# Scubiee CLI Command-Matrix Audit

_Run on Windows (DirectML) against installed scubiee 0.3.150. Goal: exercise
every subcommand, flag combination, and error state, plus a live `upgrade` and
clean setup, looking for tracebacks, wrong exit codes, leaked internal errors,
and hangs. This complements `scubiee-cli-ux-findings.md` (the four UX issues
fixed in 0.3.150); this doc is the exhaustive pass that followed those fixes._

## Result summary

~55 command forms exercised across six groups. **Zero tracebacks and zero hangs
observed.** All error states returned clean exit codes (1 or 2) with
human-readable messages, no raw Python stack traces. One real bug was found and
root-caused: `scubiee upgrade` reported failure on every Windows upgrade.

| Group | Forms tested | Tracebacks | Hangs | Bad exit codes | Verdict |
|---|---|---|---|---|---|
| Info / read-only (`--help`, `-h` per subcommand, `version`, `status`, `gate`, `dashboard`) | ~14 | 0 | 0 | 0 | PASS |
| Repo lifecycle (`init`, `sync`, `search`, `remove`, bad paths, never-indexed) | ~12 | 0 | 0 | 0 | PASS |
| `map` (warm engine + engine-down + flag combos) | ~8 | 0 | 0 | 0 | PASS |
| Tool wiring (`connect`/`disconnect` all tools, `certify`, aliases) | ~9 | 0 | 0 | 0 | PASS |
| Engine control (`pause`/`resume`, daemon restart, health) | ~6 | 0 | 0 | 0 | PASS |
| Maintenance (`migrate`, `unlock-tool`, `wipe` guards, `upgrade --check`, `upgrade`) | ~6 | 0 | 0 | 0 (after fix) | PASS\* |

\* `upgrade` live-apply exposed the bug below; fixed and re-verified.

## Confirmed-good behaviors

- argparse flag errors → exit 2 with usage, no traceback.
- `-h`/`--help` on every subcommand renders cleanly.
- Destructive guards: `wipe` and `wipe --all` refuse without `--confirm`.
- `search` / `sync` / `status` / `gate` / `dashboard` degrade or auto-start
  cleanly when the engine is down.
- `map` with engine down now fails fast with a readable message (0.3.150 fix),
  no exit-0-on-failure and no `WinError` leak.
- `--windsurf` resolving to "Devin Desktop" is **intentional**
  (`tool_registry.py` `SLUG_ALIASES = {"windsurf": "devin-desktop"}`).
- `unlock-tool` renames the uv tool dir aside, leaving scubiee temporarily
  uninstalled, **documented behavior**, reinstall afterward. Not a bug.

## Finding: `scubiee upgrade` reports failure on every Windows upgrade

**Severity: HIGH** (every Windows user who runs `scubiee upgrade` sees a scary
"upgrade failed" with an `unlock-tool` hint, even though the upgrade succeeded).

### Repro

Live-ran `scubiee upgrade` 0.3.147 → 0.3.150. Command exited **1** with
`package_upgrade_failed` and the hint "Quit Cursor MCP, run `scubiee
unlock-tool`". But the package had actually upgraded:

- uv stderr showed `- scubiee==0.3.147` / `+ scubiee==0.3.150`.
- `importlib.metadata.version("scubiee")` returned `0.3.150`.

### Root cause

`swap_package` in `packages/pipeline/upgrade_supervisor.py` judged success
solely by the installer **exit code**. The running `scubiee.exe` holds a lock on
its own entrypoint shim, so uv swaps the package cleanly but fails the final
step, copying the new launcher over the locked one:

```
error: Failed to install entrypoint
  Caused by: failed to copy ...\uv\tools\scubiee\Scripts\scubiee.exe
  to C:\Users\...\.local\bin\scubiee.exe: being used by another process (os error 32)
```

That is a cosmetic rebind failure (the shim re-points on next launch), not a
package-upgrade failure, but the exit-code-only check turned it into a hard
failure, and `do_upgrade` surfaced it as `package_upgrade_failed`.

### Fix

`swap_package` now **verifies success by installed version**, not just exit
code:

1. The caller passes the resolved `target_version` into `swap_package`.
2. When an install command exits non-zero, `_verified_ok` checks whether the
   failure was only the self-locked entrypoint copy (`_entrypoint_copy_failed_only`:
   "failed to install entrypoint" + "os error 32"/"being used by another
   process") **and** `installed_version() == target_version`. If so it returns
   `ok: True` with `shim_rebind_deferred: True` and a plain-language note.
3. A last-chance verify at the end succeeds if the package is demonstrably on
   target regardless of why the command reported non-zero (installed version is
   ground truth).
4. Genuine failures (version did not move) still return
   `package_upgrade_failed` with the unlock-tool hint.

The CLI (`cmd_upgrade`) prints a friendly one-liner when the shim rebind was
deferred: the launcher re-points automatically on next run, no action needed.

### Tests

`tests/test_upgrade_supervisor.py` adds four cases:

- shim locked + version bumped → `ok: True`, `shim_rebind_deferred`.
- version unchanged → still `package_upgrade_failed`.
- no `target_version` passed → exit-code semantics preserved (failure).
- package on target despite unrelated non-zero exit → last-chance verify
  succeeds (version is ground truth).

All 39 tests across `test_upgrade_supervisor`, `test_upgrade_scenarios`,
`test_upgrade_cli_integration`, and `test_cli_ux_hardening` pass.

## Still owed

- Clean-machine first-run `setup` end-to-end test (deprioritized when the
  upgrade bug surfaced).
- This fix ships in **0.3.151**: 0.3.150 still contains the broken upgrade, so
  users on 0.3.150 who run `scubiee upgrade` to a later version will still see
  the false failure until they are on a build that carries this fix.
