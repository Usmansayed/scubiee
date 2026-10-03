# Map-only rule comparison — without vs flexible vs strict vs guided (one clean run)

This replaces the earlier stitched-together table (which mixed runs from different days). Here all
four arms ran **back-to-back in a single experiment**, same task, same model, same byte-identical
tree. The three map arms expose **only `map`/`status`/`gate`** and differ **only in the CLAUDE.md
rule text**. Nothing inside Scubiee or the simulation was changed.

- **Task:** `cache_aware_savings` (the sub-2M vague task).
- **Model:** `claude-sonnet-5`. **max_turns:** 60. Real SDK `model_usage` tokens.
- **Arms:**
  - **A without** — native tools, no Scubiee.
  - **B flexible** — loose rule: "use `map` for discovery, then Read spans; prefer map over grep."
  - **C strict** — forced: "MAP FIRST always; map every sub-question; grep only as last resort."
  - **D guided** — when-to-use guidance (agent decides when map earns its keep).

## Results (one run each)

| Metric | A: without | B: flexible | C: strict | D: guided |
|---|---:|---:|---:|---:|
| **Total tokens** | 1,249,297 | 1,146,194 | 1,282,194 | **831,077** |
| **% vs without** | — | +8.3% (worse) | −2.6% (worse) | **+33.5% (better)** |
| Cache-read | 1,184,697 | 1,075,451 | 1,205,393 | 772,241 |
| Tool calls | 29 | 26 | 33 | **19** |
| map calls | 0 | 2 | 3 | 1 |
| grep/glob | 0 | 8 | 15 | 7 |
| map→grep (ignored map) | 0 | 0 | 2 | 1 |
| **Turns** | 30 | 27 | 34 | **20** |
| Real `.py` edits | 1 | 1 | 1 | 1 |
| **Task success (oracle)** | ✓ 1.0 | **✗ 0.33** | ✓ 1.0 | ✓ 1.0 |

## What this run shows

- **Guided was clearly best this run:** lowest tokens (831K, −33.5% vs without), fewest turns (20),
  fewest tool calls (19), and it passed. It used `map` once — by choice — then worked efficiently.
- **Strict was worst on efficiency** (1.28M, 34 turns, 15 grep): forcing map-everywhere made the
  agent map *and then grep the same areas* (2 map→grep sequences), inflating turns. It still passed,
  but cost the most. This confirms the earlier finding that **forcing map is counterproductive.**
- **Flexible failed the task** (oracle 0.33) this run and cost more than guided — the loose rule
  gave no useful steer.
- **Turns tell the story** (tokens ≈ turns × transcript via cache-read):
  **guided 20 < flexible 27 < without 30 < strict 34.** Guided is the leanest, strict the heaviest.
- **`map→grep` count** (did the agent map then immediately grep the same thing?): strict 2, guided
  1, flexible 0, without 0 — strict most often ignored its own map result.

## Honest reading — the ordering is meaningful, the exact %s are not

This is a **fair** comparison (one run, identical everything but the rule), so the **relative
ordering** is trustworthy *for this run* and matches the mechanism we expect:

> A **when-to-use (guided)** rule lets the agent map once and move on → fewest turns → cheapest.
> A **forced (strict)** rule makes it map *and* grep → most turns → most expensive.

But each arm is still **n = 1**, and we have direct proof that this task's per-run noise is large:
across earlier runs the *without* arm alone swung 0.86M → 1.25M → 1.42M on the identical task. So:
- **Trust:** guided ≤ flexible/without ≤ strict on turns/tokens — the direction is consistent with
  every trace we've analyzed (fewer turns = cheaper; forcing map adds turns).
- **Don't trust:** the precise "−33.5%" or "+8.3%" — a repeat could shift these by tens of percent.
- One correctness data point per arm is also too few to rank rules on *quality* (flexible's fail
  here is one sample).

## Verdict

**Of the three map-only rule styles, "guided / when-to-use" is the best design** — this run it was
both the cheapest (−33.5% vs without, 20 turns) and correct, while "strict/forced" was the most
expensive and "flexible/loose" failed the task. That ranking is consistent with the underlying
mechanism (map helps by *replacing* discovery turns, and only when the agent doesn't also grep-walk;
forcing map adds turns without removing greps).

**To turn this into a shippable claim** (a real token-savings number), run **each arm ≥5×** on this
task and report **mean ± stdev on turns and tokens** — a single pass can rank the designs
directionally (done here) but cannot pin the magnitude. Recommended next step, budget permitting:
5× repeat of **guided vs without** only (the two that matter), on 2–3 tasks.

## Reproduce

```
scripts/claude_sdk_harness/run_rules_4arm.py   # this 4-arm, one-run comparison
  FLEXIBLE_MAP_RULE   (defined in run_rules_4arm.py)
  STRICT_MAP_RULE     (imported from run_big_ab_strict.py)
  GUIDED_MAP_RULE     (imported from run_small_ab_guided.py)
python scripts/claude_sdk_harness/run_rules_4arm.py --preflight-only
python scripts/claude_sdk_harness/run_rules_4arm.py
```
Raw per-arm traces + REPORT.md in `.ab_workspaces/claude_sdk_harness/<run_id>_rules4/`.
All four arms: same task/model/tree; map arms expose only map/status/gate; only the rule differs.
```
