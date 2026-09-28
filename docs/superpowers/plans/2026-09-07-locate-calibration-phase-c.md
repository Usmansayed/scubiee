# Locate calibration — Phase C (policy trajectories)

**Status:** draft complete · scripted Prefer/Forbid · **not GATE ship**  
**Tax:** 2500/round · **Cases:** 14 · **Elapsed:** ~295s  

## Policies

| Policy | Behavior |
|--------|----------|
| `baseline` | Always map→pack (current ladder habit) |
| `calibrated` | Prefer/Forbid §6.3 — Grep needles; map→read soft; map→pack exact+seed_ok |
| `native_heavy` | Blind Grep first; escalate to map→pack on miss |

## Scoreboard

| Policy | n | total_proxy | rounds | must_file | must_sym | scubiee | native | ok |
|--------|--:|----------:|------:|----------:|---------:|--------:|-------:|---:|
| `baseline` | 14 | 19011 | 5.4 | 0.893 | 0.445 | 2.0 | 3.4 | 0.93 |
| `calibrated` | 14 | 17377 | 5.4 | 0.893 | 0.464 | 1.0 | 4.4 | 1.0 |
| `native_heavy` | 14 | 26717 | 8.7 | 0.893 | 0.577 | 1.3 | 4.8 | 1.0 |

## Phase D preview (this sample)

| Gate | Result |
|------|--------|
| total_proxy ↓ vs baseline | **yes** (calibrated Δ ≈ −1634) |
| must_file within −5pp | **yes** (tied 0.893) |
| over_use ≤10% (calibrated on needles) | **yes** (0.0; baseline was 0.75) |
| under_use calibrated ≤20% | **yes** (0.0) |

## Draft findings

- Calibrated beats baseline on `total_proxy` with same file recall and half the Scubiee calls.
- Native-heavy is *worse* once Grep is blind to gold symbols — soft/exact often miss then pay grep+map thrash (`traj_break` ≈ 0.64).
- Forbid-first map on needles is the clear win (baseline over-use 75% → calibrated 0%).
- Prefer map→read (not always pack) on soft matches Phase B cost evidence.

## Caveats

- Scripted policies — not live LLM agents (compliance / traj_break under real prompts still open).
- Soft/exact native Grep uses enrich tokens only (no gold-symbol oracle).
- Enrich queries are code-vocab rich, so blind Grep can still hit files.

## Next

- Optional live Kiro/Cursor A/B on 3–5 tasks for real compliance.
- Phase D: treat this scripted preview as **yellow-green** — still need live traj before Prefer text ships.
- Do **not** ship GATE/MCP Prefer text until Phase D explicitly greens live compliance.

Harness: `scripts/locate_calibration_phase_c.py`  
Raw: `docs/superpowers/plans/locate-calibration-phase-c-results.json`
