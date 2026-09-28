# Locate calibration — Phase D decision gate

**Date:** 2026-09-07  
**Inputs:** Phase B offline · Phase C scripted · Phase C live Kiro (n=3×2)  
**Decision:** **GREEN (Phase E + live C09 post-MCP-reload)** — Prefer/Forbid GATE+MCP shipped; needle over_use **0** on C09 re-check

## Checklist (post-rewrite + reload)

| Gate | Scripted C | Live C (pre) | Live C09 post-reload |
|------|------------|--------------|----------------------|
| mean `total_proxy` ↓ vs baseline | yes | mixed | — |
| `must_*` within −5pp | yes | yes | file_rec 1.0 |
| `over_use` ≤10% on needles | yes | failed | **0.0** |
| `under_use` ≤20% on soft/exact | yes | yes | — |
| No BAN-native-forever | yes | yes | yes |
| Grep/Glob first-class | draft | ignored | **held** (0 Scubiee) |
| Density | yes | C01 spike | C09 ~800 tok |

## Decision

| Option | Choice |
|--------|--------|
| Ship Prefer/Forbid GATE+MCP text | **Yes (Phase E done in-repo)** |
| Strength | Prefer + Forbid-first needles (not Require pack always) |
| Live bar | C09 post-reload: over_use **0**, scubiee **0** both arms |

## Required before calling Phase D fully green

1. ~~Rewrite GATE / AGENTS.md~~ **done**  
2. ~~Live re-check C09 after MCP reload~~ **done** (`20260907T081755Z`)  
3. ~~Pass needle over_use ≤10%~~ **done (0.0)**  

## Artifacts

- Phase B: `docs/superpowers/plans/2026-09-06-locate-calibration-phase-b.md`
- Phase C scripted: `docs/superpowers/plans/2026-09-07-locate-calibration-phase-c.md`
- Phase C live: `docs/superpowers/plans/2026-09-07-locate-calibration-phase-c-live.md`
- Phase E: `docs/superpowers/plans/2026-09-07-locate-calibration-phase-e.md`
- Framework: `docs/superpowers/specs/2026-09-06-locate-force-routing-research-framework.md`
