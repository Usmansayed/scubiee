# Scubiee Watchdog ↔ MCP ↔ Engine Lifecycle Architecture

> Living document. Updated as we investigate, fix, and verify.
> **Package version:** 0.3.69
> **Last updated:** 2026-09-12

## 1. Purpose

Scubiee must feel like “open the IDE and it just works”:

1. MCP connects → durable supervisor + warm engine ready for locate.
2. While connected → keep readiness; manage RAM/CPU (demote embedder when safe).
3. MCP disconnects → after debounce, unload embedder and stop the engine process.
4. Never flash console windows or spawn process storms.
5. Work on Windows, macOS, Linux across Cursor / Claude Code / Codex / etc.

## 2. Process roles (logical)

| Role | What it is | Parent should be | Dies when |
|------|------------|------------------|-----------|
| **MCP bridge** | `python -m pipeline.mcp_bridge` (Windows: `pythonw` + `windowsHide`) | IDE (Cursor, …) | IDE closes MCP |
| **MCP worker** | `pipeline.mcp_locate` | Bridge (job w/ KILL_ON_JOB_CLOSE) | Bridge dies |
| **Supervisor / watchdog** | `watchdog_loop` via `_boot_watchdog.pyw` / `_boot_supervisor.pyw` | OS (WMI / LaunchAgent / systemd / HKCU Run→pythonw) — **never MCP** | Logoff / explicit stop |
| **Engine** | HTTP server `:8765` | Supervisor child | Idle standby / stop / job close |

**Invariant (Windows):** If the watchdog is parented by MCP, Cursor close → MCP dies → watchdog dies → job `KILL_ON_JOB_CLOSE` → **engine killed**. Orphan spawn exists to break that chain.

**Invariant (all hosts):** The engine process must **never rewrite IDE `mcp.json`**. Pin restore belongs to `connect` / `upgrade` / `setup`. Engine start that mutates MCP config causes the host to kill and respawn the stdio server (spec: unexpected exit → restart).

## 3. End-to-end flow

```
scubiee connect / setup
  → install_session_runtime()
      → register_logon_autostart()   # OS-specific, silent
      → ensure_supervisor()          # detached on Windows

IDE starts MCP (mcp.json)
  → bridge (CREATE_NO_WINDOW children)
  → mcp_locate.main / boot_mcp_worker
      → attach_mcp_session (leave hooks only; **no engine spawn**)
      → advertise tools

Agent first gate / status / map
  → ensure_mcp_runtime → warm_engine_for_mcp(blocking=True)
      → note_engine_start_request()
      → set_desired_mode(run)
      → ensure_supervisor_detached()
      → poll /health
      → /v1/client/register + embedder

CTX_MCP_AUTO_WARM=1 restores the old connect-time ensure_daemon + background warm.

Watchdog
  → engine_should_be_running()  # desired_mode=run OR pending start_request
  → consume_engine_start_request() → start_daemon()   # sole engine spawner on supervisor path
  → health fail → force_restart only if clients>0 OR start_request OR pid still alive with demand

Disconnect (stdin EOF / leave)
  → /v1/client/unregister → last_client_left_at
  → ~10s: maybe_demote_idle (embedder)
  → ~120s: apply_idle_policy → enter_standby → stop_daemon
```

## 4. Component map (code references)

### 4.1 MCP

| File | Key symbols | Responsibility |
|------|-------------|----------------|
| `packages/pipeline/mcp_bridge.py` | `spawn_child_process`, `main` | Stable stdio bridge; Windows `CREATE_NO_WINDOW` on workers |
| `packages/pipeline/mcp_install.py` | `server_entry`, `write_cursor_mcp` | Writes mcp.json; Windows pythonw + `windowsHide`; `CTX_ENGINE_SPAWN_OWNER=supervisor` |
| `packages/pipeline/mcp_lifecycle.py` | `attach_mcp_session`, `ensure_mcp_runtime`, `warm_engine_for_mcp` | Lazy stdio attach; agent first-call warm |
| `packages/pipeline/mcp_locate.py` | `main`, `_client_for`, `status` | Tools; ensure via warm path |
| `packages/pipeline/mcp_restore.py` | `mcp_entry_needs_restore`, `heal_mcp_pins_if_stubbed` | Restore **stubbed** pins only (`connect`/`upgrade`, not engine start) |

### 4.2 Supervisor / daemon

