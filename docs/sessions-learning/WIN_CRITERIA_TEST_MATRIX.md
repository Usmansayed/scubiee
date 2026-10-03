# map_v3 vs mini_v3 - test matrix and win criteria

One n=1 win on 3 retrieval queries is NOT a win. This defines the multi-angle test needed before
declaring map_v3 better than the old map, the win criteria set UPFRONT (so we don't move goalposts),
and a token-frugal execution order.

## What we have vs what's missing (map_v3 coverage)

map_v3 so far: 3 retrieval queries (discovery/focused categories), n=2, retrieval only.
NEVER tested on:
- the other 5 retrieval queries, incl the **cross_module** category (the multi-file case the
  focus-multi / A2 / graph features were built for - the most important gap)
- any **dev task** (actual edits: cache_aware_savings, dirty_files_cap, health_reason_flag) - this is
  the workload where mini_v3 is the proven baseline and where map_v3 has ZERO data
- any **comprehension task** (research -> write MD)
- any **repeats** (variance unmeasured; mini_v3 is known high-variance)

## The test matrix (vary the conditions)

| angle | what it stresses | arms | cells |
|---|---|---|---|
| R-full | all 8 retrieval queries, all 3 categories | mini_v3, map_v3 | 16 |
| R-crossmod | the 2 cross_module queries at n=2 (multi-file - focus-multi/A2) | mini_v3, map_v3 | 8 |
| DEV | the 3 edit tasks (the baseline's home turf) | mini_v3, map_v3 | 6 (n=1) |
| COMP | 1 comprehension task (research->MD) | mini_v3, map_v3 | 2 |

Run order by ROI (stop early if a clear loss shows): R-full first (cheapest cells, biggest coverage
gain), then DEV (the real workload), then COMP. R-crossmod is folded into R-full (those 2 queries are
in the 8); add n=2 repeats only if the n=1 cross_module cells look close.

## Win criteria (decided BEFORE the runs)

Correctness is the gate; cost is the prize. map_v3 is declared BETTER than mini_v3 only if ALL hold:
1. **Correctness not worse:** map_v3 recall (retrieval) and oracle-pass (dev) >= mini_v3, within noise
   (no cell where map_v3 fails and mini_v3 passes on the same task without a map_v3 win elsewhere).
2. **Cheaper on aggregate:** map_v3 mean tokens AND mean API calls < mini_v3 across the full matrix,
   not just the 3 cherry-picked queries.
3. **Consistent:** map_v3 token/call spread (max-min) <= mini_v3's - the consistency claim from P13
   must hold on the wider set, not collapse on new query types.
4. **No regression on the baseline's turf:** on the DEV tasks (mini_v3's home), map_v3 must be at
   least competitive (within ~15% tokens) AND fully correct - it does not have to win dev, but it
   must not lose badly.

If 1-3 hold but 4 fails (map_v3 loses dev), the honest verdict is "map_v3 wins retrieval, mini_v3
wins edits" - a split, NOT an outright win. We report whichever is true.

Precision is tracked but NOT a gate: prior analysis (P10/P11) showed map_v3's lower precision is
mostly the strict single-commit oracle penalizing correct neighbor files, so it is reported as
context, not pass/fail.

## Token budget / frugality
- R-full = 16 cells but each is a cheap locate-only cell (~150-220k, low turn cap). This is the bulk.
- DEV = 6 cells, pricier (edits). COMP = 2 cells.
- Preflight gates already passed this session (battery, spawn, dev+retrieval preflight, live probe) -
  do NOT re-pay them; go straight to the runs.
- Report after EACH angle so a clear loss stops the matrix early (don't burn all cells to confirm a
  loss already visible).

## Where results land
`run_retrieval_bench.py` and `run_dev_mini.py` / `run_comprehension.py` write cells under
`.ab_workspaces/claude_sdk_harness/`; `extract_sessions.py` folds them in; verdict recorded in
LEARNINGS.md against these 4 criteria.
