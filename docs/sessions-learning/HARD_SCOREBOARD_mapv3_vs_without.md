# Running scoreboard: map_v3 vs without across all clean hard tasks

Expanded evidence base to answer "is map_v3 a win on hard dev work?" with enough
independent tasks to be robust. All tasks: genuine cross-module seams whose second edit
site is call-graph-only (not a greppable literal), strict name-agnostic deterministic
oracles (baseline FAIL / partial FAIL / full PASS, all validated offline), full preflight
(39/39) before any token, $4/cell cap, bash hard-denied.

The ambiguous `unify_token_estimate` task is EXCLUDED (its "token" concept matched multiple
subsystems and caused a semantic mislocate — kept only as a known-bad task-design example).

## Scoreboard (map_v3 vs without, n=2, STRICT grading, 10 cells per arm)

| task | subsystem | map_v3 | without | ratio |
|------|-----------|-------:|--------:|:-----:|
| unify_cpu_thread_budget | memory_budget↔embedder | 259,648 · 2/2 | 633,068 · 2/2 | 2.4x |
| surface_changed_count_timing | freshness↔engine | 204,884 · 2/2 | 240,964 · 2/2 | 1.2x |
| distinct_huge_change_strategy | freshness↔sync_status | 362,300 · 1/2 | 1,757,816 · 1/2 | 4.9x |
| net_chunk_delta_payload | incremental↔sync_loop | 243,153 · 2/2 | 355,826 · 2/2 | 1.5x |
| consistent_safety_pause_detection | incremental↔__main__ | 95,810 · 2/2 | 119,612 · 2/2 | 1.2x |
| **OVERALL** | **5 distinct subsystems** | **233,159 · 9/10** | **621,457 · 9/10** | **2.67x** |

bash calls: map_v3=0, without=0 across all 20 cells (P-H6 fairness fix holds live).

## Verdict — map_v3 is a win, now on a 5-task / 5-subsystem corpus

1. **Identical correctness: 9/10 each.** Both arms solved 4 of 5 tasks every time and both
   split 1/2 on the hardest (the strategy seam). So Scubiee is not a correctness unlock —
   a capable native agent also reaches these edits. The win is cost + consistency.

2. **map_v3 is 2.67x cheaper overall (233k vs 621k mean)** and won tokens on ALL 5 tasks
   (ratios 1.2x–4.9x). It never spiraled; its worst single cell across the corpus was 362k.

3. **The gap scales with task difficulty — exactly what a legit retrieval win looks like:**
   - Easiest/most-localized seams (safety_pause, changed_count): ~1.2x — map barely helps
     because native grep resolves a near-literal target fast.
   - Mid seams (net_chunk, cpu_thread): 1.5x–2.4x.
   - Hardest call-graph seam (huge_change_strategy): 4.9x, where native grep-hunted to
     1.76M mean (one 2.15M-token cell that FAILED). A trick would save equally everywhere;
     a real retrieval advantage saves most exactly where locating is hardest. It does.

4. **Native's failure mode is unchanged and expensive:** on the strategy seam it averaged
   10+ greps and 13 reads, blew past 2M tokens, and still missed the hidden consumer. map_v3
   found both files in 1–5 map calls.

## Honest caveats
- n=2 per task (20 cells total). The strategy seam is high-variance for both arms; the $4
  cap truncates native's worst spirals, so native's true mean is UNDER-stated → the real
  gap is >2.67x.
- Both arms split 1/2 on the strategy seam; map_v3 is cheaper-when-wrong there, not more
  correct. Making map reliably edit BOTH consumers on that seam is the remaining upside.
- Two of the five seams (safety_pause, changed_count) are only mildly hard, so the overall
  mean is pulled toward parity by the easy tail — the headline 2.67x is conservative, not
  cherry-picked toward the hard case.
- Combined with the earlier pre-fix suite (4 hard tasks) and the first clean round, the
  direction is now consistent across ~9 distinct hard seams: map_v3 matches correctness at
  materially lower, lower-variance cost.

## Bottom line
Across 5 independent hard cross-module seams in 5 different subsystems, on a clean
locate+edit-only harness, **map_v3 matches native correctness (9/10 = 9/10) at 2.67x fewer
tokens, winning every task and widening the gap precisely where locating is hardest.**
This is the robustness the earlier single-task result lacked. Keep production map_v3 (U).


---

## Independent re-verification (new seam, built after the scoreboard) — HARD7

To address "the savings seem too large to believe," built ONE brand-new hard task in a
not-yet-tested subsystem and ran map_v3 vs without fresh. Full preflight 43/43 EVERYTHING
WORKING PERFECTLY first; bash=0 across all cells.

**Task: add_importers_expand_alias** (expand-direction vocabulary seam)
- GOLD files: `mcp_locate.py` (the `_EXPAND_DIRECTION_VALUES` validation whitelist, which
  even carries a "keep in sync with context_trace.py" comment) + `context_trace.py` (the
  hand-mirrored `d in {...}` routing sets that actually decide behavior).
- The second edit site is grep-invisible: `grep _EXPAND_DIRECTION_VALUES` finds only
  mcp_locate.py; context_trace spells the vocabulary as bare literals.

**Result (n=2, STRICT, $4 cap):**
| arm | tok mean | success | tool mix |
|---|---:|:---:|---|
| map_v3 | **163,621** | 2/2 | map 1.0, grep 1.0, read low |
| without | 426,064 | 2/2 | grep 7.5, read higher; r1 = 630k / 23 calls / 10 greps |
| ratio | **2.6x cheaper** | — | — |

bash=0 across all 4 cells (fairness fix held). Both arms correct; map_v3 ~2.6x cheaper,
with the native r1 showing the usual grep-hunt (630k, 10 greps) vs map_v3's 218k/109k.

**This reproduces the headline on a seam that did not exist when the earlier numbers were
produced** — so the ~2.5-3x savings are not an artifact of the specific tasks chosen.

### Updated clean-hard-task corpus (now 6 seams, map_v3 vs without)
cpu_thread, changed_count_timing, huge_change_strategy, net_chunk_delta, safety_pause,
+ importers_alias. Across all six the ordering holds: map_v3 cheapest on every task,
identical-or-better success, ~2.5-3x overall, gap widest on the hardest call-graph seam.
