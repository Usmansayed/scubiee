# Cursor-open production battery — 0.3.95

**Date:** 2026-09-16 04:30:59
**Harness:** cold kill → Cursor-client Lane A settle → warm_contract → ship_check → mcp.json pins

**Verdict: PASS**

## Results

| Step | Result | Key numbers |
|------|--------|-------------|
| **mcp.json pins** | PASS | {"CTX_MCP_CLIENT": "cursor", "CTX_EMBED_KEEPALIVE": "1", "CTX_EMBED_KEEPALIVE_S": "15", "CTX_EMBED_PREWARM": "1", "CTX_SCUBIEE_BUILD": "0.3.95-1789508309"} |
| **cold_start_acceptance** | PASS | exit=0 wall_ms=7327.7 |
| **Lane A settle (30s, client=cursor)** | PASS | exit=0; scenario=cursor_cold_attach_steady_leave; clean_slate=ok 10731.9ms; host_start=ok 3839.6ms; auto_warm=ok 6128.9ms; settle=ok 26926.5ms; settle_join_embedder=ok 50062.5ms; map_first=ok 157.5ms; pack_first=ok 77.4ms; expand_first=ok 793.3ms |
| **warm_contract (idle 45s)** | PASS | ensure_exit=0 warm_exit=0 wall_ms=306957.0 |
| **ship_check** | PASS | exit=0 wall_ms=11003.1 |

## Notes

- Lane A uses CTX_MCP_CLIENT=cursor (matches .cursor/mcp.json).
- Settle idle after soft-ready: 30s (Cursor-open analogue).
- Settle requires embedder_loaded (or successful dense map) before map_first ≤1s (0.3.95).
- Engine is killed only before Lane A cold attach; warm_contract uses `engine ensure` + `--no-stop` (avoid DirectML re-init wedge).
- Engine + MCP procs are killed before Lane A cold attach.
