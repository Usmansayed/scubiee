# Scubiee macOS Handoff — v0.3.162 (what was tested and fixed, 0.3.155 → 0.3.162)

**Machine:** macOS 26.5.2 (25F84), Apple M5, MLX (Metal) backend, Python 3.11.16,
uv 0.12.5, installed with `uv tool install scubiee` (tool venv under
`~/.local/share/uv/tools/scubiee`).

**State left behind:** 0.3.162 installed from PyPI, `setup` done, this repo
enrolled, engine running on `127.0.0.1:8765`, Cursor attached through
`scubiee-mcp-bridge`.

**Earlier detail:** bugs M1–M23 (root causes, commits, live evidence) and the
0.3.159 battery are in `docs/scubiee-macos-findings-0.3.155.md`. This handoff
summarizes them and adds M24–M27.

---

## 1. Releases in this pass

All were pushed straight to `main` and published to PyPI. Each one was then
reinstalled from PyPI and smoke-tested.

| Version | Commit | What shipped |
|---|---|---|
| 0.3.157 | 76a7d07, 17f9d3a | `doctor` no longer fails on finished (published) journal entries |
| 0.3.158 | e919f90, 88f73fd | `setup` model download bar no longer sits at 0% under hf_xet (M14) |
| 0.3.159 | 646c513 | Watchdog single instance, `remove`, `doctor`, CLI messages, download bar at 100% (M15–M23) |
| 0.3.160 | df68210 | `wipe`/`disconnect` remove legacy `context-engine` entries from every tool's MCP config (M24) |
| 0.3.161 | 9023c43 | `wipe` cleans stale Scubiee entries under both `mcpServers` and `servers` keys (M25) |
| 0.3.162 | 7f59507 | A crashed or stopped engine is restarted by the next `map find` call (M27) |

---

## 2. Bug register (this pass)

