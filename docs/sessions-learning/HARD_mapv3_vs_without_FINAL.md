# Final hard dev tests: map_v3 (WITH) vs without (native) — post-fix, clean harness

This is the clean, post-fix confirmation round the user asked for: after fixing the
three issues from the earlier map_v3 study (P-H2 grep-wander, P-H3 silent fuzzy focus,
P-H6 Bash leak), with a thorough offline preflight (31/31) and a live confirmation cell
first. Two arms only: map_v3 (production U, WITH Scubiee) vs without (native tools only).
3 CLEAN hard cross-module tasks (the ambiguous token task excluded). n=2, STRICT grading,
$4/cell cost cap.

## Harness integrity this round
- Offline preflight: 31/31 EVERYTHING WORKING PERFECTLY before any token.
- **P-H6 Bash leak is CLOSED and proven in the live pipeline: `bash=0` across ALL 12
  cells** (both arms, every task). The "locate+edit only" guarantee now actually holds.
- Confirmation cell (n=1) passed for both arms before the full matrix.

## Results (tok mean, strict success, tool mix), n=2

| task | map_v3 | without |
|------|-------:|--------:|
| unify_cpu_thread_budget | **259,648 · 2/2** (map2 grep0 read2.5) | 633,068 · 2/2 (grep9 read7.5) |
| surface_changed_count_timing | **204,884 · 2/2** (map1 grep2 read2.5) | 240,964 · 2/2 (grep6 read3.5) |
| distinct_huge_change_strategy | **362,300 · 1/2** (map1 grep2 read4) | 1,757,816 · 1/2 (grep10.5 read13) |
| **OVERALL** | **275,611 · 5/6** | **877,282 · 5/6** |

## Verdict — map_v3 confirmed: same correctness, ~3.2x cheaper, no spirals

1. **Equal correctness (5/6 each).** Both arms solved 2 of 3 tasks cleanly and both split
   1/2 on the hardest (the strategy task), where even map_v3 occasionally edits only one
   of the two required files. So Scubiee is not a correctness unlock on these — a capable
   native agent can also get there.

2. **map_v3 is ~3.2x cheaper overall (276k vs 877k mean)** and far more consistent. On
   cpu_thread it was 2.4x cheaper (260k vs 633k) with ZERO grep; on the strategy task its
   cost was a small fraction of native's even when both failed (362k vs 1.76M).

3. **Native still spirals catastrophically on the hard seam.** On distinct_huge_change
   native averaged 10.5 greps + 13 reads and hit 2.15M tokens on one cell (41 turns) — and
   that cell FAILED. map_v3's worst cell on the same task was 578k. The gap is the native
   grep-hunt through a call-graph contract that has no single greppable literal.

4. **map_v3 got LEANER than the pre-fix suite.** On the same tasks the earlier (pre-fix)
   run showed map_v3 at 549k (cpu_thread), 358k (changed_count), 508k (strategy); this
   clean round shows 260k / 205k / 362k. Part is run-to-run variance, but the direction is
   favorable and no fix regressed cost.

## Honest caveats
- n=2; the strategy task is high-variance for BOTH arms (map_v3 147k–578k; native
  1.37M–2.15M). The $4 cap truncates native's worst spirals, so native's true mean is
  UNDER-stated — the real gap favors map_v3 more than 3.2x.
- Both arms split 1/2 on distinct_huge_change_strategy. map_v3 is cheaper-when-wrong, not
  more-correct, on that one. A prompt tweak to make map_v3 reliably edit BOTH consumers on
  the strategy seam is the remaining upside (not done — would need its own study).
- The fixes (fuzzy-focus note, no-grep-wander) didn't have a clean before/after isolation
  this round; they're verified present + unit-tested, and nothing regressed. The headline
  win (cost at equal correctness) reproduces the earlier finding on a clean harness.

## Bottom line
On genuinely hard cross-module dev work, with the harness now truly locate+edit-only,
**map_v3 matches native correctness while costing ~3.2x fewer tokens and never spiraling.**
This confirms the earlier verdict on a clean, fixed harness. Keep production map_v3 (U).
