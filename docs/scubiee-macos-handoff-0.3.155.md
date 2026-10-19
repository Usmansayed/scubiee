# Scubiee macOS Handoff — v0.3.155 (delta since the 0.3.152 pass)

**You are:** an autonomous coding agent on a **macOS** machine (say whether it's
Apple Silicon or Intel) with a terminal and, ideally, the `@scubiee/*` MCP tools
connected.

**Your job:** macOS validated 0.3.149→0.3.152
(`docs/scubiee-macos-findings-0.3.152.md`). Since then Windows and a Linux
container shipped 0.3.153→0.3.155. Test **only the changes whose code path or
behavior can differ on macOS**. Platform-agnostic changes get a one-line smoke at
most. Fix macOS-specific breakage on a branch and write a short findings doc.

**Authority:** yes to install, run, test, edit code, rebuild, commit on a branch.
Do **not** push or open PRs unless asked. Destructive commands (`wipe`, `remove`,
`halt`) are expected in §3 and §8 — this handoff exists partly to test them.
Run them only on this machine's Scubiee install and throwaway repos.

**Deliverable:** `docs/scubiee-macos-findings-0.3.155.md` (template in §9).

**Rule for reliability claims:** do not call a wipe/warm/MCP area green on unit
tests alone. The release batteries in §7 must pass live, and you report their
measured timings and ok flags.

---

## 0. What changed since 0.3.152

Full write-ups (root cause, fix, Windows/Linux evidence):
`docs/real-user-journey-fixes.md`, one section per issue number.

| # | Ver | Change | Mac risk |
|---|-----|--------|----------|
| L | 0.3.153 | New progress loaders: logo, "Analysing repository size" spinner, per-stage bars in `setup` / `init` / `wipe` | **medium** — terminal rendering differs (Terminal.app vs iTerm2, `\r` redraws, Unicode spinner glyphs) |
| 1 | 0.3.154 | `wipe --all` no longer exits 1 ("quit Cursor…") on a clean machine; stopping never recreates `~/.scubiee` | **medium** — the IDE-lock / remaining-files audit is OS-specific |
| 2 | 0.3.154 | `doctor`/`setup` no longer report a second install on a plain `uv tool install` (`env_guard.current_python()` no longer resolves the venv `python` symlink) | **high** — macOS venvs are symlinked like Linux, plus `/var`→`/private/var`, Homebrew and uv-managed Pythons. Only tested on Linux |
| 3 | 0.3.154 | `scubiee sync` waits for its own poll to finish instead of returning `deferred` | low — smoke only |
| 4 | 0.3.154 | `init` time estimate = work ÷ this machine's measured embed speed (`~/.scubiee/embed_throughput.json`) | **high** — speed comes from MLX/CoreML on Mac; calibrated only on CPU and DirectML |
| 5 | 0.3.154 | `resume` no longer hangs ~90 s with the engine silently failing to start | **medium** — engine spawn/launchd path differs on Mac |
| 6 | 0.3.154 | `connect` / `resume` report only paths that were actually written | low–medium — Cursor/Claude config locations on Mac |
| 10 | 0.3.155 | `wipe --all` fast path: never walks home; pruned repo scan; sleeps only when something was killed; `~/.scubiee` + model caches renamed aside and deleted by a detached `/bin/sh` cleaner after the CLI exits | **high** — the POSIX cleaner, macOS home layout / TCC prompts and the process check are all Mac-specific (details in §3) |
| 11 | 0.3.155 | `map focus` by bare name ~120 ms again (was ~1.3 s): the grep prefilter now handles lookaround/char-class patterns | low — pure Python; just record the timing |

Nothing in this delta changed the embedder, MLX, warm sequence, graph lane or
launchd supervisor. If those were green in the 0.3.152 findings, only re-check
them if §7 surprises you.

---

## 1. Environment + install 0.3.155 from PyPI