| File | Key symbols | Responsibility |
|------|-------------|----------------|
| `packages/pipeline/watchdog.py` | `watchdog_loop`, `start_watchdog`, `discover_watchdog_pid` | Health, start_request, restart budget; pid-file + cmdline discovery |
| `packages/pipeline/daemon.py` | `ensure_daemon`, `_ensure_daemon_via_supervisor`, `start_daemon`, `note_engine_start_request` | Spawn ownership split; **must not rewrite mcp.json** |
| `packages/pipeline/lifecycle_runtime.py` | `register_client`, `unregister_client`, `ensure_supervisor_detached`, `enter_standby`, `apply_idle_policy`, `run_supervisor`, `engine_should_be_running` | Policy + OS autostart |
| `packages/pipeline/silent_spawn.py` | `start_watchdog_silent_orphan` | WMI + pythonw boot, spawn lock |
| `packages/pipeline/process_job.py` | `windows_wmi_create_process`, `background_python`, `hidden_run`, job attach | Silent spawn + CPU job |

### 4.3 Resources

| File | Key symbols | Responsibility |
|------|-------------|----------------|
| `packages/pipeline/memory_governor.py` | `maybe_demote_idle`, `force_demote_disconnect`, `ensure_semantic_tier` | Embedder load/unload |
| Engine sweeper (server) | calls demote + `apply_idle_policy` | Disconnect-driven stop |

### 4.4 State files (`~/.scubiee` / `CTX_HOME`)

| File | Role |
|------|------|
| `engine.lock` / `engine.pid` / `engine.json` | Listener identity |
| `engine.start_request` | MCP → watchdog cold-start handoff |
| `watchdog.pid` / `watchdog.log` / `watchdog.spawn.lock` | Supervisor |
| `_boot_watchdog.pyw` / `_boot_supervisor.pyw` | Hidden Windows entrypoints |
| `lifecycle_policy.json` | `desired_mode`, `last_client_left_at` |
| `active_clients.json` | MCP/IDE clients |

## 5. Platform abstractions

| Concern | Windows | macOS | Linux |
|---------|---------|-------|-------|
| Autostart | schtasks ONLOGON or HKCU Run → **pythonw + .pyw** | LaunchAgent (`KeepAlive`, `ProcessType=Background`, `ThrottleInterval=15`) | systemd user unit (`Restart=on-failure`) / XDG autostart |
| Orphan from IDE | WMI `Win32_Process.Create` (in-process COM, `ShowWindow=0`) | LaunchAgent kickstart | systemd start |
| No console flash | `CREATE_NO_WINDOW` on **every** console spawn; prefer `pythonw` for **background** roles; MCP stdio uses pythonw + `windowsHide` (hosts that honor it) | N/A (no Win32 console) | N/A |
| Kill-with-session | Named Job Object `KILL_ON_JOB_CLOSE` | supervisor signals → `enter_standby` | same |
| Host MCP spawn | Cursor/Claude/Codex own stdio subprocess; unexpected exit → **host restart** ([stdio spec](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)) | same | same |

Do not assume the IDE sets `windowsHide` / `CREATE_NO_WINDOW`. Our `mcp.json` includes `windowsHide: true` for hosts that honor it (Claude Code). Cursor may ignore the key; crash-loop prevention matters more than a single connect flash.

## 6. MCP host semantics (research)

From MCP stdio transport spec + Python SDK + host bug trackers:

