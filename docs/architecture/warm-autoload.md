# Warm + auto-load architecture (and why Cursor open kept failing)

**Date:** 2026-09-20  
**Code:** `0.3.99` — quiet attach, 45s hung-prewarm abort, Kiro Lane B SLA  
**Evidence:** live Cursor map timeout with engine PID alive; Lane A quiet-settle false green; ORT install regressing to CPU; health-poll settle → `SETTLE_MAP_SLOW`

---

## 1. How the pieces are supposed to work

```
Cursor
  └─ mcp_bridge (stdio) ──heartbeat──┐
       └─ mcp_locate (tools)          │
                                      ▼
                              engine :8765
                         ┌────────────┴────────────┐
                         │ ThreadingHTTPServer     │
                         │  /health  /v1/map…      │
                         │  /v1/client/touch       │
                         │  /v1/embed/prewarm      │
                         └────────────┬────────────┘
                                      │
                         single embed ThreadPoolExecutor (max_workers=1)
                         FastEmbed → onnxruntime → DirectML/CPU
                                      │
                         watchdog (separate process)
                         polls /health; may force-restart
```

| Concern | Owner | Intended behavior |
|--------|--------|-------------------|
| Soft locate ready | `ce_service` binder + BM25/FAISS | Soft in seconds after open; map can use soft without dense |
| Dense embed ready | `engine.prewarm_embedder*` | Background ORT session load; then map ≤1s |
| Keep warm while IDE open | MCP heartbeat + engine keepalive + `active_clients.json` | Clients>0 ⇒ no idle unload |
| Unload after Cursor quit | leave → debounce (10s) → `standby_stop` | Process exit, free RAM |
| Autoload when dead | watchdog | Heal hung engine **with demand**; do not cold-start with zero demand |

---

## 2. What actually broke (causal chain)