```bash
sw_vers; uname -m; python3 --version; uv --version
scubiee engine stop 2>/dev/null || true
uv tool install --force --refresh "scubiee==0.3.155" --index-url https://pypi.org/simple
scubiee --version                       # expect 0.3.155
ls -la "$(command -v scubiee)"          # record the symlink target
TOOL_PY="$(dirname "$(readlink -f "$(command -v scubiee)")")/python"; echo "$TOOL_PY"
"$TOOL_PY" -c "import sys; print(sys.executable)"; ls -la "$TOOL_PY"
```

> Do NOT use `packaging/uv-overrides-win-dml.txt` on macOS (Windows-only; it strips `onnxruntime`).

- **[ ] PASS/FAIL** version 0.3.155.
- **[ ] OBS** the `scubiee` symlink target and the chain behind `$TOOL_PY` — needed for §2.

---

## 2. #2 — install identity on symlinked venvs (high)

```bash
scubiee setup 2>&1 | tee /tmp/scu_setup.log      # also watch the loaders (§6)
grep -i "another scubiee install" /tmp/scu_setup.log && echo "FALSE POSITIVE" || echo "no note"
"$TOOL_PY" -c "import json; from pipeline.env_guard import install_identity_report as r; print(json.dumps(r(), indent=1))"
scubiee doctor 2>&1 | grep -iE "multiple_installs|binaries_match|expected"
```

- **[ ] PASS/FAIL** setup prints no "another scubiee install found" note.
- **[ ] PASS/FAIL** `multiple_installs: false`, `binaries_match: true`; the expected
  binary sits under `~/.local/share/uv/tools/scubiee/bin/`.
