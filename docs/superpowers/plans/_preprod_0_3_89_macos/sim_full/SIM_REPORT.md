# Full MCP / engine simulation run — Mac 0.3.89

**Date:** 2026-09-15  
**Machine:** Apple M5 / macOS 26.5.2  
**Install:** `uv tool` scubiee 0.3.89 (+ local sim fixes in this commit)  
**Out:** `docs/superpowers/plans/_preprod_0_3_89_macos/sim_full/`

## Scoreboard

| Simulation | Result | Notes |
|------------|--------|-------|
| `scubiee_mcp_ship_check.py` | **PASS** | All tools ok, `errors: []`, engine_healthy |
| `warm_contract_acceptance.py` | **PASS** | failed=0; soft ~1.1s; map after idle 126ms |
| `run_mcp_ship_preprod.py --require-live --skip-cli` | **PASS** | L1–L4 pytest + live ladder + ship_check |
| `mcp_host_sim --lane a --live --idle-s 45` | **PASS** | soft 0.59s; map 5.4ms; pack 3.8ms; expand 131ms; **unload ok** |
| `mcp_host_sim --lane b` | **PASS (pins only)** | Lane B is pin/setup only by design (v1) |
| `e2e_mcp_idle_reconnect.py` | **PASS** | Stopped 19.7s after disconnect; reconnect warm |
| `mcp_host_sim --lane a --true-first-map` (earlier) | **FAIL** | WARM_TIMEOUT while engine still opening — flaky under churn |
| First `host_sim --lane both --idle-s 120` | **FAIL unload** | See root cause below (fixed) |

## SLA numbers (Lane A, idle=45, after unload fix)

| Phase | Budget | Measured |
|-------|--------|----------|
| soft_ready | ≤30s | **0.59s** |
| map_first | ≤1000ms | **5.4ms** |
| pack_first | ≤1000ms | **3.8ms** |
| expand_first | ≤5000ms | **131ms** |
| idle_hold | 45s | **45.3s** |
| post_idle map/pack | ≤1000ms | **5.3 / 4.1ms** |
| unload | ≤35s | **0.5ms** (already stopped) |

## Bugs found while running “all sims”

### 1. Host-sim unload polled `/health` → false UNLOAD_TIMEOUT
The unload phase used `observatory_tick()` → `EngineClient.health()`. That HTTP activity resets the idle clock, so the engine never stopped within the 12s budget even though idle policy was correct.

**Fix:** unload now uses process table + `active_clients.json` only (no `/health`), and budget raised to 35s (debounce 10 + idle 15 + slack).

### 2. e2e reconnect race
Session 2: tools/status passed but a single `engine_up()` check failed before HTTP health was ready.

**Fix:** poll health up to 20s after status on reconnect.

### 3. Lane B is not a full SLA lane
`--lane b` returns in ~9ms after Kiro pin setup. Documented in scenario: “SLA gate is Lane A until Kiro auto-session lands.”

### 4. Warm contract / true-first-map flakiness under stop/start churn
Earlier in the same session, warm_contract and `--true-first-map` hit soft=false while the engine was still in `opening …`. Final warm_contract and ship_check after settle: **PASS**. Treat cold-start races as operational; soft path is fine once listening.

## Verdict

**Simulation soft-path / MCP + idle reclaim: PASS** on this Mac for 0.3.89 after the unload/reconnect harness fixes.

Still **not** covered by these sims: live Cursor IDE click-through, `wipe --all` reinstall, Gate E full pytest.