Research (ONNX Runtime): **session initialization holds the Python GIL**. `run()` releases GIL; `InferenceSession` / init does **not** ([ORT #27063](https://github.com/microsoft/onnxruntime/issues/27063)). DirectML also forbids concurrent `Run` on one session ([DirectML EP docs](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html)).

So during cold ORT load:

1. Embed worker holds GIL for tens of seconds.
2. `ThreadingHTTPServer` workers cannot run Python → **`/health` times out** even though the process is healthy.
3. MCP attach / agent `status()` treat timeout as **engine dead** → sticky `engine_health_timeout`.
4. Heartbeats keep POSTing `/v1/client/touch` + `/keepalive` → more queued work when GIL returns → storm.
5. If clients flap to 0, **10s idle sweeper** kills the engine mid-prewarm (busy stamp was ignored).
6. Watchdog **`skip auto load` when `clients=0`** even though Cursor MCP stdio is still up → permanent DOWN.
7. Quiet Lane A sim **does not poll `/health` during settle** → false PASS (~150ms map). Live-like health-poll settle → FAIL (`SETTLE_MAP_SLOW` ~1.3s+) — proved 2026-09-20.
8. `uv tool install` once pulled plain `onnxruntime 1.30` (no DirectML) → CPU path, worse hangs.

---

## 3. Design rewrite (fail-closed contract)

### Phases (side-channel, not `/health`)

File: `~/.scubiee/warm_phase.json` (and retain `embed_prewarm.busy` stamp).

| Phase | Meaning | `/health` may timeout? | Watchdog health fails |
|-------|---------|------------------------|------------------------|
| `down` | No engine | yes (expected) | start if MCP demand |
| `soft` | Binder up, dense cold | rare | normal |
| `prewarm` | ORT session loading (GIL held) | **yes — expected** | **ignore** |
| `dense` | Embedder loaded | no | normal |
| `error` | Prewarm failed / stuck | — | heal with demand |

MCP attach, heartbeat, and status **must read this file** during `prewarm` and must **not** hammer `/health`.

### Rules

1. **One embed lane** — all ORT work on `run_embed_infer` (already). Keepalive must not start until `dense`; interval ≥ keepalive env (default 15s+).
2. **Idle stop** respects `prewarm` / busy stamp (postpone leave).
3. **Watchdog demand** = `active_clients > 0` **OR** live `mcp_bridge` process.
4. **Watchdog** while `phase=prewarm`: do not increment health-fail toward restart.
5. **Attach warm**: wait on phase file; quiet sleep; never 0.2s health spin during prewarm.
6. **Install / preflight**: Windows `dml` profile requires `DmlExecutionProvider`; refuse green sims without it.
7. **Sims**: default health-poll settle + post-round health must answer (or phase=`prewarm`/`dense` with coherent side-channel).

### What we will not do

- Claim “fixed” from quiet Lane A alone.
- Poll `/health` from MCP during prewarm “to be sure.”
- Force-restart mid-prewarm because health timed out.

---

## 4. Code map (after rewrite)

| Module | Role |
|--------|------|
| `warm_autoload.py` | Phase read/write, `should_ignore_health_fail()`, `mcp_demand()`, idle-busy helpers |
| `engine.py` | Set phase around prewarm; clear stamp in `finally`; keepalive gated on dense |
| `mcp_lifecycle.py` | Heartbeat + attach warm use phase file |
| `watchdog.py` | Demand + ignore fails in prewarm |
| `lifecycle_runtime.py` | Idle busy includes prewarm phase |
| `scripts/cursor_open_preflight.py` | ORT/DML + HEALTH_WEDGE gate |
| `scripts/cursor_close_open_loop.py` | Fail-closed loop (health-poll default) |

---

## 5. Verification required before “green”

1. `python scripts/cursor_open_preflight.py` → DML present.
2. `python scripts/cursor_close_open_loop.py --rounds 2 --settle-s 35` (health-poll on) → map ≤1s **and** no HEALTH_WEDGE.
3. Live Cursor: reload MCP → wait ≥35s → MCP `map` ≤1s.
4. Unit: phase ignore health fail; idle busy on prewarm; MCP bridge demand.

Unit tests alone are not enough (repo rule).

### Log (2026-09-20)

| Check | Result |
|-------|--------|
| Unit `test_warm_autoload` + idle/watchdog traps | **10 passed** |
| Preflight ORT | **1.24.4** + `DmlExecutionProvider` |
| `cursor_close_open_loop --rounds 2 --settle-s 35` | **PASS** — map_first **147.8ms** / **83.7ms**; round 2 hit `warm_phase=dense` during quiet window |
| Live Cursor MCP map after reload | **FAIL** — map timeout; `warm_phase=prewarm` held ≥137s; `/health` dead; later PID recycled still `prewarm` |

---

## 6. Stuck-prewarm causal inventory (before picking one cause)

Observed loop: **engine process alive → `warm_phase.json` stays `prewarm` → `/health` times out → MCP `map` = unreachable**. These are independent mechanisms that can produce that picture. Several usually fire together.

### A. ORT session init holds the GIL (primary physics)

ONNX Runtime Python bindings **do not release the GIL during `InferenceSession` / EP init** ([ORT #27063](https://github.com/microsoft/onnxruntime/issues/27063)). `run()` does. FastEmbed first `embed_one` creates the session.

`ThreadingHTTPServer` handlers are Python. No GIL ⇒ **no `/health`, no `/v1/search`, no map HTTP**. PID can still listen. This is expected for the duration of init (~10–40s) and a **hang forever** if DML never returns.

Code: `engine.py` `_LazyEmbedder.embed_one` → `run_embed_infer` → `_EMBED_EXECUTOR` (1 worker) → `emb._ensure()` / `embed_one`.

### B. DirectML is not concurrent-safe

DML EP: sequential `Run` only; Python allocator not thread-safe; ORT-DML ≥1.18 has deadlock/crash reports with multiple threads on one device ([#20713](https://github.com/microsoft/onnxruntime/issues/20713), [#22867](https://github.com/microsoft/onnxruntime/issues/22867)).

Any **second** ORT entry (keepalive tick, map search, second prewarm, HTTP worker touching embedder) during init can **stall the first session forever**. Symptom: `prewarm` never ends; watchdog thinks “busy, leave it”.

### C. Prewarm never calls `end_prewarm`

`begin_prewarm()` is called from **both** `prewarm_embedder_async` (before the thread) **and** `prewarm_embedder` (inside the thread). `end_prewarm` only runs after `embed_one` returns (or on exception).

If `embed_one` **blocks without throwing**, phase stays `prewarm` indefinitely. Daemon thread death / process kill leaves a **stale disk file** that the next MCP process still reads.

### D. Watchdog *refuses* to heal during `prewarm`

`should_ignore_health_fail()` + `_engine_busy_embed_prewarm()` reset fail counts. Idle sweeper `_idle_busy_reason()` postpones `standby_stop`.

So a hung ORT is treated as “healthy enough.” Stale timeout is **180s** (`DEFAULT_PREWARM_MAX_AGE_S`). Waits of ~2 minutes never trip it. `begin_prewarm()` **refreshes `updated_at`**, so repeated kicks reset the 180s clock.

### E. HTTP `wait=True` prewarm parks a server worker

`mcp_lifecycle._kick_embed_prewarm` and `RuntimeController._kick_embed_prewarm` POST `{wait: true, sync: true}` (client timeout 30–45s).

`server.py` then **busy-polls `prewarm_status()` every 50ms for up to 8s** on that HTTP thread. Those polls also need the GIL. Combined with A: attach warm **competes with ORT for the GIL** instead of staying quiet.

### F. Map/search kicks another prewarm / joins ORT

`ce_service.search`: if not `embedder_is_loaded()`, calls `prewarm_embedder_async` then `eng.search` which does a real embed. Locate `map` HTTP then sits on a GIL-starved server → client error `unreachable … timed out` (looks like engine down; it is wedged).

### G. Keepalive loop re-enters prewarm

`ensure_embed_keepalive_loop`: while clients>0 and embedder **not** loaded, every **2s** calls `prewarm_embedder_async` if `running` is false. If the worker died without clearing `running`, it never retries; if `running` cleared without `end_prewarm`, it **restarts** ORT (B + D clock reset). After load, keepalive `Run` on the same DML session as map.

### H. Client/touch + heartbeat HTTP storms

Bridge + locate heartbeats POST `/v1/client/touch` and `/v1/embed/keepalive`. Mitigated when `in_prewarm()` is true **in the MCP process**. MCP reads **disk** `warm_phase.json`. If the file is missing, stale, or MCP started before first `begin_prewarm`, heartbeats still hit the engine during GIL hold.

### I. Dual `begin_prewarm` + process recycle

Engine.json PID vs `warm_phase.pid` vs listener PID can disagree (wrapper vs `pythonw`). A killed engine leaves `phase=prewarm`. Watchdog/ensure starts a **new** PID; MCP still reports warming; new process immediately starts another DML init under live Cursor HTTP — hang repeats (seen: pid 24832 → 22740, still `prewarm`).

### J. CPU-ORT regression

`uv tool install` can pull plain `onnxruntime` (no `DmlExecutionProvider`). Init still holds GIL; load is slower/different. Health wedge still happens; first map stays multi-second even when it “succeeds”.

### K. Indexer / keeper / open_repo on same process

`ce_service.open_repo`, keeper ticks, AST hydrate in **locate** (not engine) can add GIL/CPU. Bridge path skips local FastEmbed; locate attach still `_kick_embed_prewarm` wait=True (E).

### L. Soft-ready ≠ dense-ready (product confusion)

Soft binder can be true in ~2s. Agents/status then `map`. Dense is still `prewarm`. Map that needs FastEmbed waits on GIL → timeout. Sim “green” if it maps after quiet settle; live map during `prewarm` fails.

### M. MCP sticky `engine_health_timeout`

Attach coordinator historically latched `warm_phase=down` after one health miss. Current code waits on `in_prewarm()` then still probes `/health`. If health never returns, MCP status stays STARTING even after engine later reaches `dense`.

### N. Port listener ≠ serving

`engine_process_alive` uses lock/pid/port. Port LISTENING with GIL stuck still counts as alive. Watchdog: skip restart.

---

## 7. How they compose (typical live failure)

```
Cursor MCP up
  → attach POST /v1/embed/prewarm wait=True     (E)
  → async thread begin_prewarm + embed_one      (C, A)
  → GIL held; /health + map HTTP dead           (A)
  → watchdog ignores fails; idle stop postponed (D)
  → if DML contends with keepalive/map          (B, F, G) → embed_one never returns
  → phase stays prewarm past 35s…137s…          (observed)
  → optional recycle → new PID, same attach load under Cursor (I) → repeat
```

**Most likely live composition:** A + B + D + E. GIL-held DML init, extra HTTP/keepalive/map during init, watchdog/idle **protect the hang**, attach `wait=True` adds more GIL waiters. Not “engine crashed.” Not “need more settle time.”

**Disproven as sole cause:** quiet-sim PASS (it avoided E/F). CPU cap (already 0). Missing DML *alone* (repair restored DML; hang continued).

---

## 8. What a real fix has to change

1. **Never HTTP-poll or `wait=True` join during `prewarm`** (attach, heartbeat, sim, map).
2. **Hard-abort hung prewarm** well under 180s (e.g. 45s) and recycle the engine process — do not “ignore health” forever.
3. **One ORT owner:** no keepalive, no search embed, no second prewarm until `end_prewarm`.
4. **Map while `prewarm`:** return warming + side-channel, do not block on `/health` or dense embed.
5. **Preflight DML** on every install; fail closed.

**0.3.99 shipped these:** attach/`_kick_embed_prewarm` is fire-and-forget (`wait=False`);
`/v1/embed/prewarm` never parks the HTTP worker; `begin_prewarm` does not refresh a
live stamp; `DEFAULT_PREWARM_MAX_AGE_S=45`; search/map return `warming` while
`phase=prewarm`; keepalive does not re-kick ORT. Lane B is no longer pin-only —
it runs the same close→unload→open→≥30s settle→map SLA with `CTX_MCP_CLIENT=kiro`.