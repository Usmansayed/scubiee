# Session log — multi-file + hard cross-module A/B suite (old mini_v3 vs new map_v3 vs native)

Date: 2026-10-02/03. Harness: scripts/claude_sdk_harness, model claude-sonnet-5,
engine warm/dense ~8.3-8.4k chunks. All runs offline-preflighted before live tokens.

## What this session set out to do
Decide whether the NEW map_v3 surface (production prompt "U": find/focus/related/graph,
bodies+wiring folded into one call) is actually better than the OLD mini_v3 (single
`map` returning location cards only) and than native-only (no Scubiee) — on REAL
multi-file dev work, not toy locates.

## Arc of the session
1. Resumed from MF1/MF2 (2-file "tidy seam" tasks). Validated oracles discriminate,
   preflighted, ran WITH(map_v3) vs WITHOUT(native) n=2.
   -> On easy 2-file edits the arms ~tie; map_v3 ~8% leaner overall, driven by the
      one semantic task; native cheaper on the literal task. Not decisive.
2. Diagnosed WHY map didn't dominate the easy case (trajectory autopsy): map carries
   fixed overhead (a ToolSearch turn to load the tool, the ~1442-tok U prompt re-sent
   every turn, bigger focus payloads) that is only repaid when locating is genuinely
   hard. On a greppable literal, native Grep is simply cheaper.
3. Built preflight_all.py — ONE no-Claude "is everything working perfectly?" self-check
   (engine health, both bridges + sync, budgets, every oracle's discrimination, arm
   wiring). Caught + fixed a self-inflicted test-isolation race (concurrent bridge
   spawns vs a live re-indexing engine). Now the gate before every live run.
4. 3-way easy run (without/mini_v3/map_v3): mini looked best on raw tokens on the
   SEMANTIC easy task — but only by doing LESS correct work (dropped the full hash;
   0/2 strict) while map_v3 was 2/2 strict. User correctly pushed back: easy tasks
   can't separate the arms.
5. Built ONE hard cross-module task (unify_cpu_thread_budget) with a strict oracle.
   map_v3 549k < mini_v3 630k < native 918k, all 2/2. First real separation.
6. User asked for MORE hard tasks to actually declare a winner. Built 3 more distinct
   hard seams (token accounting, freshness-gate wiring, strategy classification), each
   engine-free + strict + call-graph-only to locate. Preflighted to 31/31. Ran all 3
   arms n=2.

## Final numbers (4 hard tasks, n=2, STRICT grading, 8 cells/arm)
| arm | tok mean | success |
|---|--:|:--:|
| map_v3 (new) | 471,427 | 7/8 |
| mini_v3 (old) | 870,257 (+85%) | 7/8 |
| without (native) | 1,357,304 (+188%) | 4/8 |

Per task (map_v3 / mini_v3 / without), tok mean & strict success:
- cpu_thread_budget:  549k 2/2 | 630k 2/2 | 918k 2/2
- token_estimate*:    471k 1/2 | 367k 1/2 | 675k 0/2   (*ambiguous prompt, flawed task)
- changed_count_timing: 358k 2/2 | 470k 2/2 | 401k 2/2
- huge_change_strategy: 508k 2/2 | 2,015k 2/2 | 3,435k 0/2

## Verdict
map_v3 IS a win on hard cross-module dev: cheapest overall (1.85x < mini, 2.9x <
native), ties the best success rate (7/8), and never spiralled. Native spiralled to
3.1-3.7M tokens on the strategy task AND still failed (missed the hidden producer).
Keep production U/map_v3; do NOT finalize mini. Full verdict: HARD_SUITE_VERDICT.md;
raw cells: HARD_SUITE_RAW.md; easy-task context: MULTIFILE_3WAY_old_new_none.md +
MULTIFILE_WITH_vs_WITHOUT.md + HARD_TASK_DECISIVE_old_new_none.md.

## Why mini/native cost so much (mechanism, from traces)
Cost = result_bytes x turns. Native hunts the call graph by hand (11-26 Reads,
11-18 Greps on the worst cells), each full-file Read is thousands of chars, and every
result is re-sent on every subsequent turn. On huge_change_strategy, native pulled
~210k chars of grep/read into context across 54 calls -> 3.73M tokens. map_v3's focus
returns ~5-20k compact chars in 1-5 calls and converges in 11-16 turns.

## Harness / method notes for future studies
- Added a per-cell $4 budget cap (CTX_DEVMINI_MAX_USD) after a native cell ran >14 min.
  A capped cell returns a graded FAIL (honest) instead of burning unbounded tokens.
  CAVEAT: the cap truncates the worst native/mini spirals, so their true means are
  UNDER-stated -> the real gap favors map_v3 even more.
- STRICT_TASKS: hard tasks must be graded on oracle_strict (all checks), because the
  lenient 2/3 "ok" lets a partial (one-file) edit pass — which is exactly the failure
  we need to catch.
- Oracle design that works: name-agnostic + deterministic + a CROSS-FILE discriminator
  (a check that only passes when the grep-invisible second consumer is also edited).
  Validate base FAIL / partial FAIL / full PASS offline before spending any token.
- Lesson on task design: a vague prompt still needs an UNAMBIGUOUS target concept.
  token_estimate failed as a discriminator because "token" matches several unrelated
  subsystems; map_v3 reasonably landed in the wrong one. Future hard tasks: confirm the
  core concept is unique in the repo (one grep of the key noun) before using it.
