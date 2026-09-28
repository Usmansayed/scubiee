# Kiro with/without Scubiee MCP A/B

**Date:** 2026-09-05T04:16:05.185838+00:00
**Model:** `auto` · **Effort:** `medium`
**Tasks:** 10 locate-only · **Runs:** 20

## Fairness / isolation

- Same cwd, model, effort, trust-all-tools
- Sequential (not parallel) — shared machine resources
- Agents: `ab_with_scubiee` vs `ab_without_scubiee`
- `includeMcpJson=false` on both; agent owns MCP surface
- User + project `mcp.json` neutralized during the suite (restored after)
- Locate-only prompts (no edits)

## Scoreboard

| Arm | n | mean wall_ms | ~tokens | credits | file_rec | symbol_rec | scubiee tools | native tools | isolation |
|-----|---|-------------:|--------:|--------:|---------:|-----------:|--------------:|-------------:|-----------|
| with | 10 | 76528.81 | 10771.5 | 0.845 | 1.0 | 0.955 | 1.9 | 4.4 | OK |
| without | 10 | 68871.55 | 31872.5 | 1.374 | 1.0 | 0.98 | 0.0 | 6.8 | OK |

### Deltas (with − without)

| Metric | delta |
|--------|------:|
| mean wall_ms | +7.66e+03 (+11%) |
| mean ~tokens | -2.11e+04 (-66%) |
| mean credits | -0.529 (-39%) |
| mean file_rec | +0 (+0%) |
| mean symbol_rec | -0.025 (-3%) |

## Per-run

