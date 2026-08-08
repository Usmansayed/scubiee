# Resource Management System (design)

**Status:** implementing  
**Scope:** Standalone subsystem for hardware detection + adaptive indexing/embedding throughput. Independent of MCP; used by indexer, embedder, keeper, CLI.

## Goals

Never make the user's machine feel unresponsive. Indexing runs opportunistically under a scheduler that observes CPU/RAM pressure and adapts batch size, pauses, and job admission.

## Components

### 1. Hardware snapshot (`hardware.py`)

On install / first launch / `ctx init`:

- OS, arch, Python
- CPU count (+ model when available)
- Total / available RAM
- GPU list (existing DXGI / nvidia-smi paths)
- Acceleration libraries present: CUDA ORT, DirectML ORT, CPU ORT, torch CUDA/MPS, MLX (macOS) if importable

Persists to `~/.context-engine/hardware.json`. Feeds `accel.recommend_profile` (unchanged selection rules, richer `detected`).

### 2. ResourceManager (`resources.py`)

Singleton process-wide scheduler:

| Pressure | Meaning | Behavior |
|----------|---------|----------|
| `idle` | Low CPU + comfortable RAM | Larger embed batches, short/no pause |
| `normal` | Typical desktop load | Baseline batch from AccelProfile |
| `busy` | User working hard | Shrink batch, sleep between batches |
| `critical` | High CPU or low free RAM | Pause work (wait/backoff), refuse new heavy jobs |

APIs:

- `sample()` → metrics
- `pressure()` → level
- `budget(job="embed"|"index"|"sync"|"graph")` → `AdaptiveBudget(batch_size, pause_s, allow, workers)`
- `wait_for_capacity(job, ...)` — block with backoff until `allow` or timeout
- `run_job(job, fn)` — gate then execute
- Context manager `throttle(job)` around batch loops

Env overrides: `CTX_RM_DISABLE=1`, `CTX_RM_MAX_CPU`, `CTX_RM_MIN_FREE_RAM_MB`, `CTX_RM_POLL_MS`.

Prefs (optional): `resource_management` block in `prefs.json`.

### 3. Integration points

| Caller | Gate |
|--------|------|
| `Embedder.embed_many` | Before each batch: `wait` + adaptive `bs` |
| `index_repo` | Before extract/embed phases |
| `incremental_sync` | Before sync body |
| `BackgroundSyncLoop.keeper_tick` | Skip tick if critical (or delay) |
| CLI `ctx resources` | Print snapshot + live pressure |

### 4. Safety

- No hard kill of user apps; only self-throttle
- Fail-open if metrics unavailable (assume `normal`, conservative batch)
- Cap batch size even when idle (profile max × 2)
- Memory: if available RAM &lt; threshold → critical
- Exceptions in monitor never crash indexing (caught, log stderr)

## Non-goals (v1)

- Cross-process global lock across multiple MCP instances
- NPU-specific kernels
- OS-level process priority changes (nice) — optional later
