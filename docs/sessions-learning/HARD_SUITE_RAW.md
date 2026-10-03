# Hard-task suite — raw per-cell results (4 hard cross-module tasks, 3 arms, n=2)

Grading: STRICT (all oracle checks pass). Per-cell cost cap $4 (CTX_DEVMINI_MAX_USD)
after a native cell spiralled >14 min on the first attempt. Engine warm/dense.

## HARD1 — unify_cpu_thread_budget (memory_budget + embedder)  [prior run]
| arm | tok mean | calls | map | grep | read | strict success |
|-----|---------:|------:|----:|-----:|-----:|:--------------:|
| map_v3  | 549,128 | 13.0 | 1.5 | 1.5 | 4.0 | 2/2 |
| mini_v3 | 630,162 | 15.5 | 1.0 | 2.0 | 5.5 | 2/2 |
| without | 918,368 | 25.5 | 0   | 8.0 | 9.5 | 2/2 |
Ordering map_v3 < mini_v3 < without (tokens); all solved. map_v3 clear win.

## HARD2 — unify_token_estimate (token_meter + session_store)  [AMBIGUOUS — see note]
raw cells (tok, success):
- map_v3  r1: 561,554  success=False  — **MISLOCATED**: edited hybrid_cbm/instructions.py,
  seir/caps.py, tests/seir_exp/test_spans.py (NOT the token_meter/session_store seam)
- map_v3  r2: 380,393  success=True   (correct files)
- mini_v3 r1: 384,129  success=False  (partial: missed the //4 duplicate)
- mini_v3 r2: 348,977  success=True
- without r1: 437,179  success=False  (partial)
- without r2: 912,010  success=False  (partial, 23 calls)
success: map_v3 1/2, mini_v3 1/2, without 0/2.

NOTE / CAVEAT: HARD2 is a FLAWED discriminator. The prompt ("make the token estimate
more accurate / everywhere that produces a token estimate") is semantically ambiguous
— this repo has multiple unrelated "token" subsystems, and map_v3 r1 landed in a
completely different one (hybrid_cbm/seir). It measures prompt ambiguity more than
locate quality. Treat HARD2 as the "vague-prompt stress" case, not a clean seam.
Lesson: a vague prompt needs an UNAMBIGUOUS target concept, or semantic search can
reasonably land in a different valid-looking neighborhood. All arms struggled; no arm
is advantaged here.

## HARD3 — surface_changed_count_timing (freshness + engine)  [CLEAN seam]
raw cells (tok, success); correct edit was engine.py-only (changed_count already in
freshness.to_dict), so the discriminator was "reach engine.search timings and wire it":
- map_v3  r1: 321,949  map=3 grep=0  success=True
- map_v3  r2: 393,498  map=3 grep=2  success=True
- mini_v3 r1: 411,450  map=3 grep=2  success=True
- mini_v3 r2: 527,727  map=2 grep=4  success=True
- without r1: 434,603  map=0 grep=7  success=True
- without r2: 368,080  map=0 grep=4  success=True
means: map_v3 357,724 | mini_v3 469,589 | without 401,342  ; success all 2/2.
Ordering map_v3 < without < mini_v3. map_v3 cheapest; mini_v3 most expensive here
(location-only -> more grep/read churn). All solved (unambiguous seam).

## HARD4 — distinct_huge_change_strategy (freshness + sync_status)  [CLEAN, sharpest discriminator]
raw cells (tok, success):
- map_v3  r1: 417,666   map=1 grep=2  success=True  (edited freshness.py+sync_status.py exactly)
- map_v3  r2: 598,101   map=5 grep=3  success=True
- mini_v3 r1: 1,270,808 map=1 grep=7  success=True  (spiral, 24 calls)
- mini_v3 r2: 2,758,639 map=1 grep=18 success=True  (big spiral, 50 turns/cap, 12 edits)
- without r1: 3,139,557 map=0 grep=11 success=False (partial: edited sync_loop/sync_status, missed choose_strategy producer)
- without r2: 3,730,270 map=0 grep=14 success=False ($4 budget cap, mislocated)
means: map_v3 507,884 (2/2) | mini_v3 2,014,724 (2/2) | without 3,434,914 (0/2).
map_v3 ~4x cheaper than mini, ~6.8x cheaper than native AND the only arm native failed.

## OVERALL (4 hard tasks, 8 cells/arm, STRICT)
| arm | tok mean | success |
|-----|---------:|:-------:|
| map_v3  | 471,427 | 7/8 |
| mini_v3 | 870,257 | 7/8 |
| without | 1,357,304 | 4/8 |
map_v3 +0% baseline; mini_v3 +85% tokens; without +188% tokens & half the wins.
Per-cell $4 cap truncates worst mini/native spirals -> their true means understated.
Verdict in HARD_SUITE_VERDICT.md: map_v3 is a win on hard cross-module work.
