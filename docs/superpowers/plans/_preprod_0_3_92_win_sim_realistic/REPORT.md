# Realistic MCP host-sim battery (Windows) — 0.3.92

**Date:** 2026-09-15  
**Harness:** live `uv tool` scubiee + Lane A / warm_contract / ship_check  
**ORT:** DirectML restored (`DmlExecutionProvider`; CPU `onnxruntime==1.30` drained)

**Verdict: PASS** (Lane A, warm_contract, ship_check all exit 0)

## Results

| Step | Result | Key numbers |
|------|--------|-------------|
| **Lane A settle** `--settle-s 8` true-first-map | PASS | soft ~8.8s; map 451ms; pack 57ms; expand 765ms; post-idle map 74ms / pack 61ms |
| **warm_contract** `--idle-s 60` | PASS | soft ready ~5.8s; first map 671ms; after idle map 260ms; failed=0 |
| **ship_check** | PASS | gate→map→pack→expand→status→workspace→collect all ok (~4.4s) |

## SLA check (Lane A)

| Budget | Met? |
|--------|------|
| soft_ready ≤30s | Yes (~8.8s) |
| map_first ≤1000ms | Yes (451ms) |
| pack_first ≤1000ms | Yes (57ms) |
| expand_first ≤5000ms | Yes (765ms) |
| post-idle locate | Yes (~60–75ms) |

## Notes

- Earlier ship_check fail was `expand_context` / `ast_warming` before DML repair + clean re-warm.
- Watchdog hung-PID heal unit suite: 13 passed (separate from this battery).