- Host **owns** the server subprocess; shutdown = close stdin → wait → SIGTERM/KILL / Windows Job Objects.
- Unexpected exit → host **restarts** a fresh process (stateless protocol).
- Cursor: `mcp.json` file-watcher (`config_server_modified`) and duplicate `CreateClient` races can kill a healthy server within milliseconds of initialize ([forum](https://forum.cursor.com/t/cursor-3-4-20-kills-stdio-mcp-servers-1-5s-after-successful-initialize-sigkill-v2-fsm-race/160892), [disconnect-before-ready](https://forum.cursor.com/t/cursor-sometimes-disconnects-a-local-mcp-server-before-its-finished-starting-up-or-shutting-down-causing-intermittent-connection-failures/165513)).
- Implication: **any engine/watchdog path that rewrites `mcp.json` is a reconnect storm.** Crash loops × console shims = terminal blink storm.
- Claude Code on Windows: MCP/tool spawns without `windowsHide` flash CMD windows ([#24708](https://github.com/anthropics/claude-code/issues/24708)).
- Win32: `CREATE_NO_WINDOW` is **ignored** when combined with `DETACHED_PROCESS` ([Process Creation Flags](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags)). Prefer one hidden console inherited by descendants.

## 7. Expected behaviors (acceptance)

| Event | Expected |
|-------|----------|
| MCP connect (repo enrolled) | Stdio tools advertised; **no** watchdog/engine spawn; **no mcp.json rewrite** |
| Agent first `gate`/`status`/`map` | ≤1 supervisor, ≤1 engine; embedder ready (~1–4s DML cached); no console flashes |
| Repeated tool calls | No extra engine/watchdog processes; ensure is cheap/idempotent (TTL) |
| Second IDE same host | Coalesced MCP client; one engine |
| MCP disconnect | Embedder demote ~10s; engine stop after ~120s debounce; RSS drops |
| Cursor close | Engine **survives** if supervisor orphaned; standby later if no clients |
| No MCP, no CLI work | `desired_mode=standby`; engine not running |
| Watchdog pid file missing but process alive | `discover_watchdog_pid` finds `_boot_watchdog.pyw` / supervisor; no respawn storm |
| Stale `engine.start_request` (>180s, no clients) | Watchdog consumes it, sets `desired_mode=standby`, does **not** start the engine |
| Existing live pythonw pin without `windowsHide` | Leave it. Rewriting mcp.json to add the key would restart Cursor MCP. `pythonw` already has no console. |

## 8. Current implementation (0.3.68)

| Concern | Behavior | Code |
|---------|----------|------|
| Live Windows MCP pin | `pythonw -m pipeline.mcp_bridge` is a live launcher | `mcp_restore.is_live_scubiee_mcp_launcher` |
| Engine start | Does **not** call pin restore / rewrite mcp.json | `daemon.start_daemon` |
| MCP connect | Thin stdio attach; no engine/watchdog unless `CTX_MCP_AUTO_WARM=1` | `mcp_locate.boot_mcp_worker`, `mcp_lifecycle.attach_mcp_session` |
| Agent first locate | `ensure_mcp_runtime` starts engine + embedder | `mcp_lifecycle.ensure_mcp_runtime` |
| Watchdog identity | pid file, else this home's `_boot_watchdog.pyw` / `_boot_supervisor.pyw` | `watchdog.discover_watchdog_pid` |
| Demand | `desired_mode=run` **or** fresh start_request; stale request skipped | `lifecycle_runtime.engine_should_be_running`, `daemon.start_request_is_actionable` |
| Disconnect | unregister → debounce 120s → `enter_standby(stop_engine=True)`; embedder demote ~10s | `lifecycle_runtime.apply_idle_policy`, `memory_governor.maybe_demote_idle` |
| Silence | `CREATE_NO_WINDOW` on helpers; pythonw boot scripts; `windowsHide` on **new** Windows pins | `process_job.hidden_run`, `mcp_install.server_entry` |
| Upgrade stamp in mcp.json | JSON patch only if `command` contains `scubiee-mcp` — pythonw pins are not rewritten | `mcp_hot_reload._patch_build_env_in_json` |

## 9. Compatibility matrix (2026-09-12)

| Environment | How verified | Result |
|-------------|--------------|--------|
| Windows 10/11 + installed `uv tool` 0.3.68 | Live process/log/pin snapshot; pythonw stdio pytest | Pin `needs_restore=False`; no watchdog spawn after 16:25; pythonw initialize round-trip **PASS** |
| This Cursor workspace | `.cursor/mcp.json` is Figma-only | Scubiee MCP **not connected** — live reconnect/blink **not** re-observed here |
| `claude-code-proxy` Cursor pin | File + restore classifier | Live pin is pythonw+bridge; last mcp.json write 16:25:42 (storm era); **not rewritten** by 0.3.68 install |
| macOS LaunchAgent | `tests/test_lifecycle_runtime.py` plist/bootstrap mocks | Simulated **PASS**; no Mac host in this session |
| Linux systemd/XDG | `test_linux_register_uses_xdg_autostart` | Simulated **PASS**; no Linux host |
| Claude Code | `windowsHide` copied through `format_server_entry`; host may still ignore it ([#24708](https://github.com/anthropics/claude-code/issues/24708)) | Pin contract unit-tested; **no live Claude Code** |
| Codex / other JSON MCP hosts | Same `server_entry` / schema passthrough | Unit-tested; **no live Codex** |

## 10. Related docs

- `docs/architecture/watchdog-root-causes.md` — diagnosed problems + evidence + verification log
- `docs/superpowers/plans/2026-09-12-watchdog-lifecycle-hardening.md` — implementation plan