| task | arm | wall_ms | ~tok | credits | file_rec | symbol_rec | scubiee# | native# | isolation | log |
|------|-----|--------:|-----:|--------:|---------:|-----------:|---------:|--------:|-----------|-----|
| C01_connect_permissions_gate | with | 76486.3 | 2142 | 0.83 | 1.0 | 0.8 | 2 | 4 | OK | `out/kiro_ab/20260905T041605Z/C01_connect_permissions_gate__with.log` |
| C01_connect_permissions_gate | without | 53342.0 | 2302 | 1.81 | 1.0 | 0.8 | 0 | 5 | OK | `out/kiro_ab/20260905T041605Z/C01_connect_permissions_gate__without.log` |
| C02_pack_expand_ladder | with | 101597.0 | 2936 | 1.3 | 1.0 | 1.0 | 2 | 7 | OK | `out/kiro_ab/20260905T041605Z/C02_pack_expand_ladder__with.log` |
| C02_pack_expand_ladder | without | 76504.3 | 9027 | 2.12 | 1.0 | 1.0 | 0 | 9 | OK | `out/kiro_ab/20260905T041605Z/C02_pack_expand_ladder__without.log` |
| C03_composite_vs_poly_escape | with | 65953.2 | 1151 | 0.51 | 1.0 | 0.75 | 2 | 2 | OK | `out/kiro_ab/20260905T041605Z/C03_composite_vs_poly_escape__with.log` |
| C03_composite_vs_poly_escape | without | 41389.2 | 5893 | 0.42 | 1.0 | 1.0 | 0 | 3 | OK | `out/kiro_ab/20260905T041605Z/C03_composite_vs_poly_escape__without.log` |
| C04_graphify_store_vs_rebuild | with | 65249.9 | 1159 | 0.44 | 1.0 | 1.0 | 2 | 2 | OK | `out/kiro_ab/20260905T041605Z/C04_graphify_store_vs_rebuild__with.log` |
| C04_graphify_store_vs_rebuild | without | 77760.1 | 2797 | 0.58 | 1.0 | 1.0 | 0 | 8 | OK | `out/kiro_ab/20260905T041605Z/C04_graphify_store_vs_rebuild__without.log` |
| C05_incremental_merkle_confirm | with | 75312.2 | 1801 | 0.87 | 1.0 | 1.0 | 2 | 4 | OK | `out/kiro_ab/20260905T041605Z/C05_incremental_merkle_confirm__with.log` |
| C05_incremental_merkle_confirm | without | 104292.5 | 19373 | 2.45 | 1.0 | 1.0 | 0 | 11 | OK | `out/kiro_ab/20260905T041605Z/C05_incremental_merkle_confirm__without.log` |
| C06_session_isolation_parallel | with | 66897.3 | 2672 | 0.97 | 1.0 | 1.0 | 1 | 6 | OK | `out/kiro_ab/20260905T041605Z/C06_session_isolation_parallel__with.log` |
| C06_session_isolation_parallel | without | 53117.0 | 5397 | 1.44 | 1.0 | 1.0 | 0 | 5 | OK | `out/kiro_ab/20260905T041605Z/C06_session_isolation_parallel__without.log` |
| C07_kiro_mcp_install | with | 86605.0 | 3462 | 0.94 | 1.0 | 1.0 | 2 | 5 | OK | `out/kiro_ab/20260905T041605Z/C07_kiro_mcp_install__with.log` |
| C07_kiro_mcp_install | without | 118964.3 | 260398 | 1.88 | 1.0 | 1.0 | 0 | 10 | OK | `out/kiro_ab/20260905T041605Z/C07_kiro_mcp_install__without.log` |
| C08_uv_access_denied_vague | with | 106128.8 | 89473 | 1.48 | 1.0 | 1.0 | 2 | 7 | OK | `out/kiro_ab/20260905T041605Z/C08_uv_access_denied_vague__with.log` |
| C08_uv_access_denied_vague | without | 43353.1 | 1627 | 1.65 | 1.0 | 1.0 | 0 | 6 | OK | `out/kiro_ab/20260905T041605Z/C08_uv_access_denied_vague__without.log` |
| C09_auth_jwt_trap | with | 30383.3 | 785 | 0.27 | 1.0 | 1.0 | 1 | 1 | OK | `out/kiro_ab/20260905T041605Z/C09_auth_jwt_trap__with.log` |
| C09_auth_jwt_trap | without | 23710.7 | 911 | 0.32 | 1.0 | 1.0 | 0 | 3 | OK | `out/kiro_ab/20260905T041605Z/C09_auth_jwt_trap__without.log` |
| C10_warm_status_ready | with | 90675.1 | 2134 | 0.84 | 1.0 | 1.0 | 3 | 6 | OK | `out/kiro_ab/20260905T041605Z/C10_warm_status_ready__with.log` |
| C10_warm_status_ready | without | 96282.3 | 11000 | 1.07 | 1.0 | 1.0 | 0 | 8 | OK | `out/kiro_ab/20260905T041605Z/C10_warm_status_ready__without.log` |

## Protocol notes

```json
{
  "model": "auto",
  "effort": "medium",
  "timeout_s": 420,
  "n_tasks": 10,
  "arms": [
    "with",
    "without"
  ],
  "sequential": true,
  "agent_engine": "v1",
  "legacy_ui": true,
  "trust_all_tools": true,
  "locate_only": true,
  "includeMcpJson": false,
  "mcp_neutralized": [
    "project .kiro/settings/mcp.json",
    "user ~/.kiro/settings/mcp.json"
  ],
  "agents": {
    "with": "ab_with_scubiee",
    "without": "ab_without_scubiee"
  },
  "engine_health": {
    "ok": true,
    "service": "scubiee",
    "version": "0.3.15",
    "warm": true,
    "warm_state": "ready",
    "generation": 12,
    "index_usable": true,
    "last_sync_at": 1788581760.9876974,
    "repo": "C:\\Users\\usman\\Downloads\\context-engine",
    "dashboard": "/dashboard",
    "api": "/v1/*"
  },
  "kiro_cli": "C:\\Users\\usman\\AppData\\Local\\Kiro-Cli\\kiro-cli.exe",
  "bridge": "C:\\Users\\usman\\.local\\bin\\scubiee-mcp-bridge.EXE",
  "project_id": "ce_d9cb766c3820091ed9ffbc64ef33063c",
  "run_id": "20260905T041605Z"
}
```

