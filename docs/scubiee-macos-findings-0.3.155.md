# Scubiee 0.3.155 — macOS findings

Branch `macos-validate-0.3.155` (from `upstream/main` 9525527). Not pushed; no PR.
Run against `docs/scubiee-macos-handoff-0.3.155.md`.

## 1. Environment

| | |
|---|---|
| OS | macOS 26.5.2 |
| Chip | Apple M5 (arm64), 10 CPUs, 16 GB |
| Backend | MLX (Metal) |
| Python | tool venv 3.11.16 (uv-managed); system `python3` 3.9.6 is unused |
| uv | 0.12.5 |
| Install | `uv tool install scubiee` from PyPI (0.3.155) for §1–§6 and §3a/§3b; branch build (`uv tool install --force --reinstall .`) for fix verification and the final batteries |
| Unit tests | separate venv (uv, Python 3.11, `pip install -e . pytest`), `PYTHONPATH=packages` |

Symlink chain (needed for §2):
`~/.local/bin/scubiee` → `~/.local/share/uv/tools/scubiee/bin/scubiee`;
`~/.local/share/uv/tools/scubiee/bin/python` → `~/.local/share/uv/python/cpython-3.11-macos-aarch64-none/bin/python3.11`
→ `cpython-3.11.16-macos-aarch64-none/…`. The tool venv's interpreter resolves **outside**
the `tools/` tree — this is the root of bug M5.

LaunchAgent label is `com.contextengine.supervisor` (the handoff's `launchctl list | grep scubiee`
finds nothing; grep `contextengine`).

## 2. §7 release batteries

### Final run — branch build at 89a8c3c (all fixes applied)

Lane A (`mcp_host_sim.py --lane a --live --settle-s 35`), both runs **exit 0, every phase ok=True**:

| Phase | Run 1 ms | Run 2 ms | Handoff reference (Windows) |
|---|---|---|---|
| clean_slate | 1648.6 | 1623.1 | |
| host_start | 117.1 | 112.3 | |
| auto_warm | 2131.3 | 2112.0 | |
| settle | 1204.4 | 1186.7 | |
| settle_join_embedder | 217.5 | 201.2 | |
| map_first | 126.7 | 125.3 | |
| map_second | 181.5 | 164.9 | |
| status_first | 0.5 | 0.5 | |
| pack_first | 25.0 | 25.2 | |
| expand_first | 127.0 | 103.2 | 664–810 |
| idle_hold | 120307.8 | 120266.7 | |
| post_idle_map | 178.4 | 160.8 | 442–750 |
| post_idle_pack | 24.3 | 24.1 | 115–122 |
| host_stop | 1.6 | 1.6 | |
| unload | 131864.2 | 131350.3 | |

Wall: 258 s per run.

- **warm_contract:** exit 0, `"failed": 0`, 6/6 PASS — warm ready 329.7 ms, first map 108.8 ms,
  map after idle 109.4 ms (handoff reference: 6.0 s / 1,322 ms / 426 ms).
- **ship_check:** exit 0, `"ok": true`, 3 tools, `errors: []`, 335 ms.
  (`git checkout docs/superpowers/plans/2026-09-06-mcp-ship-check.json` run afterwards.)

### Earlier runs on PyPI 0.3.155

- Run 1 (unmodified harness): every latency phase ok (`map_first` 151, `map_second` 231,
  `pack_first` 26, `expand_first` 163, post-idle 231 / 25 ms). **Only `unload` failed —
  `UNLOAD_TIMEOUT`** because the harness budget was 35 s while the product's disconnect
  debounce is 120 s (bug M2). In that run the engine's own shutdown also stalled ~9 s and the
  watchdog killed it at +129 s.
- Runs 2 and 3 (harness fixed): exit 0, all ok — `map_first` 124.7 / 126.9, `map_second`
  166.5 / 164.7, `pack_first` 25.0 / 25.2, `expand_first` 103.2 / 104.6, post-idle map
  198.1 / 197.2, post-idle pack 24.6 / 24.5 ms, `unload` 131.7 / 131.9 s.
- warm_contract 6/6 (warm 342.9 ms, first map 110.8, after idle 110.6); ship_check ok, 3 tools,
  0 errors, 449.5 ms.

Precondition note: the host-sim targets this repo and needs it indexed. A battery started right
after `wipe --all` fails every step with `auto_warm: WARM_TIMEOUT` (engine at 0 chunks). That
is expected, not a regression; `scubiee init .` (8,862 chunks, 139 s) restores it.

### `find` latency (the open question from Windows)

