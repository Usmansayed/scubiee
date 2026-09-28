# Locate calibration — Phase C live (Kiro policy A/B)

**Run:** `20260907T084356Z` · **Tasks:** 1 · **Elapsed:** 74.77s
**Both arms have Scubiee** — only Prefer/Forbid instruction text differs.

## Scoreboard

| Arm | n | file_rec | sym_rec | tokens | scubiee | native | over_use | under_use |
|-----|--:|---------:|--------:|-------:|--------:|-------:|---------:|----------:|
| `baseline` | 1 | 1.0 | 1.0 | 877.0 | 0.0 | 2.0 | 0.0 | 0.0 |
| `calibrated` | 1 | 1.0 | 1.0 | 899.0 | 0.0 | 2.0 | 0.0 | 0.0 |

**Needle over_use (calibrated):** 0.0
**Soft/exact under_use (calibrated):** None

## Findings

- Live arms both have Scubiee; policy text differs (baseline mandatory ladder vs calibrated Prefer/Forbid).
- Scoreboard baseline file_rec=1.0 calibrated=1.0.
- Needle over_use calibrated=0.0; soft/exact under_use calibrated=None.
- mean scubiee_calls baseline=0.0 calibrated=0.0.

Logs: `out/kiro_phase_c_live/20260907T084356Z/`
Raw: `docs/superpowers/plans/locate-calibration-phase-c-live-results.json`
