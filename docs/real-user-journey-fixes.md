# Real-user journey fixes (0.3.153 → next)

Found by running the full user journey in a fresh Linux container
(`vm/run.ps1`, logs in `vm/logs*/`). Each issue is fixed on its own, with a
root cause, the patch, and how it was verified.

| # | Issue | Status |
|---|-------|--------|
| 1 | `wipe --all` always exits 1 ("quit Cursor…") on a clean machine | fixed |
| 2 | `doctor` / `setup` report a second install on a normal `uv tool install` | fixed |
| 3 | `sync` returns before the index is refreshed (`strategy: deferred`) | fixed |
| 4 | `init` time estimate far too low on CPU ("~1 min", took 5 min) | fixed |
| 5 | `resume` prints nothing for ~90 s (engine silently failed to start) | fixed |
| 6 | `connect --cursor` / `resume` report paths that were never written (`/.cursor/mcp.json`, global rule) | fixed |
| 10 | `wipe --all` hangs when run from the home folder; ~2 min even when it works | fixed |
| 11 | `map focus` by bare name takes ~1.3 s (was ~0.2 s); fails the release battery | fixed |
| 7 | Re-running `init` prints "already indexed" on top of an uncleared "Starting…" line | open |
| 8 | `scubiee` with no arguments prints a raw argparse error (exit 2) | open |
| 9 | `scubiee --version` on a fresh machine prints "Engine stopped" | open |

---

## 1. `wipe --all` always exits 1 on a clean machine

**Symptom.** Every `scubiee wipe --all --confirm` ended with
"! Some Scubiee files remain — quit Cursor completely so MCP releases locks,
then run wipe again" and exit code 1, even in a container with no Cursor.
`~/.scubiee/` existed after the wipe with two files: `engine.log` and
`engine_transition.json`.

**Root cause.** The wipe deletes `~/.scubiee`, then runs a final process
sweep (`kill_all_scubiee_processes` → `stop_all_context_engine_processes` →
`daemon.stop_daemon`). With no engine running, `stop_daemon` still:

- logged a `[stop]` audit line through `engine_log.note_stop`, which did
  `home.mkdir(parents=True)` before appending to `engine.log`; and
- recorded a `stop` lifecycle transition through `save_transition`, which
  also creates the home.

The logged line proved it:
`target=engine pid=None reason=stop_daemon:user … at=daemon.stop_daemon<process_control.stop_all_context_engine_processes<process_control.kill_all_scubiee_processes<wipe.wipe_all`.
The artifact audit then found the recreated home and failed the wipe, and
the summary blamed Cursor.

**Fix.** Stopping must never create Scubiee's home:

- `engine_log.note_stop` writes only into an existing home (no `mkdir`).
- `daemon.stop_daemon` records the `stop` transition only when the home
  exists.

Normal stops on an installed machine still log and record exactly as before.

**Verification.**

- New `tests/test_stop_no_home.py`: stop with a missing home leaves it
  missing; stop with an existing home still writes the log line and
  transition. 78 stop/wipe/lifecycle tests pass.
- Live (`vm/run.ps1 wipe_check.sh`, two enrolled repos):
  `wipe --all` exit 1 → **0**, "Wipe complete" + "Clean", and
  `/root/.scubiee` no longer exists afterwards.

## 2. `doctor` / `setup` report a second install on a normal `uv tool install`

**Symptom.** On Linux, right after `uv tool install scubiee`:
`setup` printed "note: another scubiee install found at
/root/.local/share/uv/tools/scubiee/bin/scubiee", and `doctor` returned
`ok: false` (exit 1) with "Multiple scubiee installs on PATH… Expected for
this Python: /usr/local/bin/scubiee" — a file that does not exist.

