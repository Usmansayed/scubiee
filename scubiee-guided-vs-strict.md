# Map-only rule: GUIDED vs STRICT (2-arm, no baseline)

Head-to-head between the two map-only rule styles only — no "without" arm this round. Both arms
expose **only `map`/`status`/`gate`** and differ **only** in the CLAUDE.md rule. Same task
(`cache_aware_savings`), same model (`claude-sonnet-5`), byte-identical tree, back to back.

## Result (this run)

| Metric | G: guided | S: strict |
|---|---:|---:|
| **Total tokens** | 1,000,482 | 1,119,510 |
| strict vs guided | — | **+11.9% more** |
| Cache-read | 930,379 | 1,058,465 |
| Tool calls | 20 | 23 |
| map calls | 1 | 2 |
| grep/glob | 5 | 4 |
| map→grep (ignored its own map) | 1 | 0 |
| **Turns** | 21 | 24 |
| Real `.py` edits | 1 | 1 |
| **Task success (oracle)** | **✗ 0.33 (genuine miss)** | **✓ 1.0** |

## Reading it

- **On cost, guided beat strict again:** 1.00M vs 1.12M tokens, 21 vs 24 turns, 20 vs 23 tool
  calls. This is consistent with the 4-arm run (guided leanest, strict heaviest). The mechanism
  holds: the guided rule lets the agent map once and move on (fewer turns); the strict rule pushes
  more map calls and more turns.
- **On correctness, strict won this run:** guided produced a genuine task miss (oracle 1 passed /
  2 failed — it added a cache field but the effective/savings number didn't respond to cache),
  while strict got it right. This is the *opposite* correctness outcome from the 4-arm run (where
  guided passed and flexible failed).

## Two clean runs side by side (cost, then correctness)

| Comparison | guided tokens / turns / pass | strict tokens / turns / pass |
|---|---|---|
| 4-arm run | 831K / 20 / ✓ | 1,282K / 34 / ✓ |
| this 2-arm run | 1,000K / 21 / ✗ | 1,120K / 24 / ✓ |

- **Cost:** guided < strict in **both** runs (831K<1282K; 1000K<1120K, and fewer turns each time).
  That direction is now reproduced twice — reasonably trustworthy: **guided is the cheaper rule.**
- **Correctness:** split — guided passed once and failed once; strict passed both times. The
  failures are real (behavioral), not scoring artifacts. On this evidence **strict looks more
  reliable at actually completing the task**, but with **n=1 per run** and the task's known high
  variance, one pass/fail flip is not conclusive.

## Verdict

- **Guided is consistently the cheaper rule** (fewer turns/tokens in both clean runs). If token cost
  is the only axis, guided wins.
- **Strict has been more reliable at correctness** (2/2 vs guided 1/2) in these runs — plausibly
  because forcing more map+read discipline gives the agent more grounding before it edits, at the
  price of extra turns/tokens.
- So it's a genuine **cost vs. reliability trade-off this small sample surfaced**, not a clean
  win for either. The intuitive "guided is strictly better" is **not** supported: guided is cheaper
  but missed the task once.

**To resolve it** (the only honest way): run **guided and strict ≥5× each** on this task, and report
**mean tokens/turns AND pass-rate** with the spread. Two runs can show the cost direction (guided
cheaper) but cannot settle the correctness question — a 1/2 vs 2/2 split needs more samples.

## Reproduce

```
scripts/claude_sdk_harness/run_guided_vs_strict.py
  GUIDED_MAP_RULE  (imported from run_small_ab_guided.py)
  STRICT_MAP_RULE  (imported from run_big_ab_strict.py)
python scripts/claude_sdk_harness/run_guided_vs_strict.py --preflight-only
python scripts/claude_sdk_harness/run_guided_vs_strict.py
```
Raw traces + REPORT.md in `.ab_workspaces/claude_sdk_harness/<run_id>_gVs/`.
Both arms map-only (map/status/gate); only the CLAUDE.md rule differs; Scubiee internals, task,
model, and snapshot unchanged.
```