| ID | Sev | Area | Symptom | Root cause | Fix | Verified |
|---|---|---|---|---|---|---|
| M14 | med | setup | Download bar stuck at 0% for minutes, then jumps to done | hf_xet writes the 548 MB blob only at the end; the bar watched the blob size | e919f90 | live `setup` |
| M15 | low | setup | Download bar ends at 99% | byte watcher stopped without a final sample | c2c3f8d | live `setup` ends at 100% |
| M16 | high | watchdog | Two watchdog loops after `stop` | logon supervisor and engine sidecar both ran `watchdog_loop` | 1e20801, single-instance lock | live |
| M17 | high | remove | `remove` leaves `id.json`; keeper re-enrolls the repo | swallowed `NameError` (missing import); keeper ignored lifecycle | fa70aba, 01e055b | live |
| M18 | med | doctor | `replay dirty journal` failure after rebuild/upgrade/connect | in-flight / replay-on-start entries counted as stuck | 3d3731a | live |
| M19 | med | CLI | `scubiee test` outside a checkout crashes (no pytest) | ran pytest unconditionally | a02ad6f, exit 2 + hint | live |
| M20 | med | CLI | `register` / `engine ensure` on a never-index repo report ok or a generic bind error | no lifecycle check; refusal reason dropped | a02ad6f, b94ae97 | live |
| M21 | low | CLI / wipe | `--version` prints "Engine stopped"; wipe misses legacy `context-engine` entries | notice on every command; legacy name not stripped | 6cc848c, f10354d | regression tests |
| M22 | low | engine | Engine on an explicit store reloads the default store | freshness gate passed only the root | fdb1851 | `test_e2e_pipeline` |
| M23 | low | fixtures | 4 trace-lab quality tests always failed | `fixtures/trace-lab/app/models/user.py` swallowed by the `models/` ignore | 16e9221 | 11 → 7 failing |
| M24 | med | wipe | `wipe --all` exits 1: legacy `context-engine` entries left in global Copilot/Cline/Roo MCP configs | JSON/amp/opencode removers deleted only the `scubiee` key | 619f66d (+ 78b7bd5: tests no longer rewrite the developer's real configs) | live wipe, audit clean |
| M25 | med | wipe | `wipe --all` exits 1 every time on a VS Code `mcp.json` with a stale entry under `mcpServers` | the audit checked `mcpServers` and `servers`; the remover only checked one | 3df7f77 | live wipe, audit clean |
| M26 | low | tests | `test_e2e_pipeline` needs the real model cache | test used the real query embedder | 83ca8d2, stub embedder | test passes on a clean machine |
| M27 | high | MCP | With Cursor attached, every `map` failed instantly: `engine /v1/search failed: Connection refused` | (1) re-running `setup` re-registers the LaunchAgent, whose SIGTERM put the engine in standby while an IDE was attached; (2) the MCP worker never restarted a stopped engine; (3) a killed engine stayed a zombie, and `kill(pid, 0)` reported it alive, so the watchdog waited about 2 min | 22619f1: supervisor exit keeps the engine while an MCP client is attached; `map_v3_helpers._http` starts the engine once (locked) on connection refused and retries, while `/health` pulses never start it; the spawner reaps the engine and pid checks treat zombies as dead | live in Cursor + 4 new tests |

---

## 3. What was tested

### Live battery on 0.3.162 code (this repo, installed tool Python)

Lane A, `scripts/mcp_host_sim.py --lane a --live --settle-s 35`: `ok: true`,
no errors, 247.6 s total.

| Phase | ms | Phase | ms |
|---|---|---|---|
| clean_slate | 2,635 | map_second | 209 |
| host_start | 122 | status_first | 0.5 |
| auto_warm | 2,104 | pack_first | 26 |
| settle | 1,142 | expand_first | 130 |
| settle_join_embedder | 374 | idle_hold | 120,211 |
| map_first | 129 | post_idle_map | 242 |
| | | post_idle_pack | 25 |

- **`warm_contract`:** `failed: 0`. Embedder loaded before the first map, first
  map after ready 120 ms, map after idle 111 ms.
- **`ship_check`:** `ok`, 0 errors, 344 ms. `map` find/focus, the graph-fallback
  note and the bad-config error all ok.

### First-call timings in Cursor

| Measurement | Time |
|---|---|
| Engine warm on Cursor connect (MLX ready) | 4.1 s |
| Engine `/v1/search` direct | 65–107 ms |
| `scubiee map --config find` CLI (includes Python start-up) | 250–650 ms; 340–380 ms on 0.3.162; first run after reinstall 2.95 s (bytecode compile) |
| MCP `map` in Cursor | correct, high confidence; about 3 s in the agent UI, mostly host tool-call overhead |

### Engine-down recovery, live in Cursor

1. Kill the engine (`kill -9` on the 8765 listener) and confirm `/health` is down.
2. MCP `map focus` still answers. It uses the local graph and never needs the engine.
3. MCP `map find` starts a new engine (new pid, `warm_state: ready`) and returns
   the correct result with high confidence.

### Also exercised

- Fresh-machine sweep on 0.3.158: wipe, install, setup, init, every CLI command.
  This found M15–M21.
- `wipe --all` from a dirty machine for M24/M25: exit 0, audit clean.
- Reinstall from PyPI after each release, then `--version` and `map`.
- Unit tests: `tests/test_engine_down_recovery.py` (4) and
  `tests/test_lifecycle_runtime.py` all pass. The 4 new tests fail on the old code.

---

## 4. Not tested / open

- **Setup re-run while Cursor is attached (M27 trigger):** covered by a unit
  test, not re-run live end to end.
- **Not run live:** Mac sleep/wake or reboot/logon with Cursor open; several
  IDE windows sharing one engine; two `find` calls hitting a dead engine at the
  same moment (guarded by `_RECOVER_LOCK`).
- **Not covered:** large repos, low memory, first-time `setup` without network.
  Windows and Linux were not re-validated for 0.3.156–0.3.162. The M27 changes
  touch shared code (`map_v3_helpers`, `lifecycle_runtime`, `watchdog`,
  `daemon`); `pid_is_zombie` is a no-op on Windows.
- **Environment-dependent test failures:** `test_mcp_restore` and
  `test_upgrade_scenarios` (×2) fail when `~/.scubiee` does not exist. They
  predate this pass.
- **Remaining trace-lab corpus-quality failures:** 7, all pre-existing, not
  investigated.
- **Known cosmetic issues on all OSes:** #7 re-running `init` prints "already
  indexed" over a stale "Starting…" line; #8 bare `scubiee` in a pipe prints the
  argparse error.

---

## 5. Re-verify quickly

```bash
uv tool install --force --refresh "scubiee==0.3.162"
TOOL_PY=$HOME/.local/share/uv/tools/scubiee/bin/python
cd /path/to/context-engine        # enrolled with `scubiee init .`
"$TOOL_PY" scripts/mcp_host_sim.py --lane a --live --settle-s 35 --out-dir /tmp/hostsim
"$TOOL_PY" scripts/warm_contract_acceptance.py
"$TOOL_PY" scripts/scubiee_mcp_ship_check.py
git checkout docs/superpowers/plans/2026-09-06-mcp-ship-check.json   # ship_check rewrites it
```

Engine-down check with an IDE attached: `kill -9 $(lsof -ti tcp:8765 -sTCP:LISTEN)`,
then run one MCP `map find`. It should answer, and `/health` should show a new pid.

**Notes:**
- Lane A's `clean_slate` re-initialises the repo and can delete the
  init-generated `.kiro/*` files. Run `scubiee init .` afterwards, and don't
  commit init-generated `AGENTS.md`, `.copilot/*` or `.kiro/*` changes.
- In-repo test runs need `PYTHONPATH=packages`. Installed-tool runs must not set it.
