# Realistic MCP host-sim battery (Windows) — 0.3.89

**Date:** 2026-09-15  
**While:** Mac Gate M running in parallel  
**Harness:** live `uv tool` scubiee + `scripts/mcp_host_sim.py` / warm / ship — not unit pytest  

**Verdict: PASS** (all steps `*_exit=0` and `"ok": true`).  
Outer script printed `SOME_FAIL` due to a PowerShell `$LASTEXITCODE` capture glitch after `Tee-Object`; ignore that — each step log shows exit 0.

## Results

| Step | Result | Key numbers |
|------|--------|-------------|
| **Lane A** `--live --skip-idle` | PASS | soft ~8.9s; map 74ms; pack 60ms; expand 675ms |
| **Lane A settle** `--settle-s 8` true-first-map | PASS | soft ~3.1s; **first map after settle 392ms** (≤1s); pack 51ms; expand 600ms |
| **Lane A idle 60s** | PASS | map 66ms; pack 62ms; post_idle map 52ms / pack 67ms; unload ok |
| **Lane B** | PASS | ok in ~51ms (pin/smoke path) |
| **warm_contract** | PASS | soft ready ~6.3s; first map ~2.6s; after 60s idle map 267ms; failed=0 |
| **ship_check** | PASS | gate→map→pack→expand→status→workspace→collect all ok (~8.5s) |

## SLA check (Lane A)

| Budget | Met? |
|--------|------|
| soft_ready ≤30s | Yes (3–9s) |
| map_first ≤1000ms | Yes (66–392ms; true-first after settle still &lt;1s) |
| pack_first ≤1000ms | Yes (~50–60ms) |
| expand_first ≤5000ms | Yes (~0.6–0.7s) |
| post-idle locate | Yes (~50–70ms) |

## Artifacts

`docs/superpowers/plans/_preprod_0_3_89_win_sim_realistic/`
- `master.log`, per-step `*.log`
- `mcp-host-sim-*.json` / `.md` reports

## Note for Mac operator

Windows sim soft-path still green under realistic settle + idle hold. Mac should mirror Lane A `--live` (+ optional `--settle-s 8`) with the same budgets.
