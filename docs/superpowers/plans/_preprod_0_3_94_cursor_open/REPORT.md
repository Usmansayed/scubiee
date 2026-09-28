# Cursor-open production battery — 0.3.94

**Date:** 2026-09-16 02:46:48
**Harness:** cold kill → Cursor-client Lane A settle → warm_contract → ship_check → mcp.json pins

**Verdict: FAIL**

## Results

| Step | Result | Key numbers |
|------|--------|-------------|
| **mcp.json pins** | PASS | {"CTX_MCP_CLIENT": "cursor", "CTX_EMBED_KEEPALIVE": "1", "CTX_EMBED_KEEPALIVE_S": "15", "CTX_EMBED_PREWARM": "1", "CTX_SCUBIEE_BUILD": "0.3.94-1789504399"} |
| **cold_start_acceptance** | PASS | exit=0 wall_ms=7733.8 |
| **Lane A settle (30s, client=cursor)** | FAIL | exit=1; scenario=cursor_cold_attach_steady_leave; clean_slate=ok 10765.5ms; host_start=ok 3582.6ms; auto_warm=ok 4058.0ms; settle=ok 28995.6ms; settle_join_embedder=SETTLE_EMBED_NOT_READY 161891.5ms |
| **warm_contract (idle 45s)** | FAIL | exit=1 wall_ms=45820.9 |
| **ship_check** | FAIL | exit=1 wall_ms=67671.2 |

## Notes

- Lane A uses CTX_MCP_CLIENT=cursor (matches .cursor/mcp.json).
- Settle idle after soft-ready: 30s (Cursor-open analogue).
- Settle requires embedder_loaded before map_first ≤1s (0.3.94).
- Engine + MCP procs are killed before Lane A and warm_contract cold legs.

## Errors

- Lane A Cursor settle failed — see host_sim_lane_a_cursor_settle.log / mcp-host-sim-*.md
- warm_contract_acceptance failed — see warm_contract.log
- ship_check failed — see ship_check.log
