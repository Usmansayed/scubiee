# Realistic MCP host-sim battery (Windows) — 0.3.93

**Date:** 2026-09-16  
**Harness:** live `uv tool` scubiee + Lane A / warm_contract / ship_check  
**ORT:** DirectML (`DmlExecutionProvider`)

**Verdict: PASS** (Lane A settle, warm_contract, ship_check all exit 0)

## Results

| Step | Result | Key numbers |
|------|--------|-------------|
| **Lane A settle** `--live --settle-s 8 --skip-idle` | PASS | soft ~7.3s; settle done ~14.9s; **map 398ms**; pack 72ms; expand 670ms |
| **warm_contract** `--idle-s 60 --no-stop` | PASS | soft ready ~0.8s; embedder joined; first map 4229ms; **after idle map 962ms**; failed=0 |
| **ship_check** | PASS | gate→map→pack→expand→status→workspace→collect all ok (~7.6s); `engine_healthy=true` |

## SLA check (Lane A)

| Budget | Met? |
|--------|------|
| soft_ready ≤30s | Yes (~7.3s) |
| map_first ≤1000ms (after settle) | Yes (398ms) |
| pack_first ≤1000ms | Yes (72ms) |
| expand_first ≤5000ms | Yes (670ms) |

## Also measured (quiet HTTP)

| Probe | Result |
|-------|--------|
| MAP2 after 45s idle + keepalive | **932ms** dense `D_channel_best` (PASS_SUBSECOND) |

## Fixes landed for this battery

- Dense map always (`retrieve_D_channel_best`); no skip_freshness/hash pseudo-dense
- Keepalive 15s + RLock (no `already_running` deadlock on touch/register)
- Nested `run_embed_infer` re-entrancy; sync/map/keepalive share one DML worker
- Locate-worker soft probe no longer dense-searches on attach (settle health)
- Observatory: heal stub PID (~5MB wrapper); sticky soft on `health ok:false` timeouts
- warm_contract: join `embedder_loaded` before ms-steady map gates

## Install (this machine)

- `uv tool install --force .` → **scubiee 0.3.93**
- Post-install: CPU `onnxruntime==1.30` had clobbered DirectML → drained + `onnxruntime-directml==1.24.4`; `scubiee setup --repair` reused dml profile
- Providers: `DmlExecutionProvider`, `CPUExecutionProvider`
- Engine `/health`: `version: 0.3.93`, soft ready, chunks indexed
