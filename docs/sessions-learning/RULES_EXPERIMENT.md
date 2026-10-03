# Rules/instructions experiment: map_v3 vs map_v3 vs map_v3 (tool held fixed)

Goal: find the best map_v3 rules/instructions by varying ONLY the prompt (same bridge) and iterating.
Budgets this round: rules <=350, instructions <=2000.

## Variants
- **A** (P16 current): thorough - decision tree + confidence handling + "common mistakes" + trust
  block. rules 347 / instr 1748.
- **B** (lean): decision tree + 3 hard bans, no worked examples. rules 190 / instr 353.
- **C** (strict-budget): A-style + explicit "<=2 map calls per locate, 3rd map forbidden". rules 262
  / instr 556.
- **D** (round-2 tuned): A's trust block + C's hard cap + NEW "route vague/multi-file discovery to
  graph FIRST, and on a weak find use graph not grep". rules 314 / instr 805.

## Round 1 (A vs B vs C), 2 leak-queries

| query | A | B | C |
|---|---|---|---|
| idle_engine (clean multi-symbol) | **170k / 5 / 0 grep / rec 1.0** | 195k / 6 / 0 grep / 1.0 | 228k / 7 / 2 grep / 1.0 |
| first_map_skips_graph (hard 4-file) | 538k / 14 / 10 grep / rec 0.0 | 531k / 14 / 11 grep / 0.0 | **448k / 13 / 5 grep / rec 0.5** |

Read: on the CLEAN case A is best (tightest, no grep); C's hard cap pushed it off map onto grep.
On the HARD discovery case all three grep-spiralled; C's cap limited the damage (0.5 vs 0.0).
Config check: NONE used `graph` on the discovery query - so Round 2 forced graph-first.

## Round 2 (A vs D), same 2 queries

| query | A | D (graph-first) |
|---|---|---|
| idle_engine (clean) | **162k / 5 / 0 grep** | 267k / 8 / 2 grep (REGRESSED) |
| first_map_skips_graph (hard) | 618k / 14 / 10 grep / rec 0.0 | 487k / 14 / 10 grep / rec 0.0 |

D DID follow the instruction - trace shows `graph` FIRST, then `find`. But it STILL grep-spiralled 10
times and still failed (recall 0.0). And graph-first REGRESSED the clean case (an extra orientation
call it didn't need).

## The decisive finding: this failure is a TOOL recall gap, not a rules gap

`first_map_skips_graph` ("first request on a cold cache skips the heavy graph build") is a BEHAVIORAL
concept whose code does not lexically match the query words. `graph` and `find` both miss it
semantically; grep misses it too. D proved the instruction can route the agent to graph - but when
graph AND find both come back empty, no prompt can stop the agent flailing on a query the tool simply
cannot resolve. **Rules have hit their ceiling on this query; the fix would have to be engine/tool
retrieval quality (better semantic recall on behavioral concepts), not more instructions.**

Equally important: **graph-first as a blanket rule HURTS** - it added a wasted orientation call on the
clean query (D 267k vs A 162k). So forcing graph is net-negative.

## Winner and final rules

**A (the P16 version) is the best general prompt** - tightest and cheapest on everything map can
actually solve, and graph-first/strict-cap did not improve the unsolvable case while regressing the
solvable ones. Keep A as `map_v3`.

One targeted keeper from C: the "<=2 map calls, do not grep-spiral, after 2 locate attempts stop"
cap was the only thing that moved the hard query (0.0 -> 0.5) without hurting elsewhere. Fold JUST
that cap into A (not graph-first). That gives the final rules: A + hard anti-spiral cap.

## Actions
- Final `map_v3` rules = A + C's anti-grep-spiral cap (fold the cap line into RULES_MAP_V3 /
  INSTRUCTIONS_MAP_V3; drop the graph-first blanket routing - it regressed clean cases).
- Log the real blocker: discovery queries like first_map_skips_graph need better TOOL semantic recall
  on behavioral concepts; rules cannot fix a query map cannot locate. (Also both arms failed
  cold_start_status_warming earlier - same class of behavioral-concept miss.)
- n is small (1 per cell); treat the clean-case A-win and the graph-first regression as directional
  but consistent across both rounds.
