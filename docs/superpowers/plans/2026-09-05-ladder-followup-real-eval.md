# Real ladder + follow-up tools (2026-09-05)

## Real test (this repo, `CTX_TRACE_ENGINE=composite_v1`)

**Pack-only** (`ten_problem_map_pack_eval`): mean file_rec **0.592**, symbol_rec **0.065**.

**Ladder** map → pack(lean) → expand(callees|broad, with_bodies) (`ladder_followup_real_eval`):

| Metric | Lean pack only | + expand follow-up |
|--------|----------------|--------------------|
| mean file_rec | 0.592 | **0.642** (+0.05) |
| mean symbol_rec | 0.065 | **0.098** (+0.033) |

Notable recoveries: P07 session (+0.5 file), P03 graphify (+0.33 symbol). Failures still dominated by **bad soft-map seeds** (tests/, gold_retry), not tracer F1.

## Follow-up flexibility shipped

| Tool | New knobs | When |
|------|-----------|------|
| `expand_context` | `direction=callees\|callers\|effects\|config\|broad`, `with_bodies`, `budget_chars`, `max_bodies` | Missing hop / upward refs / side effects |
| `collect_hot_context` | `ids=file::sym,...` | Fill bodies for specific delta cards |
| `pack_context` | `policy=strict\|broad` | Broad = one-shot polytrace escape |

Responses include structured `next_actions[]` so agents can pick a follow-up without re-exploring.

## Recipe

1. `map` → `suggested_seed`
2. `pack_context(mode=lean, policy=strict)`
3. If thin: `expand_context(direction=…, with_bodies=true)` or `collect_hot_context(ids=…)`
4. Only if still cut wrong: `pack_context(policy=broad)` once

Artifacts: `2026-09-05-ladder-followup-real-eval.json`, `2026-09-05-ten-problem-map-pack-eval.json`.
