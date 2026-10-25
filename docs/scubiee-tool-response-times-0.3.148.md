# Scubiee MCP tools: working status + response times (0.3.148)

_Measured on: macOS 26.5.2, Apple Silicon (M5, arm64), MLX/Metal, Python 3.12.14.
Repo under test: the engine's own codebase (8,641 chunks). All numbers are from
live runs against the running engine (`127.0.0.1:8765`), not estimates._

## All tools: working

| Tool | Config | Status | Notes |
|---|---|---|---|
| `gate` | - | ✅ working | managed signal `1:<project_id>` |
| `status` | - | ✅ working | warm/dense/chunks/version |
| `map` | `find` | ✅ working | semantic search; honest confidence labels |
| `map` | `focus` | ✅ working | bare name, `file::symbol`, `file:a-b` range, multi-symbol |

Also verified working this session: CLI (`init`, `search`, `sync`, `doctor`,
`map`), the auto-keeper file watcher, and all sync lanes
(add/modify/delete/rename/move/rapid/bulk).

## Response times: warm engine (steady state)

Per-call latency with the engine already warm (median of 6 calls):

| Tool / call | first call in a new worker | warm (median) |
|---|---|---|
| `gate` | ~7 ms | **0.3 ms** |
| `status` | ~0.3 ms | **0.2 ms** |
| `map find` (symbol-ish query) | ~224 ms | **~18 ms** |
| `map find` (vague NL query) | ~70 ms | **~19 ms** |
| `map focus` (`file::symbol`) | ~18 ms | **~6 ms** |
| `map focus` (bare name) | ~236 ms | **~236 ms** |
| `map focus` (2 bare names) | ~485 ms | **~481 ms** |
| `/health` HTTP endpoint | - | **~0.4-0.6 ms** |

Notes:
- `map find`'s first call in a process pays a one-time engine `/v1/search`
  warm-up (~0.2 s); every subsequent call is ~18 ms.
- **`map focus` by a `file::symbol` is ~40× faster than by a bare name** (~6 ms
  vs ~236 ms). Bare-name resolution runs a disk grep + outline-confirm on every
  call (no per-call cache), so it is consistently ~236 ms; the qualified form
  reads the one file's outline directly. Multi-symbol bare lookups scale linearly
  (~2 names ≈ 2×). If latency matters, prefer `file::symbol`.
- MCP worker module import is a one-time ~19 ms per worker process.

## First call vs call after idle

| Scenario | find/focus usable (soft) | semantic search (dense) |
|---|---|---|
| **Cold start** (engine stopped → first call) | **1.7 s** | **5.9 s** |
| **Call after short idle** (gaps < ~80 min) | ~15-19 ms (no penalty) | ~15-19 ms |
| **Call after idle-standby** (engine demoted) | **1.3 s** | **5.8 s** |

Behavior:
- The engine daemon stays warm across inactivity. Idle timeouts default to
  **4800 s (80 min)** (`CTX_ENGINE_IDLE_S`, `CTX_EMBED_IDLE_DEMOTE_S`). Within
  that window a call after idle has **no penalty**, verified: after a 60 s gap a
  search was still ~19 ms with `warm=ready, dense=True`.
- After the idle timeout the supervisor puts the engine into **standby**
  (`idle_standby` → `stop_daemon`), freeing RAM/GPU. The next call re-warms:
  **~1.3 s to soft-ready** (BM25, `find`/`focus` answer) and **~5.8 s to
  dense-ready** (full semantic vectors). This equals a cold start.
- In normal IDE use the supervisor/watchdog keeps the engine warm and auto-
  restarts it, so a call after idle typically lands on an already-warm engine
  (the ~15 ms path); the ~1.3 s/5.8 s figure is the worst case where the engine
  was fully in standby when the call arrived.
- Cold-start staging matters: at **1.7 s** `find`/`focus` already work (soft/BM25
  lane); dense semantic ranking trails by a few seconds and self-upgrades, the
  tool never blocks the agent waiting for dense.

## Summary

Every tool works. Warm steady-state is **sub-millisecond for health tools,
~6-19 ms for map focus(file::symbol)/find, ~236 ms for map focus by bare name**.
A first/cold call pays a ~1.7 s (usable) / ~5.9 s (dense) warm-up; a call after a
normal idle gap pays nothing; only a call that arrives while the engine is in
deep idle-standby re-pays the ~1.3 s/5.8 s warm-up.