The first query after engine start took 497 ms (cold retrieve). Steady state was 115–160 ms,
and wall time tracked the engine's own total. There was no Windows-style 800–1,000 ms
first-minute plateau on the M5. During a hot sync, one query spiked to 1,166 ms wall against
98 ms of engine time, and a repeat trial did not reproduce it (OBS-5).

## 3. Per-delta results

### §3 — `wipe --all` (#10 + #1)

| Check | PyPI 0.3.155 | Branch build |
|---|---|---|
| 3a clean wipe from `~` | exit 0, **8.93 s**, audit clean, `next: Machine is clean…` — **but the 553 MB tool venv was left behind and the audit still said clean (FAIL, M5)** | exit 0, **4.51 s** (engine + live MCP bridge running), `ok: true`, audit clean, tool dir gone (`uv tool list` → "No tools installed") |
| 3b wipe with engine running | exit 0, **3.33 s**, engine killed, port 8765 free; `fast_path` taken legitimately; **same 558 MB venv leftover** | covered by the 4.51 s run above |
| §8 second wipe from `~` (TTY) | — | exit 0, **4.48 s**; progress UI and summary render correctly after the tool dir is moved aside |
| Trash drained, no `sh` cleaner left | PASS (≤3 s) | PASS |
| LaunchAgent + plist removed | PASS | PASS |
| TCC privacy prompt | **not verifiable** — `log show` returns nothing in this sandbox; none seen on screen | same |
| 3c reinstall right after wipe | PASS — reinstall 2.2 s, no trash-rename conflict; `setup` 162 s (wipe deletes model caches, so models re-download) | PASS — `setup` 156–159 s, agent loaded |

The first branch build with only the M5 fix removed the venv but **exited 1**:
`uninstall_scubiee: No module named 'pipeline.process_job'` (M7). Fixed in 89a8c3c and
verified by both branch-build wipes above.

### §2 — install identity on symlinked venvs (#2)

- PASS: `setup` prints no false "another scubiee install found" note.
- PASS: `doctor` → `multiple_installs: false`, `binaries_match: true` (also on the final branch build).
- PASS (negative): a Homebrew Python 3.12 venv copy is flagged `multiple_installs: true` from both sides.
- PASS: symlinked-venv unit test passes on macOS.
- OBS-1: the handoff's `python -c` identity snippet reports `active_binary: /private/tmp/-c`,
  `binaries_match: false` — `sys.argv[0]` artefact of `-c`, not Mac-specific, low.

### §4 — `init` estimate on MLX (#4)

| Repo | Estimate | Real | Chunks |
|---|---|---|---|
| flask | "<1 min" | 16.4 s | 918 |
| requests | "<1 min" | 12.3 s | 666 |
| FastAPI (docs-heavy), PyPI | "~8–11 min" | 132 s | — |
| FastAPI, branch, before overhead measured | "~5–6 min" | 130 s | — |
| FastAPI, branch, after overhead measured | "~2–3 min" | 165.6 s | — |

- PASS for flask and requests: the estimate brackets the real time, and `embed_throughput.json` holds a sane MLX rate of about 62–75 chunk/s.
- **FAIL (M3) on PyPI** for docs-heavy repos: the estimate was 4–5× too high. Doc files
  are one chunk each (text capped at 512 chars), and the fixed 0.08 s/file overhead is about
  16× the measured 0.0048 s on the M5. Fixed in 26ae3af: docs count one chunk each, and the
  per-file overhead is measured on this machine (runs of 200+ files only) and stored next to
  the chunk/s. After one measurement the estimate brackets the real time.

### §5 — quick Mac checks

- PASS #5 `resume`: 6.5 s, `engine.ok: true`, `spawn_owner: direct`.
- PASS #6 `connect`: all 32 `mcp_paths` / `rule_paths` exist inside enrolled repos.
- PASS #3 `sync`: 0.81 s, refreshed (not deferred), new content searchable immediately.
  OBS-4: `chunks_removed: 898` is misleading; the index is intact at 919 chunks.
- **FAIL (M6) on PyPI, #1 IDE-lock warning:** never shown. `__main__.py` used `os` without
  importing it, the filter raised `NameError`, and a bare `except` returned `[]`. Fixed in
  fedc7b4 and verified live: the wipe prompt now lists "holding N Scubiee MCP…".
- **FAIL (M4) on PyPI, setup/connect:** re-running `setup` or `connect` left the LaunchAgent
  **unloaded**. `launchctl bootout` is asynchronous, so the immediate `bootstrap` failed with
  "Load failed: 5: Input/output error", and the `load -w` fallback exits 0 even when it does
  nothing. Fixed in cb20b53: bootout only if loaded, wait up to 5 s for teardown, retry
  bootstrap 3×, and decide `ok` from `launchctl print`. Verified: `setup` ×2 plus `connect`
  kept `com.contextengine.supervisor` loaded each time.