**Root cause.** `env_guard.current_python()` returned
`Path(sys.executable).resolve()`. A uv tool environment (like any Linux/macOS
venv) has `bin/python` as a symlink to the base interpreter, so resolving it
gave `/usr/local/bin/python3.12`, and the "expected" scubiee became
`/usr/local/bin/scubiee`. Meanwhile `~/.local/bin/scubiee` (uv's link)
resolved to the tool's real binary, which no longer matched "expected" and was
counted as an extra install. The uv-shim exception did not apply either,
because the resolved interpreter path no longer contained `uv/tools/`.

**Fix.** `current_python()` uses `Path(sys.executable).absolute()` — no symlink
resolution — so the interpreter path keeps identifying the environment that
is actually running. This corrects every symlinked venv, not only uv tools.

**Verification.**

- New `test_symlinked_venv_python_is_not_resolved_to_base` rebuilds the real
  Linux layout with symlinks. Run in a Linux container it failed before the
  fix (expected `usr-local-bin/scubiee`) and passes after. (Windows cannot
  create the symlinks without admin rights, so it skips there; the rest of
  `test_env_guard.py` passes on Windows.)
- Live (`vm/run.ps1 install_identity_check.sh`, fresh `uv tool install`):
  expected binary is now `/root/.local/share/uv/tools/scubiee/bin/scubiee`,
  `multiple_installs: false`, `binaries_match: true`, the setup note is gone,
  and `install` no longer contributes to `doctor` failing.

## 3. `sync` returns before the index is refreshed

**Symptom.** After editing `src/flask/helpers.py`, `scubiee sync .` returned
immediately with `"strategy": "deferred", "refreshed": false`, and a search
right after it did not find the new function (it showed up minutes later).

**Root cause.** With an engine running, the CLI forwards to `POST /v1/sync`.
That endpoint is intentionally fire-and-forget: it only calls
`sync_loop.request_poll()` (sets a flag) so the HTTP thread — shared with MCP —
never walks files or embeds. The CLI printed that "accepted" reply as the sync
result, so `sync` never actually waited for anything.

**Fix.** An explicit sync can now wait for its own poll to settle, without the
HTTP thread doing any indexing work:

- `BackgroundSyncLoop.request_poll()` returns a sequence number. The keeper
  thread records which sequence each poll covered and which paths changed;
  after each `drain_due`/`drain_publish` it marks the sequence *settled* once
  nothing is `queued`/`due`/`processing`, no publish is pending, and no
  interval sync is running. `wait_settled(seq, timeout)` blocks on a
  condition variable; `settle_report()` builds the reply.
- `graph_catchup` entries do not block settle: they run after the chunks are
  already published (search is fresh) and are held back ~30s on purpose. They
  are reported as `graph_pending`.
- Paths already in flight when the requested poll runs count as synced — the
  periodic poll can queue an edit a moment earlier, and its folder watch then
  no longer reports it.
- `POST /v1/sync` with `"wait": true` waits (default 90s, capped at 110s,
  below the client's 120s HTTP timeout) and returns
  `strategy: "live"`, `refreshed`, `files_synced`, `files`, `waited_ms`.
  On timeout it returns `ok: false, error: "sync_timeout"` with a hint.
  Without `wait` (MCP and other callers) the behaviour is unchanged.
- `scubiee sync` sends `wait: true` and shows a "Syncing changes" spinner in a
  terminal; a timeout prints "Sync not finished" plus the hint.

**Verification.**

- New `tests/test_sync_wait_settle.py` (7 tests: sequencing, settle only after
  publish, pending publish blocks, older poll cannot settle a newer request,
  graph catch-up does not block, in-flight paths are counted, honest timeout).
  140 sync/keeper/server tests pass.
- Live (`vm/run.ps1 sync_check.sh`, fresh container, enrolled repo):

  | Case | Before | After |
  |------|--------|-------|
  | edit existing file → `sync` | `deferred`, edit not searchable | 5.4 s, `refreshed: true`, `files: [src/orders_2.py]`, search rank 1 |
  | new file → `sync` | — | 1.4 s (32.7 s before the graph-catch-up exclusion), `files: [src/delivery.py]`, search rank 1 |
  | edit → `sync` in a terminal | — | spinner, then "✓ Synced 1 file(s) updated" in 1.4 s; search rank 1 |
  | no changes → `sync` | — | 0.8 s, `refreshed: false` |

  If the background watcher has already published an edit before `sync`
  asks (it hot-syncs saves in ~0.55 s), `sync` correctly says
  "Already up to date".

## 4. `init` time estimate far too low on CPU

**Symptom.** `scubiee init` on pallets/flask asked "This repository has 89
files (est. ~1 min)" and then ran for 5 minutes on an 8-CPU machine without a
GPU.

**Root cause.** `cli_ui.format_index_eta(n_files)` was a flat
0.45–0.55 s *per file* tuned on a GPU box. It ignored the two things that set
the time: how much code there is (embedding is ~95% of a CPU init, and it
scales with chunks, not files — flask is 89 files but 918 chunks) and how fast
this machine embeds. Setup does measure speed (`accel.json` →
`texts_per_sec`), and `workload.record_embed_throughput` existed, but nothing
called it and the prompt never used either.

**Fix.** The estimate is now *work ÷ this machine's speed*:

- **Work.** `preflight_index_scope` remembers the paths it just counted;
  `incremental.scope_bytes(root)` sums their sizes (a `stat` per file, no
  second walk). Chunks ≈ bytes / 690 (flask 646, requests 734 B/chunk), plus
  10 s + 0.08 s/file for scan/parse/link/write/engine start.
- **Speed.** `workload.machine_embed_cps()` prefers the rate *measured by real
  indexes on this machine* — the indexer now records fresh (non-cached) chunks
  ÷ embed seconds into `~/.scubiee/embed_throughput.json` (running average,
  samples under 64 chunks ignored). Before the first index it falls back to
  setup's calibration, which embeds single-threaded and is therefore a lower
  bound on speed.
- **Range.** Measured speed → 0.8–1.25× of the embed estimate; calibration only
  → 0.5–1.05× (the real run can be up to ~2× faster than calibration).
  Under a minute shows "<1 min". With no speed known (no setup), the old
  per-file formula remains the fallback.

**Verification.**

- New `tests/test_init_estimate.py` (8 tests), including both live runs below
  as parameterised cases; 39 estimate/workload/progress tests pass.
- Live (`vm/run.ps1 estimate_check.sh`, fresh container, 8 CPUs):

  | Repo | Speed source | Prompt said | Real |
  |------|--------------|-------------|------|
  | flask (89 files, 918 chunks) | setup calibration 1.76 t/s | ~5–9 min (old: ~1 min) | 5.4 min |
  | requests (50 files, 666 chunks) | measured 2.97 chunk/s | ~4–6 min | 3.8 min |

  `embed_throughput.json` recorded 2.97 then 3.05 chunk/s. The requests run
  showed the 650 B/chunk first guess was slightly high for that repo, so the
  ratio was recalibrated to the two-repo average (690) and the measured band
  widened to 0.8×; with those values the same inputs give ~4–9 min and
  ~3–5 min (computed by the parameterised test from the measured inputs).

## 5. `resume` hangs ~90 s and the engine silently fails to start

**Symptom.** `scubiee resume` printed nothing for 91 s, then reported
`"ok": true`. Buried in its JSON: `"engine": {"ok": false, "error": "daemon
started but health check timed out"}`. So the "slow resume" was really a
failed engine start that was reported as success.

**Root cause.** `resume()` deliberately keeps `pause_state.json` at
`paused: true, resuming: true` until everything is restored, then calls
`ensure_daemon`, which spawns the engine as `scubiee engine run <repo>`. That
child process hits the CLI's global-stop guard: `paused_blocks_command` (and
`guard_engine_action("run")`) refused `engine run` whenever `is_paused()` was
true — they did not know about the `resuming` state. The engine exited at
once, and `ensure_daemon` waited out its ~90 s health timeout.
`daemon.py`, `watchdog.py`, `rules_installer.py` and `gate_cli.py` already used
`is_paused() and not is_resuming()`; the guard and
`lifecycle_runtime.engine_should_be_running` (the supervisor's check) did not.
Separately, `resume()` never looked at the engine result before returning
`ok: true`.

**Fix.**

- `pause_resume.is_stopped()` = paused **and not** resuming — the one state that
  must refuse engine starts. `lifecycle_guard.paused_blocks_command`,
  `guard_engine_action`, and `engine_should_be_running` use it. A real
  `scubiee stop` still blocks `engine run/start/ensure` exactly as before.
- `resume()` returns `ok: false` with a hint ("MCP and rules are restored, but
  the engine did not start…") when `ensure_daemon` fails.
- In a terminal, `resume` shows a "Resuming Scubiee" spinner, and an engine-only
  failure says "Resumed, but the engine did not start" instead of the
  incorrect "Scubiee is still stopped".

**Verification.**

- New `tests/test_resume_engine_start.py`: `engine run` allowed while resuming;
  still blocked when truly stopped; supervisor keeps the engine while resuming
  but not when stopped; resume reports a failed engine start. 62
  resume/lifecycle/watchdog/upgrade tests pass.
- Live (`vm/run.ps1 resume_check.sh`: setup → init → connect → stop → resume,
  twice):

  | | Before | After |
  |---|--------|-------|
  | `resume` wall time | 91.3 s | **1.7 s** (piped), **1.9 s** (terminal) |
  | engine after resume | health check timed out, `ok: true` reported | `/health` ok right away, `engine.ok: true` |
  | search right after resume | — | top hit `src/m_2.py` |
  | terminal output | silent | "⠋ Resuming Scubiee" → "✓ Resumed" |

## 6. `connect` / `resume` report paths that were never written

**Symptom.** `scubiee connect --cursor` reported
`rule_path: /root/.cursor/rules/scubiee.mdc` with `rule_paths: []` and
`rule_written: null`, so the user was pointed at a file that does not exist.
`scubiee resume` run from `/` reported `mcp_path: /.cursor/mcp.json` at the
filesystem root. The files that were really written (`<repo>/.cursor/mcp.json`,
`<repo>/.cursor/rules/scubiee.mdc`) appeared only deep inside `project_fan_out`.

**Root cause.** `rules_installer.install_tool` filled its top-level fields
*before* doing any work, from guesses: `mcp_path(s)` from
`resolve_mcp_project_paths(tool, Path.cwd())` (whatever directory the command ran
in) and `rule_path` from `resolve_rule_user_paths(tool)` (the legacy global
rule location). Connect is project-local now, so it writes MCP config and GATE
rules only into enrolled repos through `fan_out_tool_to_enrolled_repos`. Neither
guess is ever written. `pause_resume._enable_mcp_for_tool` also added both the
top-level list and the per-repo lists, so a real path could appear twice.

**Fix.**

- `install_tool` starts with empty `mcp_path(s)` / `rule_path(s)`, and
  `_summarize_fan_out_paths` fills them from the fan-out reports: files written
  (`mcp_paths`, `rules.written`), or the would-write lists on `--dry-run`. Paths
  are deduplicated, and the first of each becomes `mcp_path` / `rule_path`.
- With no enrolled repo, all four fields are empty/`null` (the existing
  "Saved Cursor for this machine… run `scubiee init .`" notice explains why).
- `_enable_mcp_for_tool` returns the top-level list only (no duplicates).

**Verification.**

- New `tests/test_connect_reported_paths.py` (5 tests): connect from an
  unrelated cwd reports the repo files and every reported path exists; nothing
  is reported with no enrolled repo; dry-run reports would-write paths and
  writes nothing; two repos are listed once each; resume's enable list has no
  duplicates. 145 connect/resume/journey tests pass (6 platform skips).
- Live (`vm/run.ps1 paths_check.sh`). The script checks every reported path
  exists and is inside the enrolled repo `/work/app`:

  | Step | rc | Time | `mcp_path` | `rule_path` | ok |
  |------|----|------|-----------|-------------|----|
  | connect before init (cwd `/tmp`) | 0 | 0.5 s | `null` | `null` | true |
  | connect in repo | 0 | 0.5 s | `/work/app/.cursor/mcp.json` | `/work/app/.cursor/rules/scubiee.mdc` | true |
  | connect from `/` | 0 | 0.5 s | `/work/app/.cursor/mcp.json` | `/work/app/.cursor/rules/scubiee.mdc` | true |
  | connect `--dry-run` from `/` | 0 | 0.3 s | `/work/app/.cursor/mcp.json` | `/work/app/.cursor/rules/scubiee.mdc` | true |
  | resume from `/` | 0 | 1.7 s | `/work/app/.cursor/mcp.json` | `/work/app/.cursor/rules/scubiee.mdc` | true |

  Before: `/.cursor/mcp.json` and `/root/.cursor/rules/scubiee.mdc`, neither of
  which existed. After: no missing paths and nothing outside the repo
  (`ALL_OK True`).

## 10. `wipe --all` hangs from the home folder and is slow even when it works

**Symptom.** On a real Windows laptop, `scubiee wipe --all --confirm` run from
`C:\Users\usman` was still going after ~15 min. A `py-spy` stack showed it in
`_discover_repo_id_dirs` → `Path.rglob(".scubiee")`. A rerun from an empty
folder finished, but took 112 s.

**Root cause.**

- `wipe_all` cleaned every registered repo, then also treated the folder it was
  run from as a repo and called `rglob(".scubiee")` on it. From the home folder,
  that walks all of Downloads, every `node_modules` and `.venv`. Even inside this
  repo, the old search took 114 s.
- Fixed overhead of 12.8 s, measured with nothing running: seven unconditional
  sleeps (1.0 s × 3 in `stop_all_context_engine_processes`, a 1.5 s MCP settle,
  0.2 s × 3 in `stop_watchdog`); 12 engine health checks at ~0.36 s each (on
  Windows a closed localhost port waits out the connect timeout instead of
  refusing); and the full stop-all pass run three times. `stop_processes_under`
  also slept its full grace period with nothing to kill.
- The remaining time went to deleting `~/.scubiee` and the model cache file by
  file.

**Fix.**

- The current folder is added only if it is a real repo (`.git` or `.scubiee`)
  and not home, an ancestor of home, or a drive root. `_discover_repo_id_dirs`
  is now a pruned `os.walk`: it skips `node_modules`, `.git`, `.venv`, caches and
  build output, stops at depth 4 and 5,000 folders, and never returns the
  machine home. Registered repos are still wiped by path.
- Sleeps run only after something was actually terminated. The MCP settle runs
  only if a Scubiee process is alive. `stop_daemon` / `kill_all_engine_daemons`
  reuse the last health answer. `kill_all_scubiee_processes` takes a fast path
  when nothing is running (no Scubiee process, no engine port listener, nothing
  under the uv tool folder).
- From the CLI, `~/.scubiee`, the vector DB and model caches are renamed aside
  (`<name>.trash-<pid>`, instant) and deleted by one detached cleaner after the
  CLI exits. The original paths are free immediately, so a reinstall can start
  right away. If the rename fails (a locked file), it falls back to the in-place
  delete.

**Verification.**

- New `tests/test_wipe_speed.py` (11 tests): home/ancestor/drive roots are never
  walked; dependency trees are skipped; the depth cap holds; the machine home is
  never returned; only real repos are added as targets; rename-aside; the
  scheduled delete runs after the waited process exits; kill-all fast path and
  full path; no idle sleeps. 43 wipe/stop/hardening tests pass. Two existing
  tests were updated to match (the test repo got a `.git`; the bridge test pins
  "something is running").
- Windows, this laptop (read-only search timing):

  | Search root | Before | After |
  |---|---|---|
  | `C:\Users\usman` (home) | still running after 120 s (hung ~15 min in practice) | **0.00 s** |
  | `context-engine` repo | 114.3 s | **0.23 s** (same `.scubiee` found) |
  | fixed overhead, nothing running | 12.8 s | **1.83 s** |

- Live (`vm/run.ps1 wipe_speed_check.sh`): a home seeded with a 300,000-file
  `node_modules`, then setup → init → connect → `wipe --all` from `/root`:

  | Step | Before (PyPI 0.3.154) | After |
  |------|------|-------|
  | `wipe --all` from home | rc 0, 8.9 s | rc 0, **3.8 s** (rerun with the depth cap: **3.9 s**) |
  | right after wipe | — | `~/.scubiee`, model cache, repo `.scubiee` gone; `scubiee` not on PATH |
  | background delete | — | trash drained in **0.2 s** |
  | reinstall + `scubiee setup` right after | — | rc 0 (0.1 s install, setup ready) |

  On Linux the old walk over 300k files costs seconds, not hours. The hang is a
  Windows effect (NTFS plus antivirus on every directory read), and the Windows
  timings above cover it.

---

## 11. `map focus` by bare name takes ~1.3 s and fails the release battery

**Found by:** the `mcp_host_sim` Lane A release battery on Windows. `pack_first`
(a `map focus names=[enforce_mcp_warm_contract]`) took 1,322 ms against a 1 s
budget. The same call by `file::symbol` took 24 ms.

**Root cause.** Commit `7dd2a85` (Unicode/`$` identifiers in focus) changed the
bare-name resolution patterns in `_resolve_symbol_name` from `\b` to the
lookarounds `(?<![\w$])` / `(?![\w$])`. The grep prefilter
(`_pattern_prefilter` in `map_v3_helpers.py`) gives up on any pattern that
contains `[`, so every bare-name lookup ran the full regex over all ~4,900
"code" files (28.5 MB; 3,820 of them under the gitignored `testdata/`). The
keyword-led definition pattern was slow for a second reason: its prefilter ORs
every identifier (`pub`, `type`, `var`, `fun`, ...), so almost every file passed.

**Fix (`packages/pipeline/map_v3_helpers.py`).**

- Character classes are blanked before group handling: a class matches one
  unknown character and never holds required text.
- Identifiers outside every group are ANDed when the pattern has no top-level
  `|` — each is a literal the match must contain. Alternations stay OR.

The prefilter is still only a necessary condition, so grep results cannot change.

**Verification.**

- New `tests/test_map_grep_prefilter.py` (13 tests): lookaround/class patterns
  get a prefilter, the definition pattern requires the name, top-level
  alternation stays OR, and no real match is ever rejected.
- Equivalence on the real repo: grep with vs without the prefilter, 17
  identifiers (incl. `x`, `get`, `data$`, `École`) × 4 patterns × 2 scopes =
  136 pairs, **0 mismatches**.

  | Measurement | Before | After |
  |------|------|-------|
  | bare-word grep (lookaround) | 644 ms | 24 ms |
  | `_resolve_symbol_name` | 1,270 ms | 77 ms |
  | `map focus` bare name, through the MCP bridge | 1,291–1,326 ms | 112–124 ms |

- Release batteries on the laptop (fixed wheel installed with `uv tool install`):

  | Battery | Result |
  |------|------|
  | `mcp_host_sim --lane a --live --settle-s 35` (with 120 s idle), 2 runs | ok, exit 0 both runs |
  | `warm_contract_acceptance.py` | 6/6 checks pass |
  | `scubiee_mcp_ship_check.py` | ok, 0 errors |

**Harness fixes found on the way** (`packages/pipeline/mcp_host_sim/`): Map V3
returns plain text, so the bridge host reads `dense_ready` from engine `/health`,
and the scenario ignores the non-dict placeholder card when picking the pack seed.

**Known margin.** `map find` with a new query is ~260–600 ms steady state but
800–1,000 ms in the first minute after the engine starts, and it spikes while
the engine hot-syncs a changed file. Lane A's `map_second` passed at 962–979 ms
against a 1 s budget. Run the battery with `--out-dir` outside the repo: by
default it writes its report into `docs/superpowers/plans/`, so the next run
starts by re-indexing that report, right when the locate calls are timed.
