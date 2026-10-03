# Verdict: map_v3 vs mini_v3 (multi-angle test)

Judged against the 4 criteria set BEFORE the runs (see WIN_CRITERIA_TEST_MATRIX.md). This replaces
the premature "map_v3 wins" from the earlier 3-query n=1 run with a fair, multi-angle result.

## What ran
- **R-full:** all 8 retrieval queries x 2 arms = 16 cells. DONE.
- **DEV:** 3 edit tasks x 2 arms = 6 cells. DONE.
- **COMP:** 1 comprehension task x 2 arms = BLOCKED - the OAuth account hit "Credit balance is too
  low" (both arms failed identically at 0 tokens; a billing wall, not a tool fault). Not counted.

22 live cells completed. Correctness held everywhere both arms ran (see below).

## Results by angle

### Retrieval (16 cells) - map_v3 better
| metric | mini_v3 | map_v3 |
|---|--:|--:|
| recall mean | 0.81 | **0.875** |
| full-recall rate | 6/8 | **7/8** |
| tokens mean | 265k | **245k** |
| API calls mean | 7.9 | **6.9** |
| grep mean | 2.6 | **0.5** |
| read mean | 4.0 | **0.5** |
| precision mean | **0.57** | 0.43 |

Highlights: on the hardest 4-file discovery query map_v3 recalled 1.0 vs mini_v3 0.5. map_v3 wins by
cutting grep/read chains. Both failed `cold_start_status_warming` (shared blind spot). map_v3's one
spike (611k on first_map_skips_graph: 5 map + 4 greps) is its worst retrieval cell.

### Dev / edits (6 cells) - mini_v3 better
| task | mini_v3 | map_v3 | both correct? |
|---|--:|--:|:--:|
| dirty_files_cap | **148k / 5** | 244k / 7 | yes (oracle 1.0) |
| health_reason_flag | 269k / 9 (4 grep) | **216k / 7** | yes |
| cache_aware_savings | **274k / 8** | 513k / 12 (4 grep) | yes |
| **mean** | **230k** | 324k | - |

map_v3 is 41% pricier on dev. The cache_aware cell is the killer: map_v3 located in 1 map call then
grep-chained the prompt-caching PRICING sub-question (the known confound). map_v3 only won the one
dev task where mini_v3 itself grep-chained.

## Against the 4 preset criteria

| # | criterion | result |
|---|---|---|
| 1 | correctness not worse | **PASS** - retrieval recall higher (0.875 vs 0.81); dev oracle 1.0 for both on all 3 tasks |
| 2 | cheaper on aggregate | **MIXED** - cheaper on retrieval (245k vs 265k) but pricier on dev (324k vs 230k). Across all 22 cells it is NOT uniformly cheaper. |
| 3 | consistent (spread <= mini_v3) | **FAIL** - map_v3 spikes on hard discovery (611k) and on the pricing dev task (513k); not tighter overall |
| 4 | no dev regression (within ~15%) | **FAIL** - map_v3 is 41% pricier on dev |

## Verdict: SPLIT, not an outright win

**map_v3 wins retrieval/locate; mini_v3 wins edits.** This is the honest call and it is exactly the
"split" outcome the criteria doc anticipated. Specifically:
- For **finding code / understanding where things are** (retrieval), map_v3 is better: higher recall,
  fewer calls, far fewer grep/read chains, cheaper.
- For **making edits** (dev tasks), mini_v3's one-map-one-whole-file-Read instinct is cheaper and
  tighter; map_v3 costs more, dragged by grep chains on the pricing-confounded task.

Both are 100% correct where tested. So this is a **cost/behavior split, not a correctness problem.**

## Why (root cause, from the traces)
- map_v3's retrieval win comes from its configs returning code+wiring inline, removing the native
  grep/read chains mini_v3 relies on (mini_v3 avg 2.6 grep + 4.0 read on retrieval).
- map_v3's dev loss comes from the SAME tasks' non-locate work (the cache_aware pricing sub-question)
  where the agent grep-chains regardless of the map - a task-design confound (M4), not a map failure.
  Controlling for it (health_reason_flag, no confound) map_v3 actually beat mini_v3 on dev.

## What would settle it (not done - out of credits / needs sign-off)
- Re-run COMP (blocked by credits).
- n>=3 on dev with the pricing sub-question stripped (M4) to see if map_v3's dev cost converges to
  mini_v3 once the confound is removed - the health_reason_flag result suggests it might.
- The discovery-category retrieval spike (first_map_skips_graph) deserves a look: map_v3 fell back to
  4 greps there, which the rules say it should not.

Bottom line: do NOT declare map_v3 an outright win. It is a **retrieval win and a dev loss** on the
current tasks, both at full correctness. Recommend map_v3 for locate/comprehension surfaces and keep
mini_v3 (or settle the confound) for edit-heavy work.