### §6 — loaders

- PASS: glyphs render, no boxes or `?`.
- PASS: redraw in place (208 CR against 21 LF over a full init).
- PASS: colour on gives 584 SGR codes; `NO_COLOR` gives 0.
- PASS: piped output has no escape codes. OBS-6: `[embed]` log lines leak into it when stderr is merged.
- PASS: a 40-column terminal truncates with an ellipsis instead of wrapping.
- OBS-7: the ETA sometimes sticks at "~5s left" until the phase ends.
- N-A: no visual check in Terminal.app or iTerm2. All checks ran through `script` pseudo-terminals.

## 4. Bug register

| ID | Sev | Area | Summary | Root cause | Fix | Status |
|---|---|---|---|---|---|---|
| M1 | low | tests | 3 `test_env_guard` failures on macOS | Windows-layout tests had no platform guard; extra binary hard-coded `scubiee.exe` | 24e1bfd | fixed |
| M2 | med | host-sim | Lane A `unload` → `UNLOAD_TIMEOUT` on every run | harness budget 35 s, product disconnect debounce 120 s (restored in a356d2c) | 0e091d6 — budget = debounce + 35 s | fixed, batteries green |
| M3 | med | init estimate | docs-heavy repos estimated 4–5× too long on MLX | doc files counted by bytes; per-file overhead 0.08 s fixed vs 0.0048 s measured | 26ae3af | fixed, brackets after 1 run |
| M4 | high | darwin autostart | re-running `setup`/`connect` leaves the LaunchAgent unloaded | async `bootout` races `bootstrap`; `load -w` fallback exits 0 regardless | cb20b53 | fixed, verified live |
| M5 | high | wipe | `wipe --all` leaves the 553 MB tool venv and still audits clean | `uv_tool_root` called `resolve()` first; uv's python symlink points outside `tools/`, so the root was never found | 7138d14 — check absolute and resolved paths | fixed, verified live |
| M6 | med | wipe UX | IDE-lock pre-flight warning never shown | `os` not imported in `__main__.py`; bare `except` hid the `NameError` | fedc7b4 | fixed, verified live |
| M7 | high | wipe | with M5 fixed, `wipe --all` exits 1 (`No module named 'pipeline.process_job'`) | the early tool-dir unlock renames the live venv on POSIX (on Windows it fails, which is harmless), so later lazy imports break | 89a8c3c — early unlock is Windows-only; the package step moves the dir aside last | fixed, verified live ×2 |

Follow-up pass: every observation was root-caused, and all but OBS-5 and OBS-12 were fixed with a regression test (each test fails without its fix). Each fix is one commit.

| ID | Summary | Root cause | Fix | Live evidence |
|---|---|---|---|---|
| OBS-1 | `python -c` identity gives `active_binary: /private/tmp/-c` | `argv[0]` of `-c`/`-m`/`.py` was taken as the launcher path | 849a780 | `binaries_match` false → true |
| OBS-2 | engine's own shutdown stalls ~9–10 s | idle standby runs inside the engine; `stop_daemon` then POSTed `/v1/shutdown` to itself, tried to kill its own protected pid, swept `:8765` 5 s and polled 5 s before `_retire_self` exited — port held by a half-retired engine | e8de254 — self-targeted stop returns at once | `standby_stop` → exit 10.3 s → 0.2–0.5 s (3/3); host-sim `unload` 131.8 s → 120.2 / 121.4 s (debounce is 120 s) |
| OBS-3 | `engine start` during standby-retire returns `already_running`, then the engine exits | start adopted an engine that was mid-retire; the stopper's port sweep then killed the new spawn and `start` waited 90 s | f4516da — stopper-scoped `engine.retiring` marker, start waits it out, standby aborts if a start lands after its decision, fast-fail when the spawn dies | lost the engine 4/5 (PyPI) → 0/5 |
| OBS-4 | `sync` reports `chunks_removed` for every untouched chunk | a local full-corpus sync counted all of `truly_removed`, not just touched files | 169bbf6 | 664 → 1, no-op sync 0.25 s, index intact |
| OBS-5 | one hot-sync wall spike, 1,166 ms vs 98 ms engine | not reproduced — see below | none (no defect found) | 132 hot-sync queries, worst gap 173 ms |
| OBS-6 | `[embed]` lines in piped CLI output | embedder diagnostics printed unconditionally to stderr | 99a1d0b — `CTX_EMBED_LOG`, off for CLI commands, on in the engine | 0 lines piped, 17 in `engine.log` |
| OBS-7 | ETA sticks at "~5s left" | ETA was measured from the last render, not the last progress | 2dd3066 | counts down; switches to elapsed time on a stall |
| OBS-8 | host-sim rewrites a tracked stderr file despite `--out-dir` | `BridgeHost` hard-coded the docs path | 61c926a | stderr lands in `--out-dir`; tracked file md5 unchanged across 2 live runs |
| OBS-9 | wipe label says "unlock" on POSIX | fixed string | 34026dc, 936daae, 831679a — label, JSON hint and step/summary wording | TTY wipe: no "unlock" anywhere, one consistent label |
| OBS-10 | stale `upgrade.in_progress.json` from 0.3.144 | marker written every phase, cleared only on commit, never read | 7360ea6 — `doctor` reports an interrupted upgrade and clears the marker once the installed version moved on | planted 0.3.144 marker → `cleared: True`, file gone |
| OBS-11 | handoff greps `scubiee` in `launchctl list` | label is `com.contextengine.supervisor` | handoff doc updated | — |
| OBS-12 | TCC prompts can't be verified from logs | environment limit | — | still needs a manual desktop check |

