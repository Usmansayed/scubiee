# Watchdog Lifecycle Hardening Implementation Plan

> **For agentic workers:** Execute inline in this session (user required one-session completion). Steps use checkbox syntax.

**Goal:** Reliable MCP↔watchdog↔engine lifecycle: no mcp.json rewrite storms, silent spawns, demand-driven engine, one warm path, verified disconnect unload.

**Architecture:** Keep supervisor-owned engine spawn. Treat `pipeline.mcp_bridge` as a live MCP pin. Engine start must not mutate IDE config. Discover watchdog by cmdline when the pid file is missing.

**Tech Stack:** Python package `pipeline`, pytest, Windows Job/WMI, LaunchAgent, systemd user.

**Spec:** `docs/architecture/watchdog-mcp-lifecycle.md` + `docs/architecture/watchdog-root-causes.md`

## Global Constraints

- No PowerShell/cmd WMI wrappers
- Default spawn: soft `CREATE_NO_WINDOW` / pythonw for background; no `DETACHED_PROCESS` unless explicit env
- MCP path always `spawn_owner=supervisor`
- Engine process must not rewrite `mcp.json`
- Do not claim fixed without recorded verification
- Version 0.3.68 after this cluster

---

## File map

| File | Change |
|------|--------|
| `packages/pipeline/mcp_restore.py` | Live launcher includes `pipeline.mcp_bridge`; skip vscdb scan on no-op |
| `packages/pipeline/daemon.py` | Remove `heal_mcp_pins_if_stubbed` from `start_daemon` |
| `packages/pipeline/watchdog.py` | Cmdline discover; start_request is demand |
| `packages/pipeline/lifecycle_runtime.py` | `engine_should_be_running` honors start_request |
| `packages/pipeline/mcp_install.py` | `windowsHide: true` on Windows server_entry |
| `packages/pipeline/process_job.py` | Keep job handles; strip debug blink |
| `packages/pipeline/process_control.py` | Durable boot-script identity; hidden wmic fallback; strip debug |
| `packages/pipeline/mcp_bridge.py` / `silent_spawn.py` / `freshness.py` / `project_id.py` | Strip `_debug_blink` |
| `tests/test_mcp_restore.py` | Live pythonw+bridge pin |
| `tests/test_watchdog_lifecycle_contract.py` | New contracts |

---

### Task 1: False-positive pin restore (Problem G)

- [x] Document diagnosis
- [x] Test: pythonw `-m pipeline.mcp_bridge` does **not** need restore
- [x] Implement live-launcher markers
- [x] Remove heal from `start_daemon`
- [x] No-op restore does not walk `state.vscdb`

### Task 2: Terminal silence leftovers (Problem A)

- [x] `windowsHide: true` on Windows MCP entry
- [x] wmic fallback uses `hidden_run`
- [x] Remove `_debug_blink` from production hot paths
- [x] pythonw stdio initialize round-trip

### Task 3: Demand-driven watchdog (Problems C+D)

- [x] `engine_should_be_running` true if start_request exists
- [x] Skip stale start_request (>180s, no clients)
- [x] `discover_watchdog_pid` via `_boot_watchdog.pyw` / supervisor boot
- [x] Hold Windows job handles in a module list

### Task 4: Verify disconnect unload (no rewrite)

- [x] Run existing idle / disconnect tests

### Task 5: Simulation + compatibility

- [x] Lifecycle sim still passes (74 tests including stay-alive child + cooldown)
- [x] Matrix: Win real (install + pin + pythonw); macOS/Linux/tool hosts simulated
- [ ] Live Cursor reconnect in an enrolled Scubiee repo (blocked: this workspace mcp.json is Figma-only)

---

## Out of scope

- Redesigning embedder / FAISS
- Changing locate algorithm quality
- UI/dashboard work
- Connecting Scubiee MCP into this workspace’s `.cursor/mcp.json` (currently Figma-only by user config)
