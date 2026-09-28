# Scubiee Runtime Simplification Design (Approach 3)

**Date:** 2026-09-13  
**Status:** Draft for implementation  
**Product contract (unchanged):** Cursor open → warm ≤10s → map/pack stay ms while any client connected → unload only when all clients gone.

## Problem

Reliability failures are mostly **trigger fan-out**, not missing features:

- Multiple warm entrypoints: `CTX_MCP_AUTO_WARM`, `CTX_MCP_ATTACH_WARM`, `ensure_mcp_runtime`, `_spawn_background_warm`, `/v1/embed/prewarm`, AST preload, pack-side hydrate join
- Home-grown HTTP (`urllib`) without shared retry/timeout policy → false `unreachable` / contradictory `status`
- Heartbeat + ensure TTL + demote + idle sweeper + watchdog all mutate “should engine be up?”

## Design principles

1. **One owner** for “is the runtime ready?” — `RuntimeController`
2. **Two knobs only** for agents: attach warm on/off; disconnect debounce seconds
3. **Libraries for glue**, not for product logic: `httpx` (timeouts/pool) + `tenacity` (transient retries with jitter + budget)
4. **Sync first** — keep `EngineClient` sync (MCP tools are sync). Do not async-rewrite MCP in this pass.
5. **Delete before add** — every new helper must retire ≥1 old path

## Target architecture

```
Cursor → mcp_bridge
            │ register client (kind=bridge)
            │ RuntimeController.ensure(ATTACH)
            ▼
         engine process  ←── single ensure_daemon owner
            │ /health + /v1/embed/prewarm (httpx+tenacity)
            ▼
         ReadySnapshot {engine, embedder, ast}
            │
mcp_locate ← RuntimeController.ensure(SERVE) before map/pack
            │ AST hydrate/bake only here (not in bridge)
            ▼
         map/pack hot path
```

### States (explicit)

| State | Meaning | Allowed actions |
|-------|---------|-----------------|
| `DOWN` | No engine listener | `ensure` spawn |
| `STARTING` | Spawned, waiting `/health` | poll only |
| `READY` | health ok + embedder loaded | map/pack |
| `DEGRADED` | health ok, embedder/AST lagging | join within deadline |
| `STOPPING` | last client left, debounce | no new warm kicks |

### Single env contract

| Env | Default | Role |
|-----|---------|------|
| `CTX_MCP_ATTACH_WARM` | `1` | Kick ensure on bridge/locate attach |
| `CTX_WARM_DEADLINE_MS` | `10000` | Max attach→READY budget |
| `CTX_DISCONNECT_DEBOUNCE_S` | `120` | Unload after last client |
| `CTX_ENGINE_HTTP_RETRIES` | `3` | tenacity attempts for idempotent GETs |
| `CTX_MCP_AUTO_WARM` | **removed** (alias→`CTX_MCP_ATTACH_WARM` one release) | |

### Library usage

- **httpx.Client**: connection reuse, split connect/read timeouts, replace `urllib` in `EngineClient`
- **tenacity**: retry only `ConnectError` / `TimeoutException` / 502–504 on GET/health/prewarm-status; never retry non-idempotent POSTs blindly; cap total retry budget to remaining warm deadline
- **Supervisor**: not an external daemon framework — one `RuntimeController` + existing watchdog as **only** process babysitter (no second home-grown sweeper inventing start policy)

## Delete / merge list

| Retire | Merge into |
|--------|------------|
| `mcp_auto_warm_on_connect` separate flag | `attach_warm_enabled` |
| `warm_engine_for_mcp` + `start_attach_warm_pipeline` + `_spawn_background_warm` | `RuntimeController.ensure(reason)` |
| Duplicate `/v1/status` vs `/health` probe logic | `ReadySnapshot.from_health()` |
| Bridge AST hydrate attempts | locate-only `AstStore.hydrate()` |
| Ad-hoc sleep/retry in map for warming | `ensure(SERVE)` join once |

## Non-goals (this pass)

- Async MCP / FastAPI rewrite
- Replacing FastEmbed/ORT model
- Changing composite_v1 / multi_seed quality
- New MCP tools

## Success metrics

- ≤3 public warm entrypoints callable from MCP: `attach`, `ensure`, `leave`
- Unit: RuntimeController state transitions table tests
- Live: warm ≤10s cold; map/pack p95 after idle ≤300ms / ≤800ms
- Zero contradictory status: never `warm_ready=true` with `embedder_loaded=false` from same snapshot