New Mac bug found during the follow-up:

| ID | Sev | Summary | Root cause | Fix | Live evidence |
|---|---|---|---|---|---|
| M8 | med | engine and watchdog die with their spawner's process group | darwin was excluded from `start_new_session`, so closing the terminal that ran `init`/`engine start`, Ctrl-C there, or a host killing the MCP server's group took the warm engine down | 8fcdb50 | SIGHUP to the spawner's group: PyPI engine died 3/3, branch survived 3/3 (health 200) |
| M9 | med | graph catch-up worker segfaults (`rc=-11`, empty log, no result) | `preexec_fn=os.nice(10)` makes CPython run Python and every registered at-fork hook in the forked child of a multithreaded process before `exec`; on macOS that child crashed, so graph catch-up after a save silently failed | 9efa45e — the worker renices itself (`--nice 10`) | crash 3/3 in the a–g test context before, 0/3 after |
| M10 | low | `stop_dashboard` reports failure after a clean stop | the dashboard is a `Popen` child; after `/api/shutdown` it is a zombie until reaped and `kill(pid, 0)` succeeds on zombies, so a process that started and stopped it waited 5 s and got `ok: False` | bcb4a12 — reap an exited child with `WNOHANG` first | `ps` showed `Z`, `stop_ok` false 2/2 → true 26/26, 0.4–0.9 s instead of 5 s |

