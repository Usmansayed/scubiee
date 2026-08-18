# Future work — Context Engine production backlog

**Date:** 2026-08-18  
**Worktree:** `.worktrees/production-certification`  
**Status:** living backlog  
**Source:** live reindex fix, chaos harness, operator/MCP use

P0 items below were patched in this worktree (2026-08-18 reliability pass). Remaining items are still future work.

---

## P0 — must fix before any “production” claim

### 1. Search queries become repo paths — **FIXED (this worktree)**

CLI used to parse `search . "test query"` as query=`.` and path=`test query`, then `resolve_project` mkdir’d that folder. Now: directory-first heuristic; `write_id_file` requires an existing dir; nested folders inherit the parent id.json without writing a new one; HTTP client ignores non-directory `path` values.

### 2. Project ID churn for one repo — **PARTIALLY FIXED**

Nested non-git folders no longer mint a new `ce_…` or get their own `id.json`. Git worktree family still shares `git_common_dir` by design. Leftover stores under `~/.context-engine/projects/` from earlier runs still need a one-time cleanup.

### 3. MCP status vs HTTP health contradiction — **FIXED (this worktree)**

`status` now checks `/health` first. A slow `/v1/status` timeout can no longer report `healthy: true` and `unreachable` together.

### 4. Engine uptime / idle stop vs MCP — **IMPROVED (this worktree)**

MCP `main()` and `_client_for` call `ensure_daemon(..., force_if_hung=True)`. Unix `stop_daemon` now SIGTERM then SIGKILL / killpg. Idle 120s and LaunchAgent KeepAlive are unchanged — still be careful on a MacBook (`CTX_WATCHDOG=0` / skip `ctx setup` for a first trial).

---

## P1 — correctness and operator trust

### 5. CLI `search` vs warm HTTP search

With the engine down (or CLI local path), `ctx search` returned unrelated files and printed “large drift — NOT auto-reindexing”. `/v1/search` was correct after live upserts.

- Align CLI with daemon when up; fail fast or label local fallback when down.

### 6. Large dump / folder replace does not auto-catch-up

By design: `choose_strategy` → `full` at ≥50% corpus change; incremental hard-cap 80 files (`CTX_INCREMENTAL_MAX_TOUCH`); `CTX_ALLOW_BG_FULL` default off.

- Operator-facing message + one documented command (`ctx index . --force`).
- Optional: safe background full reindex with RAM/CPU gates (do **not** re-enable unbounded auto-full).

### 7. `ctx init` missing `--fast` / `--roots`

`init --fast --roots src` is unrecognized. Fast index only via `index` / `register`.

- Add flags to `init` or document the two-step flow.

### 8. `doctor` exit code 1 when only the daemon is unbound

Index usable, manifest OK, still exit 1 because `binding.ok: false`.

- Separate “index broken” vs “start the engine”.

### 9. `pip uninstall` leaves a live daemon

Uninstall succeeded while `:8765` kept serving.

- Docs + `setup`/`uninstall` hook: `engine stop` first.

---

## P2 — indexing resilience (dump / replace / libraries)

Already skipped: `node_modules`, `.venv`, `venv`, `site-packages`, `dist`, `build`, `testdata/`, `.git`, `.cursor`, vendor, etc.

Still future work:

### 10. Dumping another project’s source at repo root

A tree like `frontend-mcp/src/…` **outside** `testdata/` looks like first-party code and will be queued for embed. Testdata skip exists because a frontend-mcp **copy** already hung indexing.

- Heuristics or an allowlist of index roots (beyond fast-mode).
- “Foreign tree” detector (nested `.git`, lockfiles at dump root).

### 11. Merkle closed-universe vs mass add after folder replace

Replacing a folder’s contents is mass add+remove → `full` → no auto embed. Search goes stale until force index.

- Catch-up path that is capped and junk-filtered, not “index the world”.

### 12. Junk-filter holes

Skip lists are substring/dir-name based. Not skipped: `Lib/`, `vendor-copy/src`, random `libs/` without `site-packages` in the path, copied wheels unpacked as `.py`.

- Review `_SKIP_SUBSTRINGS` / `DEFAULT_IGNORE_DIRS` against real dumps.

---

## P3 — polish

| Item | Notes |
|------|--------|
| `ctx --version` | Missing; exit 2 today |
| Bare `ctx` | No default help beyond argparse error |
| Large-drift warning spam | Every local search; scares people into `--force` |
| pytest + logfire plugin | Need `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` on this machine |
| Probe / chaos artifacts | `tests/ce_newfile_auto_index.py`, `tests/ce_live_index_beacon.py`, `tests/_chaos_run.py`, `tests/_chaos_output.jsonl` — delete or gitignore |
| Publish 0.2.4 | PyPI/npm not shipped; local editable only |
| Parent checkout MCP | Must not point CE at the wrong worktree |
| Dashboard Forget / pause | Built earlier; not re-certified end-to-end after chaos |
| CLI search path vs `search_repo` | Confirm `--path` is never parsed as extra roots |

---

## Explicitly out of scope for this backlog

- Turning off watchdog permanently
- Re-enabling unbounded auto full reindex (`CTX_ALLOW_BG_FULL` as default)
- Making CE MCP replace native Read at edit time (trajectory stays map → focus → edit)

---

## Suggested order when we pick this up

1. Search-query path pollution (#1) + disk/registry cleanup  
2. Stable `project_id` (#2)  
3. MCP health vs HTTP (#3) + engine ensure on use (#4)  
4. CLI search parity (#5)  
5. Init flags + doctor exit codes (#7–8)  
6. Dump/replace operator path (#6, #10–12)  
7. Polish + publish  

**Do not treat this repo as production-ready until P0 is done.**
