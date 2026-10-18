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

Observations (not fixed):

- OBS-1: the `python -c` identity report gives `active_binary: /private/tmp/-c` (low).
- OBS-2: on PyPI run 1, the engine's own shutdown stalled about 9 s before the watchdog kill at +129 s. It wasn't seen again.
- OBS-3: `engine start` during the standby-retire window returns `already_running`, and then the engine exits. Reproduced 3/3. Low, because CLI-only engines retire by design.
- OBS-4: `sync`'s `chunks_removed` counter is misleading (see §5).
- OBS-5: a single hot-sync wall spike of 1,166 ms against 98 ms engine time; not reproduced.
- OBS-6: `[embed]` lines in piped output when stderr is merged.
- OBS-7: the ETA sticks at "~5s left".
- OBS-8: the host-sim writes `docs/superpowers/plans/_mcp_host_sim_bridge_stderr.txt`, a tracked file, despite `--out-dir`.
- OBS-9: the wipe progress label still says "Prepared machine (stub MCP, kill, unlock)" on POSIX, where no unlock runs any more.
- OBS-10: a stale `upgrade.in_progress.json` from 0.3.144 was found in `~/.scubiee`.
- OBS-11: the handoff should grep `contextengine`, not `scubiee`, in `launchctl list`.
- OBS-12: TCC prompts can't be verified from logs in this environment.

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

Mac-only follow-ups:

- A listener check via `lsof` (psutil `net_connections` needs root on macOS). Port 8765 was verified free with `lsof` in every wipe.
- A manual TCC prompt check on a desktop session.
- Trim the POSIX unlock wording (OBS-9).

**Machine state left:** branch build at 89a8c3c installed via `uv tool install`, `setup` done,
`com.contextengine.supervisor` loaded, `doctor` clean, this repo re-indexed, and Cursor, Kiro and
Copilot reconnected under the new project id. Throwaway repos (`/tmp/scu_*`) and `/tmp/hostsim` removed.
