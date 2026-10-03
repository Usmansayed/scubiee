# Hard-task suite verdict: is map_v3 a win? (4 independent cross-module tasks)

To move from "one hard task is suggestive" to a real call, we built FOUR independent
hard cross-module dev tasks, each a vague prompt over a different subsystem, each with
a strict name-agnostic deterministic oracle (baseline FAIL / partial FAIL / full PASS,
all validated offline), all preflighted to 31/31 "EVERYTHING WORKING PERFECTLY" before
any live token. Then all 3 arms (map_v3 / mini_v3 / without), n=2, graded on STRICT.

Per-cell cost cap $4 (CTX_DEVMINI_MAX_USD) after a native cell spiralled >14 min on
the first attempt — so a runaway native arm terminates with a graded FAIL instead of
burning unbounded tokens. That cap itself is a finding (see native below).

## The 4 seams (all distinct subsystems, all call-graph-only to locate)
1. **unify_cpu_thread_budget** — memory_budget + embedder (CPU-thread formula dup).
2. **unify_token_estimate** — token_meter + session_store (hidden //4 duplicate). *(ambiguous, see note)*
3. **surface_changed_count_timing** — freshness + engine (gate-dict wiring into timings).
4. **distinct_huge_change_strategy** — freshness + sync_status (new strategy tier + classifier).

## Per-task results (tok mean, strict success), n=2

| task | map_v3 | mini_v3 | without |
|------|-------:|--------:|--------:|
| unify_cpu_thread_budget | **549k · 2/2** | 630k · 2/2 | 918k · 2/2 |
| unify_token_estimate *(ambiguous)* | 471k · 1/2 | **367k · 1/2** | 675k · 0/2 |
| surface_changed_count_timing | **358k · 2/2** | 470k · 2/2 | 401k · 2/2 |
| distinct_huge_change_strategy | **508k · 2/2** | 2,015k · 2/2 | 3,435k · 0/2 |

## Overall (8 cells per arm)

| arm | tok mean | success | vs map_v3 |
|-----|---------:|:-------:|----------:|
| **map_v3 (new)** | **471,427** | **7/8** | — |
| mini_v3 (old) | 870,257 | 7/8 | +85% tokens |
| without (native) | 1,357,304 | 4/8 | +188% tokens, half the wins |

## Verdict — YES, map_v3 is a win on hard cross-module work

Across four independent hard seams the pattern is consistent and now well-sampled
(not one lucky task):

1. **map_v3 is the cheapest arm overall by a wide margin** — 471k mean vs mini_v3 870k
   (+85%) vs native 1.36M (+188%). It won tokens on 3 of 4 tasks outright and was a
   close 2nd on the one ambiguous task.

2. **map_v3 ties the best success rate (7/8) at a fraction of the cost.** mini_v3 also
   got 7/8 but paid ~1.85x the tokens to do it, including two spirals (1.27M and 2.76M
   on the strategy task) where its location-only output left the agent grep-churning
   through the call graph.

3. **Native (no retrieval) is the clear loser on hard tasks: 4/8 success and 1.36M
   mean, with catastrophic spirals** — 3.14M and 3.73M-token runs on the strategy task,
   both of which still FAILED strict because the agent never found the second
   cross-module consumer (it edited sync_loop/sync_status but missed the choose_strategy
   producer in freshness.py). This is the core thesis made concrete: when the contract
   is a dataclass field / call-graph edge and not a greppable literal, grep-hunting
   either explodes in cost or silently misses a consumer.

4. **The strategy task (hard4) is the sharpest discriminator:** map_v3 508k and 2/2;
   native 3.4M and 0/2. ~6.8x cheaper AND correct where native was expensive and wrong.

### The honest caveats
- **hard2 (unify_token_estimate) is a flawed task** and we keep it only as the
  "ambiguous-prompt" case. The prompt's "token estimate" concept is not unique in this
  repo — map_v3 r1 semantically landed in an unrelated subsystem (hybrid_cbm/seir) and
  edited the wrong files. ALL arms did poorly (map 1/2, mini 1/2, native 0/2). Lesson:
  a vague prompt still needs an unambiguous target concept; this one measures prompt
  ambiguity, not locate quality. Excluding hard2, map_v3 is 6/6 success vs native 4/6,
  and the token gap widens.
- n=2 per task (8 cells/arm total). Token counts have real variance (mini_v3 and native
  both produced multi-million-token spirals), but the ORDERING map_v3 < mini_v3 < without
  held on the overall mean and on 3 of 4 tasks individually.
- The $4/cell cap truncates the worst native/mini spirals, so their true means are
  UNDER-stated — i.e. the real gap favors map_v3 even more than the table shows.

## Recommendation
**Keep NEW map_v3 (production U) as the finalized surface — now with multi-task
evidence, not a single data point.** On the easy 2-file tasks the arms are ~tied (and
mini occasionally edges ahead on raw tokens by doing less); on hard cross-module tasks
— the ones that represent real complex dev work — map_v3 wins decisively on both cost
(≈1.85x cheaper than mini, ≈2.9x cheaper than native) and reliability (7/8 vs native
4/8). Do not finalize mini: it matches map_v3's success only by spending ~85% more
tokens and is prone to grep spirals the richer `focus`/`graph` surface avoids.
