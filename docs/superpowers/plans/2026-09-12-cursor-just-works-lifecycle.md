# Cursor Just-Works Lifecycle (0.3.62) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Opening Cursor and using Scubiee requires zero process babysitting — one engine, one supervisor, locate never fights sync, MCP never parents the engine.

**Architecture:** Supervisor/watchdog is the only process allowed to `Popen` the engine. MCP attaches over HTTP and may only request run-mode + ensure a detached supervisor. Lock/pid always bind to the TCP listener PID. Keeper defers *all* sync during an active locate streak. Duplicate Cursor MCP clients coalesce to one primary.

**Tech Stack:** Python (`pipeline.daemon`, `lifecycle_runtime`, `watchdog`, `mcp_lifecycle`, `sync_loop`, `context_trace`), Windows DETACHED/BREAKAWAY + schtasks logon supervisor, pytest.

**Spec:** User request 2026-09-11/12 — prevent 30s pack contention, dual Python/MCP trees, and “messed up” ownership so Cursor open → natural use.

## Global Constraints

- Ship as `0.3.62` (pyproject + npm + upgrade_releases).
- Do not restore job memory hard-kill.
- Ban shell `scubiee map|pack|expand` while MCP locate is callable (agents).
- MCP must not call `start_daemon` / direct engine `Popen`.
- Prefer listener PID over wrapper PID for lock/pid/meta.

---

## File map

| File | Responsibility |
|------|----------------|
| `packages/pipeline/daemon.py` | Listener PID bind; `ensure_daemon(spawn_owner=)` |
| `packages/pipeline/watchdog.py` | Eager start when desired_run + down; detach spawn |
| `packages/pipeline/lifecycle_runtime.py` | Detached ensure_supervisor; MCP client coalesce |
| `packages/pipeline/mcp_lifecycle.py` | Attach-only ensure (no direct spawn) |
| `packages/pipeline/process_job.py` | Stronger detached Popen helpers if needed |
| `packages/pipeline/sync_loop.py` | Defer live sync during locate streak |
| `packages/pipeline/mcp_locate.py` / client | `note_locate` on every map/pack start |
| `packages/pipeline/context_trace.py` | Cap multi-seed while warming/syncing |
| `packages/pipeline/__main__.py` / `mcp_install.py` | `connect` → `install_session_runtime` |
| `tests/test_lifecycle_just_works.py` | New regression tests |
| `packages/pipeline/upgrade_releases/v0_3_62.py` | Release notes |

---

### Task 1: Listener PID identity

- [x] Add `bind_engine_identity_to_listener()` — after healthy start/heal, set lock+pid+meta.pid to port listener.
- [x] Update `heal_engine_lock` to rewrite when lock PID ≠ listener but listener alive.
- [x] Test: heal rewrites wrapper → listener.

### Task 2: Supervisor-only engine spawn

- [x] `ensure_daemon(..., spawn_owner="direct"|"supervisor")`; MCP uses `supervisor`.
- [x] Supervisor path: `set_desired_mode(run)` + detached `ensure_supervisor` + poll `/health`; never `start_daemon`.
- [x] Watchdog: if desired_run and not healthy and not alive → `start_daemon` immediately (eager), not only after fail budget.
- [x] Detach supervisor spawn so MCP is not parent (schtasks /Run if registered, else DETACHED+BREAKAWAY intermediate).
- [x] Tests: MCP path does not call `start_daemon`; watchdog eager-starts.

### Task 3: Coalesce duplicate Cursor MCP clients

- [x] On `register_client(kind=mcp)`, drop/supersede older same-host MCP clients with dead or older PIDs.
- [x] Secondary attach must not trigger another spawn race.
- [x] Test: two cursor MCP registrations → one primary.

### Task 4: Locate-over-sync

- [x] Call `note_locate` at start of map + pack_context (engine HTTP).
- [x] Bump default `CTX_LOCATE_STREAK_MS` to 60000.
- [x] `_defer_for_active_session`: defer **all** sync (not only bulk) while locate streak active.
- [x] Test: locate streak defers live 1-file sync.

### Task 5: Warm UX + multi-seed cap

- [x] While engine `warm_state` in indexing/warming or keeper syncing: cap resolved seeds to 2 (or serialize).
- [x] Status already exposes warming — keep agents retrying without treating as hard fail in ship check if needed.

### Task 6: connect ensures supervisor

- [x] `cmd_connect` / install path calls `install_session_runtime()` so logon task + session supervisor exist before Cursor opens.

### Task 7: Ship

- [x] Release `0.3.62`, version bump, registry test update.
- [x] Unit tests green; uv tool install + `scubiee connect --cursor` + verify single engine listener + MCP ladder.

## Done when

1. MCP process tree does not contain `pipeline engine run`.
2. `engine.lock` pid == listener on :8765.
3. At most one primary `mcp:cursor@*` client after reconcile.
4. Pack during locate streak does not start keeper incremental.
5. Warm single-seed pack stays fast when idle; cold path does not orphan engines on MCP reload.
