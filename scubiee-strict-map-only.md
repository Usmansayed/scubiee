# Strengthening map-only: session analysis + strict-rule experiment

Follow-up to the big-task tie (−3.8%). Hypothesis: the flexible map-only rule let the agent map
once and then grep-walk anyway, so a **stricter map-usage rule** should recover the savings. This
documents the session analysis, the strict config, the re-run, and the (honest) verdict.

## 1. Session analysis — when map actually helped

Recorded tool traces (`analyze_sessions.py` over the prior A/B runs):

**Winning pattern** — small task, flexible map-only, **−45% tokens** (3-arm run):
```
gate → map → map(refined) → Read the returned loc span → edit → done
18 tool calls total · 2 map · 2 grep · 1 read
```
The agent trusted the map, went straight to the located file, and barely grepped.

**Losing pattern** — big task, flexible map-only, **−3.8% (tie)**:
```
gate → map → Glob, Glob, Grep, Grep, Grep … (30+) → Read (26) …
111 tool calls · 2 map · 31 grep
```
The agent mapped once, ignored the result, and grep-walked the whole area — same as the without arm.

**Diagnosis:** the flexible rule ("use map for discovery, then Read the spans") never (a) forbade
grepping after a map, (b) told the agent to re-map each new sub-question, or (c) told it to read
map's `loc` spans instead of re-searching. On a multi-sub-question task the agent reverted to grep
habit. The −45% win wasn't caused by *forcing* map; it happened because a small discovery-dominated
task naturally resolves in a few `map → read → stop` turns.

## 2. The strict map-only config (only allowed changes)

Per the constraints, exactly two things changed vs. baseline — **nothing inside Scubiee or the
simulation**:

1. **MCP adapter exposes only `map` / `status` / `gate`.** Enforced at the adapter boundary via the
   SDK allow-list (`allowed_tools` + `strict_mcp_config`); the Scubiee server still runs its normal
   surface unmodified. (Adding a bespoke "map-only surface" inside `mcp_locate.py` would have been a
   Scubiee-internal change, which was off-limits, so the restriction is applied at the adapter.)
2. **A strict map-usage rule** in the workspace `CLAUDE.md` (encoding the winning pattern):
   map FIRST for every new where/how sub-question; READ the returned `loc` spans (not whole files,
   not grep); grep only as a justified last resort after a map failed to cover it; one map per
   question then act; re-map when moving to a new area.

Task, model (`claude-sonnet-5`), tree snapshot (byte-identical), budgets, and oracle: unchanged.
Task used: the sub-2M `cache_aware_savings` task (the one where flexible map-only first won −45%).

## 3. Result (strict map-only vs without, small task)

| Metric | A: Without | B: Strict map-only |
|---|---:|---:|
| **Total tokens** | 1,037,706 | 1,125,787 |
| **% vs without** | — | **−8.5% (worse)** |
| Output tokens | 22,208 | 18,973 |
| Cache-read | 950,513 | 1,066,253 |
| Tool calls | 33 | 24 |
| map calls | 0 | 2 |
| grep/glob | 12 | **7** |
| native Read/Grep/Glob | 16 | **9** |
| Turns | 21 | 25 |
| Real `.py` edits | 1 | 1 |
| **Oracle** | **1.0 (pass)** | **0.33 (fail: 1 passed, 2 failed)** |

## 4. What the strict rule did and didn't do

- **It worked as designed on behavior:** grep/glob fell 12 → 7 and native discovery 16 → 9. The
  agent stopped grep-walking and did do `map → read` cycles. So the rule successfully changed the
  *pattern* we identified.
- **But total tokens went UP (+8.5%) and turns went UP (21 → 25).** The strict protocol traded
  greps for more map+read+reason cycles and more back-and-forth turns. Because total token cost is
  dominated by cache-read (which scales with **turns**, not with grep count), swapping a few greps
  for extra turns was a net loss. Suppressing grep did not reduce turns.
- **Worse, correctness dropped this run:** the strict arm's oracle scored 0.33 — a **genuine task
  miss** (it added a cache field but the effective/savings number didn't actually respond to
  cache), while the without arm passed at 1.0. This is a real failure, not the skip-artifact from
  the big run.

## 5. Verdict

**On this run, the strict map-only rule did not beat "without" — it was ~8.5% more expensive and
produced a worse result.** Making the map policy *stricter* did not recover the savings; it added
turns.

The deeper lesson from putting all the runs together:

| Task | map-only variant | tokens vs without |
|---|---|---|
| Small (3-arm) | flexible | **−45%** (win) |
| Big | flexible | −3.8% (tie) |
| Big | (not re-run small-first) | — |
| Small | **strict** | **+8.5%** (worse) |

- The **−45% win was not reproducible by forcing more map discipline.** It came from a run where
  the agent *naturally* did `map → read → stop` in very few turns. The strict rules produced more
  map calls but also more turns, and turns are what cost tokens.
- **`map`'s benefit is fragile and turn-driven, not grep-driven.** Fewer greps ≠ fewer tokens if
  the agent takes more conversational turns to get there. The token bill tracks turns (cache-read),
  so the only reliable way `map` saves tokens is by **cutting the number of turns to reach the
  edit** — which happens on small, discovery-dominated tasks and does not happen when a rule makes
  the agent do a mandatory map+read loop per sub-question.
- Over-constraining also risks **correctness**: forcing the agent through a rigid discovery
  protocol on a task that needs iterative understanding cost it the behavioral outcome once.

**Recommendation:** do not ship a rigid "map before everything, never grep" rule — it can raise
both cost and error rate. The realistic sweet spot is the **lightweight** guidance ("start with one
`map`; read its loc spans before grepping") applied to **small, discovery-heavy tasks**, and
letting the agent fall back to native tools freely. And crucially: **n = 1 per cell.** The −45%,
the −3.8%, and this +8.5% are single Sonnet runs with high variance; the only trustworthy
conclusion is *directional* — map helps most on small discovery-dominated tasks, strict rules don't
reliably improve it, and a proper number needs repeats (≥5 seeds/task) which is token-expensive.

## Reproduce

```
scripts/claude_sdk_harness/
  analyze_sessions.py        # trace analysis (map vs grep timing)
  run_big_ab_strict.py       # strict-rule + map/status/gate-only (STRICT_MAP_RULE lives here)
  run_small_ab_strict.py     # same strict config on the sub-2M task (this report's run)
python scripts/claude_sdk_harness/run_small_ab_strict.py --preflight-only
python scripts/claude_sdk_harness/run_small_ab_strict.py
```
Raw traces + REPORT.md in `.ab_workspaces/claude_sdk_harness/<run_id>_smallStrict/`.
Only the adapter exposure (map/status/gate) and the CLAUDE.md rule differ between arms; Scubiee
internals, the task, the model, and the snapshot are unchanged.
```
