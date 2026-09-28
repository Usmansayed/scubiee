# Kiro with/without Scubiee MCP A/B

**Date:** 2026-09-07T08:55:44.620421+00:00
**Model:** `auto` · **Effort:** `medium`
**Tasks:** 11 locate-only · **Runs:** 22

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
| with | 11 | 154420.764 | 3151.0 | 1.07 | 0.932 | 0.929 | 2.545 | 6.364 | OK |
| without | 11 | 237264.982 | 4934.636 | 1.148 | 0.909 | 0.941 | 0.0 | 6.545 | OK |

### Deltas (with − without)

| Metric | delta |
|--------|------:|
| mean wall_ms | -8.28e+04 (-35%) |
| mean ~tokens | -1.78e+03 (-36%) |
| mean credits | -0.078 (-7%) |
| mean file_rec | +0.023 (+3%) |
| mean symbol_rec | -0.012 (-1%) |

## Per-run

| task | arm | wall_ms | ~tok | credits | file_rec | symbol_rec | scubiee# | native# | isolation | log |
|------|-----|--------:|-----:|--------:|---------:|-----------:|---------:|--------:|-----------|-----|
| C01_connect_permissions_gate | with | 204136.6 | 4587 | 1.98 | 1.0 | 0.8 | 2 | 12 | OK | `out/kiro_ab/20260907T085544Z/C01_connect_permissions_gate__with.log` |
| C01_connect_permissions_gate | without | 108660.9 | 6351 | 1.58 | 1.0 | 0.6 | 0 | 11 | OK | `out/kiro_ab/20260907T085544Z/C01_connect_permissions_gate__without.log` |
| C02_pack_expand_ladder | with | 234276.5 | 5140 | 1.73 | 1.0 | 1.0 | 3 | 11 | OK | `out/kiro_ab/20260907T085544Z/C02_pack_expand_ladder__with.log` |
| C02_pack_expand_ladder | without | 106091.5 | 5202 | 2.07 | 1.0 | 1.0 | 0 | 8 | OK | `out/kiro_ab/20260907T085544Z/C02_pack_expand_ladder__without.log` |
| C03_composite_vs_poly_escape | with | 105431.8 | 879 | 0.46 | 1.0 | 0.75 | 3 | 2 | OK | `out/kiro_ab/20260907T085544Z/C03_composite_vs_poly_escape__with.log` |
| C03_composite_vs_poly_escape | without | 1768218.2 | 800 | None | 0.0 | 0.75 | 0 | 3 | OK | `out/kiro_ab/20260907T085544Z/C03_composite_vs_poly_escape__without.log` |
| C04_graphify_store_vs_rebuild | with | 61427.8 | 1612 | 0.71 | 1.0 | 1.0 | 2 | 3 | OK | `out/kiro_ab/20260907T085544Z/C04_graphify_store_vs_rebuild__with.log` |
| C04_graphify_store_vs_rebuild | without | 127712.3 | 3008 | 0.57 | 1.0 | 1.0 | 0 | 6 | OK | `out/kiro_ab/20260907T085544Z/C04_graphify_store_vs_rebuild__without.log` |
| C05_incremental_merkle_confirm | with | 91847.2 | 1673 | 0.79 | 1.0 | 1.0 | 2 | 4 | OK | `out/kiro_ab/20260907T085544Z/C05_incremental_merkle_confirm__with.log` |
| C05_incremental_merkle_confirm | without | 45180.5 | 1304 | 1.2 | 1.0 | 1.0 | 0 | 3 | OK | `out/kiro_ab/20260907T085544Z/C05_incremental_merkle_confirm__without.log` |
| C06_session_isolation_parallel | with | 109407.1 | 3721 | 1.24 | 1.0 | 1.0 | 2 | 10 | OK | `out/kiro_ab/20260907T085544Z/C06_session_isolation_parallel__with.log` |
| C06_session_isolation_parallel | without | 108618.0 | 8708 | 1.11 | 1.0 | 1.0 | 0 | 7 | OK | `out/kiro_ab/20260907T085544Z/C06_session_isolation_parallel__without.log` |
| C07_kiro_mcp_install | with | 148464.8 | 9966 | 1.87 | 1.0 | 1.0 | 3 | 16 | OK | `out/kiro_ab/20260907T085544Z/C07_kiro_mcp_install__with.log` |
| C07_kiro_mcp_install | without | 96122.9 | 14207 | 1.08 | 1.0 | 1.0 | 0 | 10 | OK | `out/kiro_ab/20260907T085544Z/C07_kiro_mcp_install__without.log` |
| C08_uv_access_denied_vague | with | 70164.8 | 871 | 0.38 | 1.0 | 1.0 | 2 | 1 | OK | `out/kiro_ab/20260907T085544Z/C08_uv_access_denied_vague__with.log` |
| C08_uv_access_denied_vague | without | 43296.6 | 990 | 0.91 | 1.0 | 1.0 | 0 | 3 | OK | `out/kiro_ab/20260907T085544Z/C08_uv_access_denied_vague__without.log` |
| C09_auth_jwt_trap | with | 47525.1 | 1226 | 0.5 | 1.0 | 1.0 | 3 | 2 | OK | `out/kiro_ab/20260907T085544Z/C09_auth_jwt_trap__with.log` |
| C09_auth_jwt_trap | without | 24385.8 | 925 | 0.32 | 1.0 | 1.0 | 0 | 3 | OK | `out/kiro_ab/20260907T085544Z/C09_auth_jwt_trap__without.log` |
| C10_warm_status_ready | with | 80689.9 | 3788 | 1.04 | 1.0 | 1.0 | 4 | 6 | OK | `out/kiro_ab/20260907T085544Z/C10_warm_status_ready__with.log` |
| C10_warm_status_ready | without | 81061.5 | 6131 | 1.42 | 1.0 | 1.0 | 0 | 8 | OK | `out/kiro_ab/20260907T085544Z/C10_warm_status_ready__without.log` |
| C11_pack_bodies_optin_collect | with | 545256.8 | 1198 | None | 0.25 | 0.667 | 2 | 3 | OK | `out/kiro_ab/20260907T085544Z/C11_pack_bodies_optin_collect__with.log` |
| C11_pack_bodies_optin_collect | without | 100566.6 | 6655 | 1.22 | 1.0 | 1.0 | 0 | 10 | OK | `out/kiro_ab/20260907T085544Z/C11_pack_bodies_optin_collect__without.log` |

## Protocol notes

```json
{
  "model": "auto",
  "effort": "medium",
  "timeout_s": 420,
  "n_tasks": 11,
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
    "version": "0.3.25",
    "warm": false,
    "warm_state": "ready",
    "generation": 13,
    "index_usable": true,
    "last_sync_at": 1788771174.4058187,
    "repo": "C:\\Users\\usman\\Downloads\\context-engine",
    "dashboard": "/dashboard",
    "api": "/v1/*"
  },
  "kiro_cli": "C:\\Users\\usman\\AppData\\Local\\Kiro-Cli\\kiro-cli.exe",
  "bridge": "C:\\Users\\usman\\.local\\bin\\scubiee-mcp-bridge.EXE",
  "project_id": "ce_d9cb766c3820091ed9ffbc64ef33063c",
  "run_id": "20260907T085544Z"
}
```

