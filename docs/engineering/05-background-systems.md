# Background Systems

This document covers the process management, health monitoring, resource control, and background maintenance that keep the system running reliably.

## Daemon lifecycle

**File:** `packages/pipeline/daemon.py`

The engine runs as a detached background process. The daemon module handles:

### Starting

`start_daemon(repo, host, port)`:
1. Check if already healthy (`/health` responds) — return immediately if so.
2. Check for stale lock with a live PID but no health response — refuse (hung state).
3. Spawn detached: `python -m pipeline engine run <repo> --host <host> --port <port>`.
   - Windows: `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`
   - POSIX: `start_new_session=True`
4. Write `engine.lock` (JSON: pid, url, repo, timestamp).
5. Write `engine.json` (full metadata) and `engine.pid` (raw PID).
6. Poll `/health` for up to 90 seconds.

### Stopping

`stop_daemon()`:
1. POST to `/v1/shutdown` (graceful).
2. Kill by PID from both `engine.pid` and `engine.lock`.
3. Clean up lock files.

### Force restart

`force_restart_daemon()` — used by the watchdog:
1. Stop everything (including force-kill).
2. Clear stale locks even if PID is alive.
3. Wait 2 seconds.
4. Start fresh with 120s timeout.

### Ensure (lazy start)

`ensure_daemon(repo)`:
- If healthy → return.
- If hung and `force_if_hung=True` → force restart.
- If hung and `force_if_hung=False` (MCP paths) → return error (avoid blocking agent).
- Otherwise → start.

### Single-instance enforcement

The `engine.lock` file at `~/.context-engine/engine.lock` prevents multiple instances. It contains `{pid, url, repo, acquired_at}`. A lock is considered stale if the PID is dead. A lock with a live PID but no health response is "hung" — only the watchdog or explicit `force_restart_daemon` clears it.

## Watchdog sidecar

**File:** `packages/pipeline/watchdog.py`

A separate detached process that monitors engine health and restarts it on failure.

### Behavior

- Polls `/health` every 15 seconds (configurable via `CTX_WATCHDOG_INTERVAL_S`).
- After 2 consecutive failures, calls `force_restart_daemon`.
- Exponential backoff after restarts: 5s → 15s → 30s.
- **Crash-loop protection:** If 20 restarts happen within one hour, pauses for 10 minutes before trying again.
- Controlled by `CTX_WATCHDOG` env var (default: enabled).

### Lifecycle

- Started by `start_watchdog()` — spawns a detached `python -m pipeline engine watchdog` process.
- Writes its own PID to `~/.context-engine/watchdog.pid`.
- Logs to `~/.context-engine/watchdog.log`.
- Stopped by `stop_watchdog()` or when the user runs `ctx engine stop`.

## Background sync loop (keeper)

**File:** `packages/pipeline/sync_loop.py`

The `BackgroundSyncLoop` runs inside the engine process as a daemon thread. It keeps the index fresh without manual intervention.

### How it works

1. **Initial delay:** Waits 5 seconds after engine start before first tick (configurable `CTX_SYNC_INITIAL_DELAY_MS`).
2. **Periodic tick:** Every 5 minutes (configurable `CTX_SYNC_INTERVAL_MS`), calls `keeper_tick()`.
3. **keeper_tick:**
   - First checks resource pressure — if system is critical, skips the tick.
   - Runs `root_probe(repo)` — cheap mtime-gated Merkle root comparison.
   - If clean: no-op, log, return.
   - If dirty: run `incremental_sync(repo)`, then call `publish_engine()` to reload the search engine with new data.

### Trigger file

A secondary watcher thread monitors `~/.context-engine/.sync-trigger`. When this file is touched (mtime changes), it immediately runs a tick. This lets external tools (IDE hooks, file-save events) wake the keeper on demand.

### Exit behavior

Registered via `atexit` — does one final probe + sync before the process dies. This ensures edits made just before closing the IDE still get indexed.

### Environment controls

