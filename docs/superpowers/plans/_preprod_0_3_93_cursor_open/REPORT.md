# Cursor-open production battery — 0.3.93

**Date:** 2026-09-16 01:59:20
**Harness:** cold kill → Cursor-client Lane A settle → warm_contract → ship_check → mcp.json pins

**Verdict: FAIL**

## Results

| Step | Result | Key numbers |
|------|--------|-------------|
| **mcp.json pins** | PASS | {"CTX_MCP_CLIENT": "cursor", "CTX_EMBED_KEEPALIVE": "1", "CTX_EMBED_KEEPALIVE_S": "15", "CTX_EMBED_PREWARM": "1", "CTX_SCUBIEE_BUILD": "0.3.93-1789494421"} |
| **cold_start_acceptance** | PASS | exit=0 wall_ms=8792.0 |
| **Lane A settle (30s, client=cursor)** | FAIL | exit=1; scenario=cursor_cold_attach_steady_leave; clean_slate=ok 10952.2ms; host_start=ok 6949.1ms; auto_warm=ok 1696.8ms; settle=ok 34432.0ms; map_first=SETTLE_MAP_SLOW 2880.3ms |
| **warm_contract (idle 60s)** | FAIL | exit=1 wall_ms=45271.2 |
| **ship_check** | FAIL | exit=1 wall_ms=68068.7 |

## Notes

- Lane A uses CTX_MCP_CLIENT=cursor (matches .cursor/mcp.json).
- Settle idle after soft-ready: 30s (Cursor-open analogue).
- Engine + MCP procs are killed before Lane A and warm_contract cold legs.

## Errors

- Lane A Cursor settle failed — see host_sim_lane_a_cursor_settle.log / mcp-host-sim-*.md
- warm_contract_acceptance failed — see warm_contract.log
- ship_check failed — see ship_check.log
