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
