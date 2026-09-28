# Pack-context + few-call bakeoff

**Date:** 2026-09-04  
**Goal:** Full useful context in fewest agent calls; measure tokens vs guide+native.

## Spec

### `pack_context(query, seed…, k, hot_threshold, budget_chars)`
One call returns:
- `heatmap`: slim cards (rank, score, heat, loc, symbol, why) — noise-filtered
- `pack`: bodies for hot nodes under `budget_chars` (auto collect)
- `cold`: loc-only alts not packed
- `stats`: calls=1, chars, n_hot, n_packed
- short `next` hint only if pack incomplete

Noise drop: `cli_ui.py`, symbols matching `^(error|info|warn|success|colors|table|status_line|ICON_|_Scrub)` unless query mentions them.

### Keep existing tools
`map_context` / `expand_context` / `collect_hot_context` remain for A/B arms.

### Bakeoff arms
- **A** guide: map_context only (chars of JSON; simulate N Reads = sum of card line spans × 40 chars)
- **B** guide+collect: map_context + collect_hot
- **C** pack: pack_context once

Cases: auth fixture seed; connect `cmd_connect` seed.  
Metrics: tool_calls, response_chars, packed_must_hit (auth gold path), useful_card_frac.

## Files
- `packages/pipeline/context_trace.py` — `run_pack_context`, noise filter, slim cards
- `packages/pipeline/mcp_locate.py` — register tool + instructions
- `packages/pipeline/mcp_permissions.py` — allowlist `pack_context`
- `packages/pipeline/rules_installer.py` — prefer pack for full-context
- `packages/trace_lab/pack_bakeoff.py` + CLI
- `docs/superpowers/specs/2026-09-04-pack-context-few-calls-design.md`
- `docs/superpowers/plans/2026-09-04-pack-context-bakeoff.md`

## Tasks
1. Spec (this + design doc)
2. Backend `run_pack_context` + tests/smoke
3. MCP wire + permissions
4. Bakeoff runner + results JSON
5. GATE/MCP instruction update
6. Local install / connect
