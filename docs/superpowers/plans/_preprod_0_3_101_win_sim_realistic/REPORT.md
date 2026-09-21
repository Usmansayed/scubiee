# Realistic pre-prod battery (Windows) — 0.3.101

**Date:** 2026-09-21  
**Machine:** Windows 10 (this PC)  
**Install:** `uv tool` scubiee **0.3.101** (local wheel from this tip)  
**ORT:** DirectML `1.24.4` (`DmlExecutionProvider`, `CPUExecutionProvider`)  
**Keepalive:** `CTX_EMBED_KEEPALIVE=1`, `CTX_EMBED_KEEPALIVE_S=8` (+ post-search cooldown, `abort_if_search`, capped graph touch)  
**Harness:** live MCP in Cursor + CLI engine + Lane A `mcp_host_sim` (no `CTX_SIM_DEV`) + ship_check + warm_contract  

**Verdict: Cursor / Lane A PASS** (final artifact `mcp-host-sim-20260921T184003Z`).  
Contention fixes required for dual Cursor MCP + host-sim `clean_slate` (dummy search pile-up + keepalive FIFO ahead of unique maps). Kiro Lane B not re-run on this tip.

---

## Latest Lane A (tip, 2026-09-21 evening)

```text
python scripts/mcp_host_sim.py --lane a --live --settle-s 40 --idle-s 120 --mcp-client cursor
```

| Phase | ok | ms | Budget |
|-------|----|----|--------|
| soft_ready | True | ~16s | 40s |
| map_first | True | **69** | ≤3s |
| map_second (unique) | True | **64** | ≤1s |
| status_first | True | **458** | ≤3s |
| pack_first | True | **77** | ≤1s |
| expand_first | True | **75** | ≤1s |
| idle_hold | True | ~120s | — |
| post_idle_map (unique) | True | **153** (attempt 1) | ≤1s |
| post_idle_pack | True | **70** | ≤1s |
| unload | True | 14 | 35s |

**ok=true**, elapsed **170s**. Units: keepalive/prewarm **24 passed**. ship_check / warm_contract: PASS.

Mac handoff: `docs/macos-handoff-0.3.101.md`.

---

## Morning baseline (same day, pre-contention-fix)

Lane A then: unique `map_second` **640ms**, `post_idle_map` **804ms**. Artifacts: `mcp-host-sim-20260921T151546Z`.

### Live Cursor MCP

Unique queries, `retrieve_mode=D_channel_best`, `dense=true`. Card `source` tags included **bm25 / dense / graph**.

| Call | Result | Time |
|------|--------|------|
| Unique map (pre-sim) | ok, D_channel_best | **1073ms** |
| Evening unique map (steady) | ok, D_channel_best | **593ms** |

### Lane B Kiro (morning)

| Phase | ok | ms | Budget |
|-------|----|----|--------|
| map_second unique | **FAIL `LOCATE_SLA`** | **1223** | ≤1s |

Do not ship Kiro as &lt;1s unique-map until re-run with `--idle-s 120`.

### CLI / dual install

`scubiee --version` **0.3.101**. Dual conda vs `uv tool` sharing `~/.scubiee` — **WARN**; keep a single install.

Safe CLI matrix JSON under this folder (`cli_matrix*.json`). Did not run wipe/halt/disconnect/`index --force`.

---

## Production gate (this PC)

| Gate | Status |
|------|--------|
| Cursor Lane A live settle 40s + idle 120s unique map &lt;1s | **PASS (153ms tip)** |
| Full D-channel on map | **PASS** |
| ship_check ladder | **PASS** |
| Keepalive/prewarm units | **PASS (24)** |
| Kiro Lane B unique map_second ≤1s | **FAIL (morning)** |
