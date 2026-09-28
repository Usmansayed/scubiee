# Kiro with/without Scubiee MCP A/B

**Date:** 2026-09-05T04:00:23.755502+00:00
**Model:** `claude-haiku-4.5` · **Effort:** `medium`
**Tasks:** 5 locate-only · **Runs:** 10

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
| with | 5 | 64366.0 | 1255.0 | 0.306 | 0.9 | 0.883 | 4.4 | 5.2 | OK |
| without | 5 | 87977.82 | 3164.8 | 0.778 | 1.0 | 0.867 | 0.0 | 17.0 | OK |

### Deltas (with − without)

| Metric | with | without | delta | interpretation |
|--------|-----:|--------:|------:|----------------|
| mean wall_ms | 64366 | 87978 | **−23612 (−27%)** | with Scubiee faster |
| mean ~tokens (stdout/4) | 1255 | 3165 | **−1910 (−60%)** | with Scubiee leaner tool dumps |
| mean credits | 0.306 | 0.778 | **−0.472 (−61%)** | with Scubiee cheaper |
| mean file_rec | 0.90 | 1.00 | −0.10 | without slightly higher file hit |
| mean symbol_rec | 0.883 | 0.867 | +0.016 | roughly parity |
| mean native tool calls | 5.2 | 17.0 | −11.8 | with replaces thrash with MCP |

Isolation: both arms OK (with always called `@scubiee/*`; without never did). Full logs under `out/kiro_ab/20260905T040023Z/`.

## Per-run

| task | arm | wall_ms | ~tok | credits | file_rec | symbol_rec | scubiee# | native# | isolation | log |
|------|-----|--------:|-----:|--------:|---------:|-----------:|---------:|--------:|-----------|-----|
| P01_connect_permissions | with | 79375.5 | 2062 | 0.62 | 1.0 | 1.0 | 3 | 17 | OK | `out/kiro_ab/20260905T040023Z/P01_connect_permissions__with.log` |
| P01_connect_permissions | without | 83208.8 | 2275 | 0.99 | 1.0 | 1.0 | 0 | 14 | OK | `out/kiro_ab/20260905T040023Z/P01_connect_permissions__without.log` |
| P02_pack_context | with | 56817.8 | 933 | 0.19 | 0.5 | 0.75 | 2 | 3 | OK | `out/kiro_ab/20260905T040023Z/P02_pack_context__with.log` |
| P02_pack_context | without | 85119.9 | 2223 | 0.49 | 1.0 | 1.0 | 0 | 19 | OK | `out/kiro_ab/20260905T040023Z/P02_pack_context__without.log` |
| P05_gate_rules | with | 67724.6 | 1516 | 0.31 | 1.0 | 0.667 | 4 | 6 | OK | `out/kiro_ab/20260905T040023Z/P05_gate_rules__with.log` |
| P05_gate_rules | without | 41048.5 | 1908 | 0.55 | 1.0 | 0.667 | 0 | 8 | OK | `out/kiro_ab/20260905T040023Z/P05_gate_rules__without.log` |
| P09_uv_tool_unlock | with | 51178.2 | 592 | 0.16 | 1.0 | 1.0 | 4 | 0 | OK | `out/kiro_ab/20260905T040023Z/P09_uv_tool_unlock__with.log` |
| P09_uv_tool_unlock | without | 149226.6 | 6196 | 1.43 | 1.0 | 0.667 | 0 | 24 | OK | `out/kiro_ab/20260905T040023Z/P09_uv_tool_unlock__without.log` |
| P10_auth_fixture | with | 66733.9 | 1172 | 0.25 | 1.0 | 1.0 | 9 | 0 | OK | `out/kiro_ab/20260905T040023Z/P10_auth_fixture__with.log` |
| P10_auth_fixture | without | 81285.3 | 3222 | 0.43 | 1.0 | 1.0 | 0 | 20 | OK | `out/kiro_ab/20260905T040023Z/P10_auth_fixture__without.log` |

## Protocol notes

```json
{
  "model": "claude-haiku-4.5",
  "effort": "medium",
  "timeout_s": 300,
  "n_tasks": 5,
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
    "warm": false,
    "warm_state": "ready",
    "generation": 8,
    "index_usable": true,
    "last_sync_at": 1788580751.4344428,
    "repo": "C:\\Users\\usman\\Downloads\\context-engine",
    "dashboard": "/dashboard",
    "api": "/v1/*"
  },
  "kiro_cli": "C:\\Users\\usman\\AppData\\Local\\Kiro-Cli\\kiro-cli.exe",
  "bridge": "C:\\Users\\usman\\.local\\bin\\scubiee-mcp-bridge.EXE",
  "project_id": "ce_d9cb766c3820091ed9ffbc64ef33063c",
  "run_id": "20260905T040023Z"
}
```