OBS-5 detail: two harnesses (warmed and cold-start, 30 functions appended to a tracked file per trial) ran 132 queries during hot syncs. No query came close to 1 s; the largest wall-minus-engine gap was 173 ms. Instrumenting request admission (`admit` → `activate_repo`, outside the engine's timer) gave p50 0.8 ms, p90 12.9 ms, max 71.5 ms; the remaining ≤150 ms is the HTTP thread waiting on the GIL while the sync thread parses and hashes, inherent to in-process sync. The original spike most likely coincided with an outside registry writer; no code change is warranted.

Pre-existing macOS test failures (fail identically on PyPI 0.3.155), fixed in 80e2598 / 8fcdb50:

- `test_engine_lifecycle_audit`, `test_watchdog_lifecycle_contract`: INTERNALERROR. `monkeypatch.setattr(os, "name", "nt")` also flipped pathlib to `WindowsPath`, so every `Path()` mid-test, and pytest's own failure report, raised. `tests/conftest.py` now pins pathlib to the host OS.
- `test_lifecycle_ownership`, `test_process_job`: these asserted the POSIX own-session contract that darwin violated (M8), so the code was wrong, not the tests.
- `test_watchdog`: asserted Windows creation flags on POSIX; now checks each platform's contract.
- `test_root_probe::test_dir_watch_finds_new_files_without_a_repo_walk`: relied on NTFS's lazy folder-entry mtimes to treat `old/` as untouched; the test now backdates the old tree.
- `test_graph_catchup_async::test_start_graph_merge_runs_a_real_child_process` (order-dependent): M9.
- `test_dashboard_api::test_background_server_reuses_pid_and_stops`: M10.
- `test_connect_formats` (Devin `AppData` path) and `test_diagnose_output_path` (PowerShell literal): Windows-only expectations; now platform-aware (d37fd47).

## 5. Unit tests

On the final branch, in a Python 3.11 venv on macOS, all delta tests pass: 135 passed and 2 skipped. The skips are POSIX/Windows-only by design. The run covered:

- `test_env_guard`, `test_init_estimate`, `test_lifecycle_runtime`, `test_wipe`, `test_wipe_speed`
- `test_process_control`, `test_production_hardening`
- `test_map_grep_prefilter`, `test_mcp_host_sim`, `test_pause_resume`, `test_resume_engine_start`

New regression tests:

- the async-bootout darwin re-register
- agent not loaded reported as a failure
- the IDE-lock warning
- a symlinked uv tool python
- doc-aware estimate and measured overhead
- POSIX full-wipe prep not unlocking the live tool dir

The new POSIX full-wipe test fails without 89a8c3c.

After the follow-up pass, the **whole** suite (`pytest tests`, default markers) on macOS gives
1968 passed, 24 skipped, 12 failed. All 12 also fail on the branch's starting point (95255278),
and none are Mac-specific:

- 11 locate-quality corpus tests (`test_polytrace` ×4, `test_trace_lab` ×2, `test_multi_seed_v1` ×2,
  `test_locate_quality_combo`, `test_vague_prompts`, `test_verify_board`): the same tests fail in
  the repo's Windows full-pytest logs (`docs/architecture/_full_pytest_post_kiro.txt`).
- `test_e2e_pipeline::test_full_pipeline_stores_in_faiss_collection` (0 hits with fake all-ones
  embeddings): listed as a known "FAISS/pipeline env" failure in the Windows 0.3.89 pre-prod battery.

The baseline also failed `test_connect_formats`, `test_diagnose_output_path` and `test_dashboard_api`
on macOS; those are fixed (d37fd47, bcb4a12). One early full run segfaulted the pytest process
itself; it did not recur across the next 4 full runs, and the only reproducible segfault (M9) was
in a child process.

## 6. Verdict

**PyPI 0.3.155 is not fully correct on macOS.** Search, warm-up and lifecycle are fast and
healthy. All latency phases are well under budget and much faster than the Windows
reference. However, three high-severity Mac/POSIX bugs ship in it:

- `wipe --all` leaves the 553 MB tool venv while reporting clean (M5).
- Re-running `setup` or `connect` leaves the logon agent unloaded (M4).
- The IDE-lock warning is dead (M6).

**With the 7 commits on `macos-validate-0.3.155`, macOS is green.** Both Lane A live runs
(including settle, 120 s idle and unload), warm_contract 6/6 and ship_check pass on the final
build. Two live `wipe --all` runs exit 0 in about 4.5 s with a clean audit and nothing left
behind, and reinstall plus `setup` works immediately.

**Follow-up pass (17 more commits, f4516da…d37fd47): every observation is resolved** (OBS-5 and
OBS-12 have no code defect), plus three Mac bugs found along the way (M8 process group, M9 graph
worker segfault, M10 dashboard zombie). Final live battery on the final build:

| Check | Run 1 | Run 2 |
|---|---|---|
| Lane A `auto_warm` / `settle` (ms) | 4329 / 3422 | 2129 / 1216 |
| `map_first` / `map_second` (ms) | 157.9 / 217.4 | 123.8 / 161.9 |
| `pack_first` / `expand_first` (ms) | 25.4 / 150.6 | 24.6 / 100.4 |
| post-idle `map` / `pack` (ms) | 185.0 / 24.1 | 160.5 / 24.0 |
| `idle_hold` / `unload` (s) | 120.3 / 121.2 | 120.3 / 120.9 |
| all 15 phases ok | yes | yes |

`unload` was 131.7–131.9 s before the OBS-2 fix: the 120 s disconnect debounce plus the 10 s self-kill stall.
warm_contract 6/6 (`warm_ready` 331.5 ms, first map 105.6 ms, map after idle 109.6 ms).
ship_check ok, 7/7 checks, 333.9 ms. The bridge stderr went to `--out-dir`; the tracked file was unchanged.
A live TTY `wipe --all` took 4.51 s with a clean audit and consistent labels.

Mac-only follow-ups:

- A listener check via `lsof` (psutil `net_connections` needs root on macOS). Port 8765 was verified free with `lsof` in every wipe.
- A manual TCC prompt check on a desktop session.

**Machine state left:** final branch build installed via `uv tool install`, `setup` done,
`com.contextengine.supervisor` loaded, `doctor` ok (`binaries_match: true`, no interrupted upgrade),
this repo re-indexed (8906 chunks), and Cursor, Kiro and Copilot reconnected. Throwaway dirs
(`/tmp/scu_*`, `/tmp/hostsim*`) removed.
