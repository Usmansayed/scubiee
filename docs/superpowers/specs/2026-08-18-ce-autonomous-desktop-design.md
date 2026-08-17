# Context Engine — Autonomous Desktop Product

**Date:** 2026-08-18  
**User contract:** Install once. After that the only intentional command is `ctx init <repo>`. Everything else is our job.

## What the user does

1. `pip install -e .` then `ctx setup` **once per machine**.
2. `ctx init <path>` for each codebase they want CE to manage.
3. Use Cursor. They do not start, stop, warm, repair, or babysit a server.

Optional later: `ctx dashboard` (operator UI), `ctx doctor --fix` (only if they want a button). Neither is required for the happy path.

## Process model (efficiency + reliability)

Three layers, never more:

| Layer | When it exists | Cost | Purpose |
|-------|----------------|------|---------|
| **Supervisor** | User logon → logoff | Tiny (one Python loop, ~15s sleep) | Decide whether the engine *should* be up. Restart only if desired. Idle-stop. Survive sleep. |
| **Engine** | On demand, while work is happening | HTTP on 127.0.0.1:8765 | Search, sync, MCP backend. |
| **Warm runtime** | First request for a managed repo | RAM + GPU/ORT | Load index + embedder. Not at boot. |

**Boot / power-on:** nothing GPU-related starts.  
**User logon:** supervisor starts (standby). Engine stays off.  
**First `ctx init` or Cursor MCP tool use:** `ensure_daemon` sets desired mode `run`, starts engine, warms **that** repo.  
**Idle (default 30 min, no user requests):** engine stops, mode `standby`. Supervisor stays. `/health` from the supervisor does **not** count as user activity.  
**Sleep/wake:** supervisor sees a monotonic gap and reconciles dirty files.  
**Logoff / reboot:** supervisor task ends; engine must die with it. No leftover GPU process.  
**Next logon:** supervisor starts again in standby. First IDE use powers the engine up.

Hard rules:

- Desired mode `standby` → supervisor **must not** restart a dead engine (that was the “keeps running forever” bug class).
- Desired mode `run` + engine dead → supervisor **must** restart (that was the “doesn’t power up” bug class).
- Detached orphans that survive logoff are a defect. Supervisor is the logon-scheduled parent; engine is a child, not a breakaway process when started from the supervisor.

## Features the product must have (A–Z)

Already in this branch (keep):

- Machine profile + batch calibration (`ctx setup` / `--repair`)
- Repo admission + index (`ctx init`)
- Durable project identity, registry, presence (missing ≠ Forget)
- Live dirty sync, dirty journal replay, watcher overflow → needs_full
- Fail-closed search when the index/parser/provider is not ready
- Publication checksums
- Watchdog health polling + sleep/wake reconcile
- Doctor + classified safe repairs (`--fix`)
- Loopback dashboard (optional)
- MCP phase surface (`map` / `focus` / `workspace` / `status`) with `ensure_daemon` on first tool use
- Resource envelope (batch/workers drop under RAM pressure)
- Multi-repo isolation in one engine
- Certify + `ctx test core`

Must add now (this spec):

1. **Logon autostart of the supervisor**
   - Windows: scheduled task `ContextEngineSupervisor` (`schtasks` ONLOGON)
   - macOS: LaunchAgent `com.contextengine.supervisor` (Aqua session, RunAtLoad)
   - Linux: `~/.config/autostart/*.desktop`
   Registered by `ctx setup`. Engine is not started at logon.
2. **Standby vs run policy** persisted next to the engine lock.
3. **Idle engine stop** so overnight/idle machines do not keep ORT/GPU loaded.
4. **Activity clock** on real user/MCP/CLI work, never on supervisor `/health`.
5. **`ctx engine supervisor`** blocking loop used by the logon task.
6. **`ctx setup` unregister path** (`ctx engine autostart --off`) so uninstall is possible.

Explicitly out of product scope (do not build):

- Start at BIOS/Windows boot before login (wastes power, no user session)
- Warm every managed repo at logon
- Auto `pip install` / auto full rebuild of corrupt publications
- Cloud/multi-user server
- Full graph explorer

## Failure table

| Event | Expected |
|-------|----------|
| Fresh reboot, user never opens Cursor | Supervisor only. No engine. No GPU. |
| User opens managed repo in Cursor | Engine starts, that repo warms, search works. |
| Engine crash mid-session | Supervisor restarts engine (mode=run). |
| User idle 30+ min | Engine stops. Supervisor remains. |
| User comes back | Next MCP/`ctx init` starts engine again. |
| Sleep 2 hours | Reconcile dirty; do not full-reindex. |
| Logoff | No leftover `python -m pipeline` engine. |
| `ctx setup` on a new PC | Profile, model, batch, MCP, logon task. |

## Success

- User story holds: setup once, then only `ctx init`.
- After reboot, first Cursor locate works without a manual `engine start`.
- After a day of not using Cursor, no GPU/ORT process remains.
- Core tests cover policy, idle stop, standby-does-not-restart, autostart register/unregister (OS calls mocked).
