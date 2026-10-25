# Scubiee CLI sequence-test findings (0.3.153)

_State-machine-driven testing: instead of running commands in isolation, I
modelled the user's state vector `(machine, repo, engine, tools, pause)` and
executed **command sequences** where state carries over, the class of bug that
isolated tests miss. 12 sequences, ~45 command invocations, on a clean isolated
home. Harness checks every step for: traceback, hang (>timeout), exit code,
state consistency, install integrity._

## Headline: the reported hang was NOT actually fixed the first time

The user reported `scubiee init --confirm` on their home dir looking hung. A
prior fix was added to `preflight_index_scope`, but **the sequence test proved it
did not work**: `S6 init HOME --confirm` still **HANG(>70s)**.

**Why the first fix failed:** it placed the cap check *after*
`n = len(collect_index_relpaths(root))`. That count is the expensive part, it
walks the entire home dir AND reads the first 8 KB of every candidate file (the
text sniff) just to produce a number. On a ~400k-file home dir that is minutes of
silent work, so the hang happened *before* the new cap check ever ran.

**The real fix (this version):** a new bounded `exceeds_index_cap(root, cap)` in
`pipeline/paths.py` does its own pruned `os.walk` (skips `node_modules`, `.git`,
`.venv`, dotdirs via `is_builtin_ignored_dir_name`), counts only
extension-matching files, and **early-exits the instant it passes the cap**, no
per-file content read. `preflight_index_scope` now calls it for the broad-root
`--confirm` path *before* the full count. Verified against the real home dir:

| | before | after |
|---|---|---|
| `init HOME --confirm` | hang (>70s, still going) | **refuses in ~11.6s** with a clear message |
| normal project preflight | 1.8s | 1.8s (unchanged) |

The message now correctly points at `--roots`/`--force` (not "re-pass --confirm",
which the user already did). `--force` remains the explicit "I really mean it"
escape. Tests: `test_broad_home_confirm_still_caps_huge_tree`,
`test_broad_home_confirm_under_cap_counts_precisely`,
`test_exceeds_index_cap_early_exits_over_limit`,
`test_exceeds_index_cap_skips_ignored_dirs` (+ existing 37 in the affected
suites; 41 pass total).

## Full sequence results

All 12 sequences: **zero tracebacks, zero unexpected hangs** (after the fix).
Every error path returned a clean exit code.

| Seq | What | Result |
|---|---|---|
| 1 Happy path | init→status→search→map find→map focus→sync→status | PASS |
| 9 Idempotent re-init | init×3 | PASS (stable, incremental) |
| 6 **Broad-root** | init HOME refuse; init HOME --confirm | refuse exit 2; **--confirm now caps in ~11.6s (was hang)** |
| 7 Connect-before-init | connect(fresh)→status→search | PASS (search exit 1 = clean "not enrolled") |
| 3 connect→init→reconnect | kiro→init→cursor→status | PASS (install intact, tools auto-applied) |
| 4 Pause semantics | pause→search→map→status→resume→search | PASS (see note) |
| 5 Remove then use | remove→status→search→reinit→status | PASS (clean unmanaged, re-enrolls) |
| 10 Disconnect | connect --all→disconnect cursor→status→disconnect kiro | PASS |
| 8 Engine lifecycle | stop→status(autostart)→stop→map | PASS (map engine-down = clean msg exit 1) |
| 12 Bad-arg recovery | map --config bogus→search→status | PASS (exit 2 then state fine) |

## Minor findings (not blockers)

- **F2 (harness artifact, not a bug):** `map --repo <path>` → exit 2. `map` takes
  the repo as a **positional `path`**, not `--repo`. scubiee rejected it cleanly
  (exit 2, no traceback). But note the **inconsistency**: `connect`/`disconnect`
  use `--repo`, while `map`/`search`/`init`/`status`/`sync` use a positional
  `path`. Worth unifying for UX, or documenting clearly.
- **F3 (minor UX):** `pause`/`resume` are cwd-scoped (optional positional path).
  Run from an *unmanaged* directory, `pause` returns `{"ok":false,"error":
  "unmanaged"}` with exit 1 and no actionable hint. Pointed at the managed repo
  it works (`ok:true, state:paused`, exit 0). Suggest a friendlier hint
  ("run inside a managed repo or pass a repo path"). Also note: **search/map on
  the CLI still return results while paused**, pause gates the MCP/agent surface,
  not your own CLI queries. Confirm this is intended and document it.

## Verdict

The user-reported hang is a **real, now-genuinely-fixed** bug, and critically,
it was the *sequence/state* test (broad-root with `--confirm`) that caught the
first fix being ineffective, which the earlier isolated-command passes missed.
No tracebacks or deadlocks anywhere across the state machine. Two minor UX nits
(flag inconsistency, terse pause-on-unmanaged) remain, documented above.