| Variable | Default | Purpose |
|----------|---------|---------|
| CTX_BACKGROUND_SYNC | 1 | Enable/disable the keeper entirely |
| CTX_SYNC_INTERVAL_MS | 300000 | Probe interval (5 minutes) |
| CTX_SYNC_INITIAL_DELAY_MS | 5000 | Wait before first tick |
| CTX_ALLOW_BG_FULL | 0 | Allow full reindex in background (default: only incremental) |
| CTX_TRIGGER_WATCHER | 1 | Enable the trigger file watcher |

## Resource manager

**File:** `packages/pipeline/resources.py`

The `ResourceManager` prevents indexing/embedding from overwhelming the user's machine.

### Pressure levels

| Level | CPU | RAM | Effect |
|-------|-----|-----|--------|
| idle | <25% | >2× min free | Boost batch 2x, no pause |
| normal | 25-70% | adequate | Baseline budget |
| busy | 70-90% | adequate | Halve batch, pause 200-350ms between batches |
| critical | >90% OR <512MB free | — | Batch=1, block sync/index/graph entirely |

### How it's used

Every heavy operation calls `rm.wait_for_capacity(job_kind)` before starting:

```python
budget = rm.wait_for_capacity("embed", timeout_s=180.0)
if not budget.allow:
    # defer or proceed minimally
batch_size = budget.batch_size
```

Jobs: `embed`, `index`, `sync`, `graph`, `generic`.

### Sampling

Uses `psutil` to read CPU% and RAM. Cached briefly (250ms) to avoid hammering the OS. If psutil is unavailable, falls back to conservative defaults (assume normal load).

### Configuration

Thresholds are configurable via env vars (`CTX_RM_MAX_CPU`, `CTX_RM_CRITICAL_CPU`, `CTX_RM_MIN_FREE_RAM_MB`, `CTX_RM_MAX_RAM_PCT`) and via `prefs.json` (dashboard settings POST). Can be disabled entirely with `CTX_RM_DISABLE=1`.

## Root probe

**File:** `packages/pipeline/root_probe.py`

The cheapest freshness check — the "idle gate" for the keeper.

### Algorithm

1. Load stored Merkle snapshot (file → SHA-256 hash) and stored mtimes.
2. For each indexed file:
   - `stat()` to get current mtime.
   - If mtime matches stored value → reuse old hash (skip SHA-256).
   - If mtime differs → compute SHA-256.
3. Optionally discover newcomers under fast_roots (new `.py` files not in the snapshot).
4. Compute new Merkle root hash, compare against stored.
5. Return `RootProbeResult` with clean/dirty status and change lists.

**Performance:** When nothing changed, the probe does N stat calls and zero file reads. Typically completes in 10-50ms for a 3000-file project.

## Freshness detection

**File:** `packages/pipeline/freshness.py`

Layered strategy for determining what changed:

1. **git_fast:** Same HEAD + clean porcelain → still verify Merkle leaves (gitignored files don't show in porcelain).
2. **git_diff:** HEAD advanced → combine `git diff --name-only` + porcelain + Merkle verification.
3. **mtime:** Pre-filter by stored mtime → only hash files whose mtime changed.
4. **merkle:** Full scan/hash when no shortcuts apply.

Strategy selection based on change count:
- 0 files → `none`
- ≤40 files → `incremental` (sync before search)
- ≤200 files → `background` (search now, refresh in background)
- ≥50% of corpus → `full` (background full reindex)

## Hardware detection

**File:** `packages/pipeline/hardware.py`

Collects a comprehensive system snapshot saved to `~/.context-engine/hardware.json`:
- CPU model and logical core count
- Total and available RAM
- GPU list (via Win32_VideoController on Windows)
- Installed acceleration libraries (onnxruntime providers, torch CUDA/MPS, psutil)
- Recommended acceleration profile

Used by the Resource Manager for budget decisions and by `accel.py` for initial setup.

## The complete process topology

```
User Machine
├── Engine daemon (pid in engine.lock)
│   ├── HTTP server thread (serves queries)
│   ├── Keeper thread (periodic root probe + incremental sync)
│   └── Trigger watcher thread (watches .sync-trigger file)
├── Watchdog sidecar (pid in watchdog.pid)
│   └── Polls /health, force-restarts on failure
└── MCP subprocess (spawned by IDE per session)
    └── stdio ↔ IDE, HTTP → daemon for actual queries
```
