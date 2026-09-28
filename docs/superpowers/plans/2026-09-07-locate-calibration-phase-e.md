# Locate calibration — Phase E (Prefer/Forbid GATE + MCP ship)

**Date:** 2026-09-07  
**Status:** **shipped + live-verified** (GATE rewrite + MCP reload; C09 needle over_use 0)

## What shipped

| Surface | Change |
|---------|--------|
| `managed_gate_usage_short` / overview / MCP header | LOCATE PRIORITY Prefer/Forbid (§6.1 / §6.3) |
| `SERVER_INSTRUCTIONS_PHASE_SHIP_BODY` | Prefer soft ladder; Forbid-first map/pack on literals |
| Templates `scubiee.md` / `scubiee.mdc` | Matching one-line GATE 1 bullet |
| Repo reinstall | `write_project_gate_rules` + `write_cursor_rule` → AGENTS.md, Cursor/Kiro rules |
| Tests | `test_managed_gate_rule_is_policy_not_product_howto` asserts Forbid-first + LOCATE PRIORITY |
| Kiro A/B prompt | `SCUBIEE_PROMPT_EXTRA` aligned with Prefer/Forbid |

## Policy (summary)

- Soft/structural → **Prefer** map→pack (lean)→expand if thin  
- Literals / names / known paths → **Prefer** host Grep/Glob/Read (**Forbid-first** map/pack)  
- Forbid empty/`_`/test seeds  
- Native OK if Scubiee down — **no deadlock** / no BAN-native-forever  

## Live C09 re-check (post-rewrite + MCP reload)

| Run | baseline scubiee | calibrated scubiee | over_use | file_rec |
|-----|-----------------:|-------------------:|---------:|---------:|
| pre-rewrite | 4 | 3 | 1.0 | 1.0 |
| post-rewrite (no reload) | 1 | 2 | 1.0 | 1.0 |
| **post-reload `20260907T081755Z`** | **0** | **0** | **0.0** | **1.0** |

Both arms used native only (Forbid-first held). Needle over_use bar **≤10% met** on this check.

## Verification

- Unit: GATE policy tests **passed**  
- Repo rules reinstalled; MCP reloaded  
- Live C09 Prefer/Forbid compliance **green** after reload  
