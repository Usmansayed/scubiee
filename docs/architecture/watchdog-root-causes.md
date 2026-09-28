# Watchdog / MCP Lifecycle — Root Cause Diagnosis

> Evidence-backed. Do not “fix” items here without updating verification.
> **Date:** 2026-09-12 | **Codebase:** 0.3.68 (fixes) / 0.3.67 (broken live state)

## Research inputs

### Windows console flashing (official / industry)

- Microsoft: `CREATE_NO_WINDOW` runs a console app **without** a console window; **ignored** if combined with `DETACHED_PROCESS` ([Process Creation Flags](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags)).
- Practical rule: **one shared helper** (`hidden_run`) for all Windows console tools; never raw `Popen` of `taskkill`/`schtasks`/`wmic`/`python.exe` without hide flags. Prefer `pythonw` + `.pyw` for **background** roles (watchdog/engine), not as a substitute for fixing host reconnect loops.

### MCP stdio lifecycle

- Spec: host launches server; shutdown closes stdin; unexpected exit → **restart** ([MCP stdio 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports), [2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio)).
- Python SDK uses job objects on Windows to kill process trees on terminate (`KILL_ON_JOB_CLOSE`).
- Cursor: rewriting `mcp.json` fires `config_server_modified` → `DeleteClient`/`CreateClient` within milliseconds; a server that is still starting is SIGKILL’d.

### macOS / Linux supervisors

- LaunchAgent: `KeepAlive` + `ThrottleInterval` (default 10s, we set 15) + `ProcessType=Background`.
- systemd user: `Restart=on-failure` (not `always`) so intentional supervisor exit is not a restart storm.

---

## Problem G — LIVE ROOT CAUSE (0.3.67): false-positive MCP pin restore

| | |
|--|--|
| **What** | Watchdog spawned every ~20–40s then **dies during `start_daemon`** (log has `requested start` and never `requested start result` / `exited`). Terminals blink / MCP reconnects continuously. Engine may survive as a Windows orphan. |
| **Why** | 0.3.67 changed Windows `mcp.json` to `pythonw -m pipeline.mcp_bridge`. `mcp_entry_needs_restore()` only treated `scubiee-mcp` / `pipeline.mcp_locate` / `pipeline.mcp_server` as live — **not** `pipeline.mcp_bridge`. Every `start_daemon()` called `heal_mcp_pins_if_stubbed()` → `restore_live_mcp_pins()` → `rebind_mcp_and_rules()` **rewrote every enrolled repo’s mcp.json**. Cursor’s file watcher restarted MCP (spec-required restart on unexpected exit). MCP `ensure_supervisor_detached` (20s cooldown) spawned another watchdog. Cycle. |
| **Where** | `packages/pipeline/mcp_restore.py` `mcp_entry_needs_restore`; `packages/pipeline/daemon.py` `start_daemon` heal hook |
| **Evidence** | 2026-09-12 live `~/.scubiee/watchdog.log`: eight silent-orphan spawns 16:17–16:25, each `requested start repo=claude-code-proxy` with no result. `watchdog.pid` missing. `claude-code-proxy/.cursor/mcp.json` command is pythonw + `pipeline.mcp_bridge`. This workspace’s Scubiee MCP tools were not even loaded (project `.cursor/mcp.json` is Figma-only). |
| **Fix** | (1) Treat `pipeline.mcp_bridge` as a live launcher. (2) **Never** call pin restore from `start_daemon` — engine must not mutate IDE config. (3) No-op restore path must not walk Cursor `state.vscdb`. |
| **Tests** | `tests/test_mcp_restore.py` live pythonw+mcp_bridge pin; `tests/test_daemon_does_not_heal_mcp.py` source/contract. |

## Problem A — Terminal blink storm

| | |
|--|--|
| **What** | Consoles open/close continuously |
| **Why** | (1) **Problem G reconnect loop** (primary on 2026-09-12). (2) Console helpers without `CREATE_NO_WINDOW`. (3) uv `scubiee-mcp-bridge.EXE` console shims. (4) `DETACHED_PROCESS` grandchild consoles. (5) Debug `_debug_blink` / `wmic` fallback without hide flags. |
| **Where** | `mcp_restore` false positive; `process_control.processes_under` wmic fallback; historical taskkill/schtasks |
| **Evidence** | Microsoft docs; Claude Code issues #24708/#14828; live watchdog spawn cadence matching `_ENSURE_SUPERVISOR_COOLDOWN_S=20`. Wipe-without-MCP previously showed `flash_hits=0` — blinks require the MCP host restart loop. |
| **Fix** | Stop mcp.json rewrite storms; keep `hidden_run`/`taskkill_silent`; `windowsHide: true` in server_entry; remove production `_debug_blink` hooks; wmic fallback via `hidden_run`. |
| **Tests** | Restore live-pin test; silent spawn tests; no `_debug_blink` in hot paths. |

## Problem B — Engine not warm after wipe

| | |
|--|--|
| **What** | Engine process up but `warm=false` / `index_usable=false` |
| **Why** | Wipe cleared enrollment; HTTP process ≠ repo ready |
| **Where** | `daemon.start_daemon` vs MCP `warm_engine_for_mcp` + register |
| **Fix** | MCP warm still `open_repo` + register; do not confuse with Problem G |
| **Tests** | Existing lifecycle / MCP warm tests |