- **[ ] PASS/FAIL (negative)** a real second copy is still detected:
  `python3 -m venv /tmp/scu_venv && /tmp/scu_venv/bin/pip install -q scubiee==0.3.155`,
  then rerun the identity report from `$TOOL_PY`. It should flag the venv copy.
  (Don't run `connect`/`setup` from the venv — it would try to consolidate.)
- Code: `env_guard.current_python()` uses `Path(sys.executable).absolute()`.
  Mac-specific worry: a Homebrew/framework Python whose `sys.executable` already
  points outside the venv. Note what you see.
- Unit: `PYTHONPATH=packages python3 -m pytest tests/test_env_guard.py -q`. The
  symlink test skips on Windows, so **macOS is the second real run of it**.

---

## 3. #10 + #1 — `wipe --all` speed and correctness (high, run after §7)

Run this section **after** the batteries in §7 (it removes the install), then
reinstall for §8. What differs on Mac:

- **Background cleaner.** On POSIX, `process_control.schedule_delete_paths_after_exit`
  spawns `/bin/sh -c 'while kill -0 <cli pid>; do sleep 0.2; done; rm -rf <trash>'`
  with `start_new_session=True`. The trash dirs are `<name>.trash-<pid>` next
  to the originals.
- **Home layout.** `_is_broad_root` treats home, its ancestors (`/Users`, `/`) and
  drive roots as "never walk". Running from `~` should not trigger macOS privacy
  (TCC) prompts for Desktop/Documents/Downloads. The old `rglob` from home would
  have walked into them.
- **Process check.** `_anything_scubiee_running` uses process enumeration, then
  `pids_listening_on_port(8765)`. On macOS `psutil.net_connections()` usually
  raises `AccessDenied` without root, and the code then returns **no listeners**.
  So on Mac the fast path relies on process-name matching only. Verify a running
  engine is still killed (3b).
- **Model caches.** MLX/HF model folders are also renamed aside; confirm they're
  on the same volume (`rename` across volumes fails and should fall back to an
  in-place delete — note if that happens).

### 3a. Clean wipe from home, timed
```bash
cd ~ && time scubiee wipe --all --confirm; echo "exit=$?"
ls -d ~/.scubiee* ~/.local/share/uv/tools/scubiee 2>&1
sleep 3; ls -d ~/.scubiee.trash-* ~/.cache/*trash-* 2>/dev/null || echo "trash drained"
pgrep -fl "scubiee|pipeline\.(mcp_bridge|engine|server)" || echo "no procs"
command -v scubiee || echo "scubiee gone"
launchctl list | grep -i contextengine || echo "no launchd job"   # label: com.contextengine.supervisor
```
- **[ ] PASS/FAIL** exit 0, final JSON `"audit": {"clean": true}`, `"next": "Machine is clean…"`.
- **[ ] PASS/FAIL** wall time — Windows was 11.6 s from an empty folder, Linux 3.8 s
  from a home holding a 300k-file `node_modules`. Report the Mac number.
- **[ ] PASS/FAIL** no TCC privacy prompt appeared.
- **[ ] PASS/FAIL** trash drained within a few seconds; no `sh` cleaner left behind
  (`pgrep -fl "kill -0"`).
- **[ ] PASS/FAIL** launchd agent removed (the plist under `~/Library/LaunchAgents/` is gone).

### 3b. Wipe while the engine is running (process check without net_connections)
Reinstall + `setup` + `scubiee init` on a small throwaway repo
(`git clone --depth 1 https://github.com/psf/requests /tmp/scu_req`), start the
engine (`scubiee engine start`), confirm `curl -s 127.0.0.1:8765/health`, then:
```bash
cd /tmp/scu_req && time scubiee wipe --all --confirm; echo "exit=$?"
curl -s -m 2 127.0.0.1:8765/health || echo "engine gone"
lsof -nP -iTCP:8765 -sTCP:LISTEN || echo "port free"
```
- **[ ] PASS/FAIL** engine killed, port 8765 free, exit 0, audit clean.
- **[ ] OBS** in the wipe JSON, was `fast_path: nothing_running` taken anywhere it
  shouldn't have been?

### 3c. Reinstall right after the wipe
```bash
uv tool install --force "scubiee==0.3.155" --index-url https://pypi.org/simple && scubiee setup
```
- **[ ] PASS/FAIL** works immediately (the trash rename should leave no conflict).

Unit: `PYTHONPATH=packages python3 -m pytest tests/test_wipe_speed.py tests/test_wipe.py -q`.

---

## 4. #4 — `init` estimate on MLX/CoreML (high)

```bash
cat ~/.scubiee/embed_throughput.json 2>/dev/null || echo "no measured speed yet"
cd /tmp && rm -rf scu_flask && git clone --depth 1 https://github.com/pallets/flask scu_flask
cd scu_flask && time scubiee init .      # note the "est. ~X" in the prompt; accept it
cat ~/.scubiee/embed_throughput.json
cd /tmp && rm -rf scu_req2 && git clone --depth 1 https://github.com/psf/requests scu_req2
cd scu_req2 && time scubiee init .       # second estimate now uses the measured speed
```
- **[ ] PASS/FAIL** the first estimate (setup calibration only) brackets the real time.
- **[ ] PASS/FAIL** after flask, `embed_throughput.json` holds a sane MLX chunk/s
  (it records only runs of 64+ fresh chunks).
- **[ ] PASS/FAIL** the second estimate brackets requests' real time.
- Reference (8-CPU Linux container): flask said ~5–9 min, took 5.4 min; requests
  said ~4–6 min, took 3.8 min. On Apple Silicon expect much shorter times, under
  a minute shown as "<1 min". **The risk:** setup's single-threaded calibration
  may badly misjudge MLX batch speed (estimate wildly high), or the
  0.8–1.25× band may be wrong for Metal. Report estimate vs real for both repos.
- Code: `cli_ui.format_index_eta`, `workload.machine_embed_cps`, `incremental.scope_bytes`.

---

## 5. #5 / #6 / #3 / #1 — quick Mac checks

```bash
cd /tmp/scu_flask
scubiee stop && time scubiee resume; echo "exit=$?"     # #5: should not hang ~90 s
curl -s 127.0.0.1:8765/health | head -c 300; echo
scubiee connect --cursor 2>&1 | tee /tmp/scu_connect.json  # #6
echo "# edit" >> src/flask/helpers.py && time scubiee sync . # #3: should NOT say deferred
scubiee search "helpers edit marker" | head -20; git checkout src/flask/helpers.py
```
- **[ ] PASS/FAIL #5** `resume` returns promptly (Linux: was 91 s), `engine.ok: true`,
  engine healthy afterwards. Note whether launchd or a direct spawn started it.
- **[ ] PASS/FAIL #6** every path in `mcp_paths` / `rule_paths` of the connect
  output **exists** (`ls` each), sits inside the repo, and isn't a bare
  `/.cursor/...` or a never-written global rule.
- **[ ] PASS/FAIL #3** `sync` reports a refreshed (not `deferred`) result and the
  change is searchable right away.
- **[ ] PASS/FAIL #1** with **Cursor open**, run `scubiee wipe --all` (no
  `--confirm`; it prompts Y/N) and answer **N**. Does the IDE-lock pre-flight
  warning detect Cursor on Mac ("Cursor" / "Cursor Helper" process names)?
  Report what it printed; don't actually wipe here.

