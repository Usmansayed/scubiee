# Guided (not forced) map-only rule — result + a variance warning

Per request, the map-only rule was rewritten to **explain when `map` is useful** and let the agent
decide — strict about following the guidance, not about a rigid workflow. Only two things differ
from baseline: the MCP adapter exposes only `map`/`status`/`gate`, and this rule replaces the
product GATE. Task, model, tree snapshot, and oracle are unchanged (sub-2M `cache_aware_savings`).

## The rule (guidance, not forcing)

Mirrors the product GATE's voice, adapted for a map-only surface. Summary of what it tells the agent:
- Prefer `map` for **semantic / "where does this happen"** search.
- Use `map` when you **don't know exactly what you're looking for** — to discover where something
  lives and how pieces relate.
- If **unsure of a keyword/function/concept/location**, consider `map`.
- After a `map`, **read the returned `loc` spans**; don't re-grep what map already found.
- When you **already know the exact file/symbol/path**, use native tools — don't call `map`.
- Reach for `map` when **broader context / relationships** matter (multi-file answers).
- Plus 5 concrete when-to / when-not-to examples.

It does **not** force `map` on any step. Full text: `run_small_ab_guided.py::GUIDED_MAP_RULE`.

## This run's result

| Metric | A: Without | B: Guided map-only |
|---|---:|---:|
| **Total tokens** | 862,855 | 1,246,468 |
| **% vs without** | — | **−44.5% (worse)** |
| map calls | 0 | 1 (agent's choice) |
| grep/glob | 7 | 12 |
| Turns | 21 | 28 |
| Real `.py` edits | 1 | 1 |
| **Task success (oracle)** | ✓ 1.0 | ✓ 1.0 |

Both arms completed the task correctly. The guided rule behaved as intended (the agent chose to
map once, wasn't forced), but this run the map arm still took more turns (28 vs 21) and more grep
(12 vs 7), so it cost 44% more.

## The finding that matters more than this number: variance dominates

Put every single-run result on the **same task/model/tree** side by side:

| Run | Without (tokens) | map-only (tokens) | map vs without |
|---|---:|---:|---:|
| 3-arm (flexible rule) | 1,422,730 | 774,797 | **−45% (better)** |
| small strict rule | 1,037,706 | 1,125,787 | +8.5% (worse) |
| small guided rule | 862,855 | 1,246,468 | **+44.5% (worse)** |

The **"without" arm alone swung from 1.42M → 0.86M**, and the map arm from 0.77M → 1.25M, across
runs of the *identical* task. The run-to-run spread (±0.5M+ tokens) is **larger than any rule
effect** we're trying to measure. Sonnet's agentic path is stochastic: how many turns it takes to
understand and edit varies a lot per run, and since total tokens ≈ turns × transcript size
(cache-read), that variance directly moves the token total.

**Honest conclusion:** from single runs, I **cannot** tell whether the guided rule (or any rule)
helps or hurts. The earlier "−45% win" and this "−44.5% loss" are the *same experiment* producing
opposite verdicts by chance. Neither is a reliable measurement of the rule.

## What this does and doesn't tell us

- **Does tell us:** the guided rule is safe on correctness (both arms passed), and the agent used
  `map` sparingly and by choice when told *when* it's useful — i.e. the rule reads well and doesn't
  induce the strict rule's turn-inflation or its one correctness miss. Qualitatively it's the best
  of the three rule variants.
- **Doesn't tell us:** whether it saves tokens. A single A/B pair can't, at this noise level.

## To actually answer "does map-only save tokens", this is required

- **Repeat each arm N≥5 times** on the same task (same seed pool), report **mean ± stdev**, and use
  a paired test — one run per arm is meaningless here.
- **Fix the turn count as the real metric.** Tokens are ~linear in turns; measure whether `map`
  reduces *turns-to-first-correct-edit*, which is the mechanism, with less noise than raw tokens.
- **Use several tasks**, not one, and separate discovery-heavy from edit-heavy tasks (the earlier
  work showed `map`'s benefit tracks the discovery fraction).
- This is token-expensive (≈1M tokens/run × 5 × 2 arms × several tasks). It needs a budget decision
  before running.

**Recommendation:** keep the **guided (when-to-use) rule** — it's the right design and the only
one that neither inflated turns nor hurt correctness — but do **not** quote a token-savings
percentage from single runs. Treat "does it save tokens" as **unmeasured pending a repeated trial**.

## Reproduce

```
scripts/claude_sdk_harness/
  run_small_ab_guided.py   # this run: guided (when-to-use) map-only rule, sub-2M task
  run_small_ab_strict.py   # the earlier forced/strict variant (for contrast)
  analyze_sessions.py      # tool-trace analysis
python scripts/claude_sdk_harness/run_small_ab_guided.py --preflight-only
python scripts/claude_sdk_harness/run_small_ab_guided.py
```
Raw traces + REPORT.md in `.ab_workspaces/claude_sdk_harness/<run_id>_smallGuided/`.
Only the adapter exposure (map/status/gate) and the CLAUDE.md rule differ; Scubiee internals, task,
model, and snapshot are unchanged.
```
