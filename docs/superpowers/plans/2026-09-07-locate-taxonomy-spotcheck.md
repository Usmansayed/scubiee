# Locate calibration — taxonomy spot-check (10 cases)

**Date:** 2026-09-07 · **Corpus:** `locate-calibration-corpus-v1.json`  
**Purpose:** sanity-check heuristic labels before treating class metrics as final.

| id | labeled | verdict | notes |
|----|---------|---------|-------|
| `blind20_t03` | soft_understand | **keep** | Ladder/how-it-works; not a single edit site |
| `blind20_t04` | soft_understand | **keep** | Understand composite rank flow |
| `blind20_t05` | soft_understand | **keep** | Understand embed keep/drop |
| `blind20_t06` | soft_understand | **keep** | Understand semantic tracer fuse |
| `blind20_t08` | soft_understand | **borderline → exact_edit?** | Error-string → fix publication path; gold has files, no symbols — could be `literal_needle`+edit |
| `blind20_t01` | exact_edit | **keep** | Concrete session isolation symbols to change/verify |
| `blind20_t02` | exact_edit | **keep** | Connect/install write path |
| `blind20_t07` | exact_edit | **keep** | Pack CLI entry points |
| `kiro_complex_C09_auth_jwt_trap` | literal_needle | **keep** | Symbol/literal chase across fixture files |
| `anchor_name_mcp_locate` | name_path | **keep** | Filename-only locate |

## Summary

- 9/10 labels look right for routing calibration.
- 1 borderline (`blind20_t08`): soft vs needle/exact — leave as soft for now; do not reweight class means until relabeled.
- Soft overweight in corpus remains real; spot-check did **not** find mass mislabels of soft↔exact.

## Action

No corpus rewrite this beat. Proceed with seed_ok Phase B re-run using fixed map symbols.