---

## 6. L — loaders in real Mac terminals (medium)

Watch `scubiee setup`, `scubiee init`, `scubiee wipe --all` in **Terminal.app** and,
if present, **iTerm2** (and Cursor's integrated terminal):

- **[ ] PASS/FAIL** logo renders; spinner glyphs are not boxes/`?`.
- **[ ] PASS/FAIL** spinners/bars redraw in place (no hundreds of stacked lines,
  no leftover half-lines when a stage ends).
- **[ ] PASS/FAIL** piped output (`scubiee init . | cat`) prints plain lines, no
  escape codes; `NO_COLOR=1` disables colour.
- **[ ] PASS/FAIL** a narrow window (`printf '\e[8;24;60t'` or resize to ~60
  columns) doesn't wrap the bar into garbage.
- Known open on all OSes (don't file again): #7 re-running `init` prints "already
  indexed" over an uncleared "Starting…" line; #8 bare `scubiee` in a pipe prints
  the argparse error; #9 `--version` on a fresh machine says "Engine stopped".

---

## 7. Release batteries on macOS (required)

Use a checkout of this repo, **enrolled and indexed** (`scubiee init .` in the
repo root), with the **installed tool's** Python (no `PYTHONPATH`). Write
host-sim reports **outside the repo** — the default writes into
`docs/superpowers/plans/`, so the next run starts by re-indexing that report
right when the locate calls are timed (this caused false Lane A failures on
Windows).

```bash
cd /path/to/context-engine
mkdir -p /tmp/hostsim
"$TOOL_PY" scripts/mcp_host_sim.py --lane a --live --settle-s 35 --out-dir /tmp/hostsim; echo "exit=$?"
"$TOOL_PY" scripts/mcp_host_sim.py --lane a --live --settle-s 35 --out-dir /tmp/hostsim; echo "exit=$?"   # clean 2nd run
"$TOOL_PY" scripts/warm_contract_acceptance.py; echo "exit=$?"
"$TOOL_PY" scripts/scubiee_mcp_ship_check.py; echo "exit=$?"
git checkout docs/superpowers/plans/2026-09-06-mcp-ship-check.json   # ship_check rewrites this tracked file
```

Windows reference (0.3.155, this repo, DirectML, engine capped to 6/16 CPUs):

| Phase / check | Budget | Windows |
|---|---|---|
| Lane A `map_first` (after 35 s settle) | ≤3 s | 781–1,045 ms |
| Lane A `map_second` (new query) | ≤1 s | 962–979 ms — **thin margin** |
| Lane A `pack_first` (= `map focus`, bare name) | ≤1 s | 116–117 ms (was 1,322 ms before #11) |
| Lane A `expand_first` (served as `find`) | ≤1 s | 664–810 ms |
| Lane A `post_idle_map` / `post_idle_pack` (after 120 s idle) | ≤1 s | 442–750 / 115–122 ms |
| `warm_contract` | 6 checks | 6/6; warm 6.0 s; first map 1,322 ms; map after idle 426 ms |
| `ship_check` | ok | ok, 3 tools, 0 errors |

- **[ ] PASS/FAIL** Lane A exit 0 with every phase `ok=True`, both runs. Paste the
  `phase …: ok= ms=` lines.
- **[ ] PASS/FAIL** warm_contract `"failed": 0`; ship_check `"ok": true`.
- **[ ] OBS — the open question from Windows:** a `find` with a new query is
  260–600 ms steady but 800–1,000 ms in the first minute after the engine starts,
  with spikes to ~2.8 s while the engine hot-syncs a changed file (GIL contention
  in the engine). Is Apple Silicon comfortably under 1 s, or equally tight?
  If tight, run the engine search directly and report `timings` (`embed_ms`,
  `retrieve_ms`, `total_ms`) vs the HTTP wall time. On Windows the engine
  reported ~430 ms total but the wall time was ~1,100 ms during startup:
  ```bash
  curl -s -XPOST 127.0.0.1:8765/v1/search -H 'Content-Type: application/json' \
    -d "{\"query\":\"sqlite vector store upsert $(date +%s)\",\"top_k\":12,\"path\":\"$PWD\"}" \
    -w '\nwall=%{time_total}s\n' | tail -c 600
  ```
- Note: with no MCP client attached the engine goes to standby after a ~10 s
  debounce. Bare `curl` loops lose the engine mid-run; that's by design. Keep a
  bridge attached (or run inside a host-sim) for longer probes.

---

## 8. Teardown

```bash
cd ~ && scubiee wipe --all --confirm     # second timed wipe; record the time
rm -rf /tmp/scu_venv /tmp/scu_flask /tmp/scu_req /tmp/scu_req2 /tmp/hostsim /tmp/scu_*.log /tmp/scu_connect.json
cd /path/to/context-engine && git status   # no stray artifacts; restore any tracked files the wipe/connect touched
```
Then reinstall + `setup` if you want the Mac left in a working state, and say which state you left it in.

---

## 9. Deliverable — `docs/scubiee-macos-findings-0.3.155.md`

1. **Environment:** macOS version, chip, backend (MLX/CoreML/CPU), Python, uv, install method.
2. **§7 batteries first:** every phase's ok/ms for both Lane A runs, warm_contract,
   ship_check, plus the `find` latency answer.
3. **Per-delta results** §2–§6: PASS/FAIL/OBS/N-A with real output. Lead with
   §3 (wipe) and §2 (install identity).
4. **Bug register** (table): ID, severity, area, summary, root cause, fix (commit
   on your branch), status.
5. **Verdict:** does 0.3.155 behave correctly on macOS? Any Mac-only follow-up
   (e.g. a non-`net_connections` listener check via `lsof`)?

### Priorities if short on time
1. §7 batteries (required for any green claim).
2. §3 wipe (3a + 3b).
3. §2 install identity.
4. §4 init estimate on MLX.
5. §5 and §6.

---

## Appendix — key facts
- **Version:** 0.3.155 on PyPI. **Engine:** `127.0.0.1:8765`.
- **Shipped MCP tools:** `map` (config `find`|`focus`), `gate`, `status`.
- **Backends:** Mac MLX (Metal) on Apple Silicon, CoreML/CPU on Intel; Windows DirectML.
- **Code for this delta:** `wipe.py` (`_discover_repo_id_dirs`, `_is_broad_root`,
  `_looks_like_repo`, `_rm_tree_background`), `process_control.py`
  (`_anything_scubiee_running`, `schedule_delete_paths_after_exit`,
  `pids_listening_on_port`), `env_guard.py` (`current_python`), `cli_ui.py` +
  `workload.py` (estimate), `pause_resume.py` / `lifecycle_guard.py` (resume),
  `rules_installer.py` (`_summarize_fan_out_paths`), `map_v3_helpers.py`
  (`_pattern_prefilter`), `mcp_host_sim/` (harness).
- In-repo test runs need `PYTHONPATH=packages`; installed-tool runs must NOT set it.