## Problem C — Engine kept running with no MCP clients

| | |
|--|--|
| **What** | Watchdog force-restarts engine forever while no IDE is connected |
| **Why** | Sticky `desired_mode=run` + `last_client_left_at: null` (0.3.66 partial fix). Stale `active_clients.json` PID if reconcile is not invoked. |
| **Where** | `should_idle_stop`, `engine_should_be_running`, watchdog demand gate |
| **Evidence** | Live 2026-09-12: `desired_mode=run`, `last_client_left_at: null`, client `mcp:cursor@proc-12328` |
| **Fix** | Keep sticky-idle (0.3.66). `engine_should_be_running` also true for pending `engine.start_request`. Reconcile drops dead PIDs (`_client_is_stale`). Skip start_request older than 180s when `active_client_count()==0` (`start_request_is_actionable`). |
| **Tests** | `tests/test_idle_no_clients_standby.py`; start_request demand + stale-skip tests |

## Problem D — Duplicate ensure / process churn

| | |
|--|--|
| **What** | Repeated ensure on every tool call; extra watchdog spawns |
| **Why** | Multiple ensure sites + Problem G making `is_watchdog_running()` false (dead pid file) |
| **Fix** | Keep MCP ensure TTL; discover watchdog by cmdline (`_boot_watchdog.pyw`) when pid file missing |
| **Tests** | `tests/test_mcp_ensure_coalesce.py`; watchdog discover test |

## Problem E — Cursor close kills engine (historical)

| | |
|--|--|
| **What** | Close Cursor → engine dead until manual start |
| **Why** | Watchdog parented by MCP → job KILL_ON_JOB_CLOSE |
| **Fix** | Keep WMI orphan; hold job handles so GC cannot close them; do not put watchdog in MCP kill job |
| **Tests** | Existing ownership tests; job handle leak test |

## Problem F — Cross-tool / cross-OS gaps

| | |
|--|--|
| **What** | Must work Cursor, Claude Code, Codex, … on Win/mac/Linux |
| **Why** | Different mcp.json locations; Windows-only console; LaunchAgent vs systemd |
| **Fix** | `windowsHide` for hosts that honor it; simulate Darwin/Linux register in unit tests; document untested hosts |
| **Tests** | Parametrized launcher recognition; existing register mocks |

---

## Priority order (this session)

1. **Problem G** — false-positive restore + remove heal from `start_daemon` (stops the live storm)
2. **Problem A leftovers** — debug hooks, wmic hide, `windowsHide`
3. **Problem C/D** — start_request as demand; watchdog cmdline discovery
4. **Verify disconnect unload** (no rewrite)
5. **Full simulation + compatibility matrix**

## What we will NOT do

- Random drive-by refactors unrelated to the component in progress
- Reintroduce PowerShell/cmd WMI wrappers
- Claim “fixed” without tests + runtime checks recorded below

## Verification log

| Date | Check | Result |
|------|-------|--------|
| 2026-09-12 | Live watchdog.log spawn storm + missing pid + pythonw mcp_bridge pin | CONFIRMED Problem G |
| 2026-09-12 | `mcp_entry_needs_restore` on pythonw `-m pipeline.mcp_bridge` | FAIL on 0.3.67 → **PASS on 0.3.68** (live claude-code-proxy pin `needs_restore=False`) |
| 2026-09-12 | `start_daemon` must not call `heal_mcp_pins_if_stubbed` | FAIL on 0.3.67 → **PASS** (`tests/test_watchdog_lifecycle_contract.py`) |
| 2026-09-12 | Lifecycle cluster (restore, idle, disconnect, sim, watchdog, silent spawn, just-works) | **67 passed** |
| 2026-09-12 | Isolated `watchdog_loop(stop_after=2)` + subprocess stay-alive | **PASS** started+exited, pid cleared |
| 2026-09-12 | pythonw MCP initialize JSON-RPC round-trip | **PASS** (`tests/test_pythonw_mcp_stdio.py`) |
| 2026-09-12 | Lifecycle cluster after stale-request gate | **74 passed** |
| 2026-09-12 | Installed uv tool 0.3.68 (reinstalled after stale-request gate) | **PASS** |
| 2026-09-12 | Live leftover cleanup (dead client 12328, start_request, lock pid 6780) | **PASS** — `desired_mode=standby`, no engine/watchdog RSS |
| 2026-09-12 | Live mcp.json rewrite after 0.3.68 | **NONE** — pin mtime still 2026-09-12 16:25:42; `needs_restore=False` |
| 2026-09-12 | Watchdog spawn storm after 16:25 | **STOPPED** (no new log lines; MCP in this window was never Scubiee) |
| 2026-09-12 | This Cursor window Scubiee MCP tools | **NOT CONNECTED** (workspace `.cursor/mcp.json` is Figma-only) |
| 2026-09-12 | macOS / Linux / Claude Code / Codex live hosts | **NOT TESTED** (unit/simulated only) |
