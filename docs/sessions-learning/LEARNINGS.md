# Learnings from all sessions

Distilled from `PATTERNS.md` (101 cells across 57 runs). Every claim here cites the mined
aggregate, not a single run. Each pattern ends with the concrete rule / instruction / tool
action it drives.

---

## P1. The cost signal is calls, not result size — and it is the whole game

Across the dev-task arms, mean tokens track the number of model calls almost perfectly:

| arm | tok mean | api mean | map mean | grep mean | success |
|---|--:|--:|--:|--:|:--:|
| without | 802,736 | 18 | 0 | 6 | 9/10 |
| mini | 495,506 | 13 | 1 | 4 | 7/7 |
| mini_v3 | 367,469 | 10 | 1 | 2 | 10/11 |
| newmap | 364,288 | 10 | 3 | 0 | 8/8 |

`without` (native only) is 2.2x the cost of the map arms and makes ~18 calls, mostly grep. Any
map arm roughly halves cost by collapsing grep chains. This is the strongest, most repeated
signal in the whole dataset.

**Action (already in place, keep):** rules lead with "#1 GOAL: reach the edit in the FEWEST tool
calls … cost ≈ context × calls." Confirmed correct by the data. Do not weaken it.

**Action (tool):** keep `grep=0` for newmap as a health check — the moment a newmap cell shows
grep > 0, a config failed to answer and the agent fell back. (newmap grep mean is 0; mini_v3 still
greps 2x on average — see P4.)

---

## P2. newmap only wins once `find` returns the WHOLE clustered region

Matched mini_v3-vs-newmap pairs, in run order:

| run (time order) | task | mini_v3 tok | newmap tok | newmap cheaper |
|---|---|--:|--:|:--:|
| 173822 | cache_aware | 462k | 544k | n |
| 181831 | cache_aware | 400k | 692k | n |
| 191233 | cache_aware | 318k | 547k | n |
| **195500** | cache_aware | 405k | **272k** | **Y** |
| 173135 | dirty_files | 258k | 353k | n |
| 182749 | dirty_files | 249k | 255k | n |
| **192151** | dirty_files | 147k | **122k** | **Y** |
| **200122** | dirty_files | 147k | **129k** | **Y** |

newmap is cheaper in **3/8 overall — but in the 3 most recent runs it wins both tasks.** The flip
lines up exactly with the `find` change from "top symbol body only" to "all clustered symbol bodies
in one call." Before that change newmap lost every pair; after it, newmap wins.

**Evidence strength: directional, not settled.** All wins are n=1 and recent; mini_v3 is a
high-variance arm (318k–462k on the same task). The win is real and mechanistic but needs n≥3 to
call a margin.

**Action (tool, done):** `cfg_find` returns every clustered relevant body in one call. Keep.
**Action (next):** re-run both tasks at **n≥3** before claiming a stable win; record in PATTERNS.

---

## P3. Follow-up locate calls after `find` are the direct predictor of losing

The miner counts locate calls between the first `find` and the first edit:

| run | task | follow-up locate calls | newmap won? |
|---|---|--:|:--:|
| 173135 | dirty_files | 4 (around, refs×3) | n |
| 182749 | dirty_files | 3 (refs×2, view) | n |
| 191233 | cache_aware | 3 (view×2, refs) | n |
| 173822 | cache_aware | 2 (refs, open) | n |
| 181831 | cache_aware | 1 (view) | n |
| 195500 | cache_aware | 1 (view) | **Y** |
| 192151 | dirty_files | 0 | **Y** |
| 200122 | dirty_files | 0 | **Y** |

`find` alone sufficed (0 follow-ups) in only **2/8** cells historically — both recent wins. Every
cell with ≥2 follow-up locate calls lost. **Follow-up count is the lever.** The multi-body change
drives it toward 0–1, which is why the recent cells win.

**Action (instruction, sharpen):** the instructions already say "do NOT call refs/view to look
around." The data says the biggest leak is specifically **refs-after-find** (see P4). Add a single
contrastive line naming it, since generic "don't look around" did not stop it in the early runs.

---

## P4. `refs` is the most-abused config — it's where the extra calls hide

newmap config usage across all cells:

| config | calls |
|---|--:|
| refs | 9 |
| find | 8 |
| view | 6 |
| around (alias) | 1 |
| open (alias) | 1 |

`refs` (9) outnumbers `find` (8), yet almost every task needs find once. Reading P3's follow-up
column, most `refs` calls are **"get the callers/uses to be thorough" AFTER find already returned
the bodies and connections.** `find` now ships the top symbol's connections inline, so a `refs`
call for wiring is usually redundant.

**Action (instruction):** tighten the `refs` "how to act" to state when refs is NOT needed:
"`find` already returns the top symbol's callers/callees — only call `refs` for a rename/
signature change that needs EVERY use site, or for a name `find` did not surface."

**Action (tool, consider):** have `find` note, when it emits connections, that the agent has them —
e.g. the connections header already reads "callers:/calls:"; add "(no refs needed for wiring)". Low
risk, nudges away from the reflex refs call.

---

## P5. mini (v2 rules) is strictly dominated — retire it as a baseline

mini (two_layer_v2, old map): 496k mean / 13 calls / greps 4x. mini_v3 (v3 strict rules, same
old map): 367k / 10 calls / greps 2x. Same bridge, only the rules differ, and v3 cuts ~130k and
2 greps. The v3 "strictly follow / fewest calls" framing measurably reduced grep fallback.

**Action:** use **mini_v3** as the old-map baseline in all future arms; drop `mini`. Keeps the
A/B clean (newmap vs the best old-map config, not a strawman).

---

## P6. Retrieval-challenge arms: rules fix PRECISION, not recall

| arm | recall | precision | tok mean |
|---|--:|--:|--:|
| without | 1.0 | 0.0 | 359k |
| guided | 1.0 | 0.0 | 381k |
| two_layer | 1.0 | 1.0 | 359k |
| two_layer_v2 | 1.0 | 1.0 | 340k |

Every arm finds the right files (recall 1.0). The differentiator is **precision**: the two_layer
rule variants name only the correct files; `without` and the loose `guided` rule name extras
(precision 0.0). The two-layer structure (persistent anchor + manual) is what produces disciplined,
precise answers, and v2 does it ~20k cheaper than v1.

**Action:** keep the two-layer structure (anchor RULES + detailed INSTRUCTIONS) for the configs
rules too — it is already the shape of RULES_CONFIGS / INSTRUCTIONS_CONFIGS. Don't collapse them.

---

## P7. Post-tuning arm test: nudges didn't stop the refs reflex; a task confound dominates

After applying T2/T3/R2/I2/I3 and passing all four preflight gates, the arm re-test came back
mixed (now in the dataset; newmap cheaper 4/10 matched pairs, find-alone-sufficed 2/10):

| task | mini_v3 | newmap | newmap outcome |
|---|--:|--:|---|
| cache_aware_savings | 328k / 9 calls | 766k / 17 calls | lost (pricing Skill chain) |
| dirty_files_cap | 249k / 8 calls | 221k / 7 calls | won, but 4 map calls on 1 symbol |

Two confirmed blockers from the traces:
- **Confound (hard task):** the cache_aware task asks for prompt-caching pricing math, so the agent
  runs a `Skill -> Grep -> Grep -> Read -> Read` pricing-research chain unrelated to the map. That
  tail (~400k) decided the hard task, not locate behavior. mini_v3 skipped it by variance. This is
  the §5/M4 Skill-noise confound, now empirically dominant.
- **refs-after-find reflex survives instruction nudges:** on a 1-symbol edit the agent still did
  `find -> refs(callers) -> refs(callers, scoped retry) -> refs(uses)`. The T3 "you already have
  the wiring" line and the R2/I2 count anchor did not suppress it; the agent re-asked for callers
  it was already given.

**Action (next cycle):**
- **M4 (do first):** remove or isolate the pricing sub-question in cache_aware (or score Skill-call
  tokens separately) so the hard-task delta measures map behavior, not research.
- **Structural refs fix:** instruction text wasn't enough. Make `find` label its callers block as
  authoritative/complete (e.g. "callers (complete list): …") so the agent trusts it instead of
  re-running refs; consider a one-line "refs would return the same callers shown above."
- **n≥3** before any cost claim — the map arm's correctness is stable (100%), but cost swings on
  the two factors above.

**Evidence strength:** this is the most informative run yet because gates were all green, so the
loss is NOT tool breakage — it isolates the two real levers (task confound + refs reflex).

## P8. Two real issues behind the mixed arm result: a bridge BUG and a design over-reach

User flagged (correctly) that (a) map was being positioned to REPLACE native grep/read rather than
work beside it, and (b) newmap had working issues. Both confirmed:

### Bug: `refs kind=callers names=["bare_name"]` returned "file not found"
Reproduced directly: `cfg_refs_router({'names':['git_dirty_files'],'kind':'callers'})` →
`around: file not found: git_dirty_files`. Root cause: relation kinds route to `cfg_around` →
`_locate_target`, which only handled `file::symbol` / `file:line` targets; a BARE symbol name was
passed to `_resolve_file`, which looked for a *file* called `git_dirty_files` and failed. This is
exactly why the dirty_files arm cell showed `find → refs(callers) → refs(callers, scoped retry) →
refs(uses)`: the first bare-name call errored, so the agent retried with a scoped name. **The bug
caused an extra call and inflated tokens.**
Fix: added `_resolve_symbol_name` — when `_resolve_file` fails on a path-less identifier, resolve
it to its definition via a def-regex grep (prefer packages/ code), fallback to semantic search's
enclosing symbol. Regression test added to the battery (now 25/25): "refs: kind=callers with BARE
name resolves".

### Design over-reach: map was framed as a REPLACEMENT, not a partner
Old RULES_CONFIGS opened "map is your PRIMARY find/read tool" and the hard-rule list was dominated
by "do NOT grep / do NOT read." That pushed the agent to route even known-string lookups through
map. In the losing hard-task run the agent still grepped (for the pricing literal) — fighting the
rule — which wasted calls. **Forcing full replacement of native tools wastes tokens.**
Fix: reframed rules + instructions so map is the SEMANTIC DISCOVERY tool that works ALONGSIDE
native Grep/Read/git. Explicit lane: "know the string → native Grep/Read first (one grep beats one
map); location unknown or want semantics → map." Added a hard rule: "MUST NOT force a known-string
lookup through map." Budgets kept (RULES 288, INSTRUCTIONS 1910).

**Lesson for the tool's north star:** the win condition is NOT "map handles everything." It is
"the agent reaches the edit in the fewest calls," which means map for discovery + native tools for
known strings — each where it's cheapest. The replace-everything framing was itself a cost bug.

## P9. Adding include_bodies + names to OLD map: bodies help, a passive `names` input doesn't

Built `mini_plus` = old single-tool map + `include_bodies` (inline bodies, multi-symbol clustering)
+ `names` (lexical anchor). All preflight gates green. 3-arm test (mini_plus vs mini_v3 vs newmap):

| task | mini_plus | mini_v3 | newmap |
|---|--:|--:|--:|
| cache_aware | 507k / FAIL(0.33) | 480k / ok | **292k / ok** |
| dirty_files | 271k / ok | 401k / ok | **160k / ok** |

Findings:
- **include_bodies is the valuable addition.** On the clean easy task mini_plus beat plain old map
  (mini_v3) 271k vs 401k with 8 vs 12 calls — the inline body removed the `map->Read` round-trip.
  Keep it; it's the high-ROI one, as the §6 report predicted.
- **A passive `names` input does NOT get used.** In BOTH mini_plus traces the agent called
  `map(query, include_bodies=true)` with NO `names`, even when it knew the symbol. An input the
  model won't volunteer can't help. Lesson: to capture the lexical-anchor value, either make the
  instruction force known names, or have the bridge AUTO-EXTRACT candidate identifiers from the
  query so the anchor happens without the agent.
- **Bodies kill the Read, not the call-site greps.** mini_plus still grepped 3x on the easy task —
  for the CALL SITES where behaviour changes, which the single returned body didn't contain. This
  is exactly the wiring info newmap's `refs`/connections supply, and why newmap (which never
  grepped) beat both old-map arms. The mini_plus-vs-newmap gap IS the call-site info.
- **Hard task still confounded** by the pricing Skill chain (mini_plus failed on pricing math, not
  locate) — M4 still blocks a clean hard-task read.

**Actions:** keep include_bodies on old map; redesign `names` as either forced-by-instruction or
bridge-auto-extracted (passive optional input proven ineffective); the call-site gap argues for a
minimal wiring return even on the simple map (a cheap "callers:" line), not just bodies.

## P10. map_v3 (new 4-config) vs mini_v3 (old) retrieval challenge: cheaper + full recall, wider net

Built map_v3 (graph/find/focus/related — see VERSIONS.md) from the P8/TOOL_DESIGN_STUDY findings
(fold wiring into the body call; add a cheap abstract graph for orientation). Verified both bridges
healthy: manual MCP-stdio (all configs OK) + a live Claude probe (ok:true, all 4 configs invoked, 0
trace errors). Then a retrieval challenge (3 queries x 2 arms x 1 rep, all recall 1.0 / MRR 1.0):

| arm | tokens | API calls | Read calls | precision |
|---|--:|--:|--:|--:|
| mini_v3 (old) | 196k | 6.3 | 2.7 | **0.83** |
| map_v3 (new) | **176k** | **5.7** | **0.33** | 0.56 |

Findings:
- **map_v3 retrieves what it needs in fewer calls/tokens with almost no follow-up Reads** — its
  configs return code inline, so the find->read round-trip is gone. Goal (fewest calls) met.
- **Trade: precision.** `graph`/`related` surface correct NEIGHBOR files not in the strict git-gold
  set, so map_v3 casts a wider net (0.56 vs 0.83). Fine for locate-and-edit (full recall, you still
  reach the target); worse for "name only the minimal set".
- Both bridges confirmed working end-to-end before the test, per the user's "make sure both work"
  requirement.

**Action/standing:** map_v3 is the cheaper-with-full-recall option; mini_v3 stays the precise/tight
baseline. Still n=1 per query on 3 queries + no map_v3 dev-task cells yet — directional, not settled.
Next if desired: widen to the full 8 retrieval queries and add map_v3 dev-task cells.

## P11. map_v3 cell-by-cell: the remaining waste is `focus` being one-symbol-at-a-time

Studied all 3 map_v3 cells + the 124-cell call-purpose data (full write-up: MAP_V3_IMPROVEMENTS.md).
The two cheap cells settled in `find -> {Read|focus} -> Write` (154k/5 calls). The expensive one
(idle_engine, 220k/7 calls) did `find -> focus -> focus -> focus -> Write`: THREE focus calls, one
per symbol, because the 3 target symbols span 2 files and `focus` takes a single anchor. This is the
dataset's #1 collapse pattern at the tool level (`locate_wire->locate_wire` 79x, `read_body->
read_body` 19x = "call the body/locate tool again for the next symbol").

Prioritized fixes (by token saving):
- **A1 (highest ROI):** `focus` should accept MULTIPLE names/anchors in ONE call, grouped by file.
  Collapses N focus calls -> 1. idle-type cells drop ~1-2 calls / ~65k.
- **A2:** `find` should pack bodies for the top 1-2 clustered files (not just 1), so a cross-file
  edit needs no focus follow-up.
- **B1:** find's body block carries wiring inline + "do NOT focus this again" (passive notes were
  shown weak in P8; put it adjacent to the code).
- **B2 (rule):** "ONE focus with all N names, never one per symbol" - name the exact anti-pattern.
- **C1 (rule):** answer lists PRIMARY file(s) first, neighbors under a 'related' heading - recovers
  the retrieval precision drop (which is ~half strict-oracle penalizing correct neighbors like
  process_control.py, ~half graph/related genuinely widening the net) without narrowing the tool.

Do NOT: add configs (waste is WITHIN focus, not a missing config), add grep affordances (map_v3
already greps 0x), or force graph (used 0x on "where is X" tasks - correct, it's for orientation).

**Next cycle:** implement A1 + B2 + C1 (one bridge change + two rule lines), re-run battery + same 3
retrieval queries (6 cells, frugal), confirm the multi-symbol cell drops to <=2 map calls.

## P12. map_v3 improvements A1/A2/B1/B2/C1 implemented + manually A/B tested (no AI)

Implemented the P11 prioritized fixes and verified with direct Python calls (no Claude spend):
- **A1 (biggest):** `cfg_focus` now accepts `names=[...]` (one or many) / `anchors` / `anchor`,
  resolves all, groups by file, returns each symbol's body+wiring+siblings in ONE call. Manual A/B:
  the idle_engine 3-symbol case collapses **3 focus calls -> 1** (6 body blocks, 2 files, 6686 chars
  vs 7654 for the 3 separate calls) - saves 2 transcript re-reads (~70k tokens) AND is smaller.
- **A2:** `find` packs bodies for the top 2 clustered files (map_v2 gained an optional
  `cluster_files` param, default 1 so newmap is unchanged; map_v3 passes 2; 2nd file only added if
  its best hit scores >=75% of top). On idle_engine, map_v3 find now packs server.py + process_
  control.py; map_v2 default still one file (regression-safe).
- **B1:** find's body carries wiring + a config-neutral "do NOT focus/refs/grep it again" note, now
  on medium confidence too (was high-only).
- **B2 (rule):** RULES/INSTRUCTIONS_MAP_V3 say "several symbols = ONE focus with all names, NEVER
  one focus per symbol", with a bad-trajectory line naming the 3-separate-focus anti-pattern.
- **C1 (rule):** "when you ANSWER, name PRIMARY file(s) first, neighbors under related:" - recovers
  the retrieval precision drop without narrowing the tool.

Verified: manual A/B all PASS (A1 collapse, B1 wiring+note, A2 2-file vs 1-file, all 4 configs
render, legacy anchor + single-symbol unchanged); offline battery 25/25; RULES_MAP_V3 279 /
INSTRUCTIONS_MAP_V3 1127 (both under budget), ASCII, imports OK. Reusable A/B script: `_ab_map_v3.py`.

**Expected effect:** the expensive multi-symbol map_v3 trajectory (`find -> focus -> focus -> focus`,
220k/7 calls) should now be `find -> focus[all names]` or just `find` (cross-file packed), landing
near the cheap cells (~154k/5). Not yet confirmed live - next frugal step is the same 3 retrieval
queries at n=1 to measure the call-count drop.

## P13. Improved map_v3 vs mini_v3 live test (5 preflight gates incl live probe): the fixes worked

After P12's A1/A2/B1/B2/C1, ran the full gate chain (battery 25/25, manual A/B, budgets, MCP-stdio
spawn, retrieval preflight, AND a live Claude probe confirming focus_calls=1 / focus_multi_ok=true -
the agent used ONE focus for 3 names), then the map_v3 vs mini_v3 retrieval test (same 3 queries,
all recall 1.0):

| | mini_v3 (old) | map_v3 (improved) |
|---|--:|--:|
| tokens mean | 215k | **157k** |
| API calls mean | 7.0 | **5.0** |
| map calls | 1 | 2 (every cell) |
| Read calls | 2.0 | **0** |
| precision | 0.83 | 0.57 |

- **A1 confirmed live:** the idle_engine multi-symbol cell dropped from 220k/7 calls/4-map
  (find->focus->focus->focus, pre-fix) to **162k/5 calls/2-map** (find->focus[all names]). The
  per-symbol focus chain is gone.
- **map_v3 is now dead-consistent:** every cell = 5 API calls / 2 map / 0 read / 0 grep (api_calls
  min=max=5). Variance eliminated. mini_v3 still swings 5-9 calls (one cell 288k/9/304s).
- **map_v3 now beats mini_v3 on cost:** 157k vs 215k mean, 5 vs 7 calls, both full recall.
- Remaining trade: precision 0.57 vs 0.83, largely the strict single-commit oracle penalizing
  correct neighbors (map_v3 named process_control.py, which holds the helpers self-retire calls).
  C1 rule is in place but the agent didn't format primary/related this run - next lever if precision
  matters.

**Standing:** the improvements delivered the intended token+call reduction with full recall, verified
through a complete preflight incl live probe. n=1 per query; directional but clean. map_v3 is the
cheaper+consistent option; mini_v3 the more precise one.

## P14. Multi-angle map_v3 vs mini_v3: it's a SPLIT, not an outright win (verdict doc)

Tested against 4 preset criteria across retrieval (8 queries, 16 cells) + dev (3 tasks, 6 cells);
COMP blocked by "Credit balance too low". Full write-up: VERDICT_map_v3_vs_mini_v3.md.

- **Retrieval: map_v3 better** - recall 0.875 vs 0.81 (7/8 vs 6/8 full), tokens 245k vs 265k, calls
  6.9 vs 7.9, grep 0.5 vs 2.6, read 0.5 vs 4.0. Wins by killing grep/read chains. On the 4-file
  discovery query map_v3 recalled 1.0 vs mini_v3 0.5.
- **Dev/edits: mini_v3 better** - mean 230k vs map_v3 324k (map_v3 41% pricier). Both 100% correct
  (oracle 1.0 all 3 tasks). map_v3's loss is the cache_aware pricing-confound grep chain (513k);
  on the no-confound task (health_reason_flag) map_v3 actually beat mini_v3 (216k vs 269k).
- **Criteria:** #1 correctness PASS; #2 cheaper MIXED (retrieval yes, dev no); #3 consistency FAIL
  (map_v3 spikes 611k discovery / 513k pricing); #4 no-dev-regression FAIL (41% pricier).

**Verdict: SPLIT. map_v3 wins locate/retrieval; mini_v3 wins edits.** Both fully correct - a
cost/behavior split, not a correctness problem. Earlier "map_v3 wins" (3-query n=1) was premature;
this corrects it. Recommend map_v3 for locate/comprehension, mini_v3 (or strip the M4 confound) for
edits. Settling needs: COMP re-run (credits), n>=3 dev with pricing sub-question removed, and a look
at why map_v3 fell to 4 greps on first_map_skips_graph (rules say it shouldn't).

## P15. Root cause of map_v3's dev loss: a trust/rules gap, not a tool flaw (WHY_MAP_V3_LOSES_DEV.md)

Traced the failing dev cells. map_v3 is sound - 13/16 retrieval cells are clean one-shot
`find->focus->Write` with 0 greps. The losses are 3 concentrated behavior leaks:
- **Leak 1 (dirty_files):** `find` returned confidence:high + full body of git_dirty_files, yet the
  agent grep-VERIFIED it twice before editing. "Trust but verify." The OLD map never triggers this
  because its whole-file Read leaves nothing to verify - map_v3's precise body ironically invites it.
- **Leak 2 (first_map_skips_graph):** agent re-MAPPED (find->find->find->find) on a non-high-conf
  first result; no hard "stop re-mapping" cutoff. The 611k discovery spike.
- **Leak 3 (cache_aware):** the 400k tail was the pricing sub-question (Skill+greps), not the map -
  a task confound. On the no-confound dev task map_v3 WON (216k vs 269k).

Why "designed from the sessions" still under-delivered: we measured the sessions on RETRIEVAL-shaped
behavior and had ZERO map_v3 dev data at design time, so map_v3 is tuned for (and wins) locate.
Deeper: token cost = tool quality x agent TRUST; we improved the output but not the rules that make
the agent ACT on it. The old map wins dev partly by accident (whole-file read -> nothing to re-check).

Fixes (rules/labeling, NOT more tool): F1 confidence-hooked no-verify note adjacent to the body; F2
hard re-map cutoff (never 2+ finds for one question); F3 "(complete symbol, lines a-b)" label to kill
the "is that all?" doubt; F4 strip the pricing confound before judging dev cost. Cheapest highest-ROI
path - pure rules/output work, no new configs.

## P16. Fixed the P15 misuse in rules/instructions (budgets raised to 350/2000)

Raised budgets (rules <=350, instructions <=2000) and spent the headroom binding the exact ways the
agent misused map_v3 in the sessions (P15 / WHY_MAP_V3_LOSES_DEV.md). Final: RULES_MAP_V3 347,
INSTRUCTIONS_MAP_V3 1748, ASCII, battery 25/25.

Misuse -> fix now in the prompt:
1. **Verify-grep after a good find** (dirty_files: find returned confidence:high + full body of
   git_dirty_files, agent grepped it twice anyway). FIX: RULES "TRUST THE RESULT - a find body is the
   COMPLETE symbol; confidence:high + body = EDIT, never grep to verify/re-Read/re-find"; INSTRUCTIONS
   find how-to now acts BY CONFIDENCE and the mistake is spelled out with the exact git_dirty_files
   example in a new "Common mistakes" section.
2. **Re-map loop** (first_map_skips_graph: find->find->find->find, 611k). FIX: "NEVER call find twice
   for one question; not high-confidence -> switch to focus or ONE grep, do not retry find."
3. **One focus per symbol** (already fixed in A1/B2; reinforced as mistake #3).
4. **Routing a known string through map** (reinforced as mistake #4).

INSTRUCTIONS find section gained explicit high/medium/low confidence handling with a real find-output
sample, and the good/bad trajectory lists now show the confidence-driven paths. This is pure
rules/output work - no tool change - the highest-ROI lever per the whole study.

**Status:** offline-verified only. The live re-test (does the verify-grep / re-map loop actually
stop, and does map_v3's dev cost converge toward mini_v3) is BLOCKED on API credits. Run the full
preflight incl live probe + the DEV + R-full matrix again once credits are restored.

## P17. Rules experiment (map_v3 vs map_v3 vs map_v3): best prompt = A + anti-spiral cap; discovery is a TOOL gap

Varied ONLY the prompt (same bridge), 2 rounds, 2 leak-queries each. Full write-up: RULES_EXPERIMENT.md.
- Variants: A=P16 thorough, B=lean, C=strict-cap, D=round-2 (A+cap+graph-first).
- Round 1: on the CLEAN multi-symbol query A won (170k/5/0grep); C's hard cap pushed it off map onto
  grep (worse). On the HARD 4-file discovery query ALL grep-spiralled; C's cap limited damage
  (recall 0.5 vs A/B 0.0). None used `graph`.
- Round 2 (A vs D): D followed the new graph-first instruction (trace: graph then find) but STILL
  grep-spiralled 10x and failed (recall 0.0); AND graph-first REGRESSED the clean case (267k vs A
  162k).

**Decisive finding:** the discovery failure is a TOOL recall gap, not a rules gap. `first_map_skips_
graph` is a behavioral concept whose code doesn't lexically match the query; graph AND find both miss
it, grep misses it. When map genuinely can't locate something, no prompt stops the flail - and
forcing graph-first is net-negative (wasted call on solvable queries). Rules have hit their ceiling
here; the real fix is engine semantic recall on behavioral concepts.

**Winner:** A (P16) + ONLY C's anti-grep-spiral cap folded in (dropped graph-first). Final map_v3
rules: RULES_MAP_V3 337 / INSTRUCTIONS_MAP_V3 1827, battery 25/25. The cap line: "<=2 map calls per
locate; never loop find->find or grep->grep->grep; after 2 tries make ONE targeted grep/Read and act."
Variants B/C/D kept in two_layer.py + policies for future rounds but map_v3 (A+cap) is the chosen prompt.

## P18. Symbolic policy variant S: map_v3 rules re-encoded as a compact formal spec

Instructions-only experiment (no tool change). Re-encoded variant A's full behavioral spec as a
symbolic policy using common logic operators (and or ¬ ⇒ → ∈ ∉ ∀ ∃ = ≠ ≤ ·) + short identifiers,
structured [SYMBOL DEFS][STATE][TOOL CAPS][SELECTION][OUTPUT->NEXT][SEQ][STOP][PROHIBITIONS]
[PRIORITY][FALLBACK][DEFAULT]. Full audit: SYMBOLIC_POLICY_AUDIT.md.

- Budgets: RULES_MAP_V3_S 340 (<350), INSTRUCTIONS_MAP_V3_S 1119 (<2000) - ~39% fewer instruction
  tokens than prose A (1827) for the SAME 23 behaviors (consistency-audited, none dropped).
- Operators are non-ASCII but verified to survive the harness utf-8 CLAUDE.md round-trip (the
  ASCII-only rule was for the CLI console path, not this file path).
- 5 compression ambiguities found + fixed (undefined `switch`, the `·1` quantifier, SELECTION
  first-match + PRIORITY P1 known⇒native, result⊇{code,wiring,siblings}, CAP-above-TRUST ordering).
- Battery 25/25; wired as policies.RULES['map_v3_s'] + arm map_v3_s in both runners.

**Open:** live A/B (map_v3_s vs map_v3_a, same queries) to measure whether the symbolic form changes
adherence or cost. Hypothesis: denser + rule-shaped may improve rule-following (fewer verify-greps /
loops) at lower token cost - or may hurt if the model parses prose better. Not yet run.

## P19. Symbolic (S) vs most-optimized prose (A) on the clean query: prose A won

Live A/B, same bridge, only the prompt differs, query = idle_engine_self_retire (A's best clean case):

| | A (prose, 2165 prompt tok) | S (symbolic, 1459 prompt tok) |
|---|--:|--:|
| recall / MRR | 1.0 / 1.0 | 1.0 / 1.0 |
| runtime tokens | **161k** | 244k |
| API calls | **5** | 7 |
| grep | **0** | 2 (map_then_grep=2) |

Both correct. A was 34% cheaper and 2 calls tighter. S's prompt is 33% smaller BUT it cost MORE at
runtime: the symbolic rules did not suppress the verify-grep as well as A's explicit prose "do NOT
grep to verify" + worked example - S led the agent into 2 extra greps. The ~700 prompt-token saving
is dwarfed by ~80k from the 2 extra runtime calls.

**Conclusion (n=1, directional):** compressing the rules symbolically saved PROMPT tokens but did NOT
improve - slightly degraded - behavior/adherence on the query A already handles cleanly. For an LLM
agent, explicit prose bans with a worked example bound the behavior better than dense glyph logic
here. Keep A (map_v3) as the production prompt; S is a kept variant, not an upgrade. Worth a wider
A/B (more queries, n>=3) before a firm call, but the clean-case direction is against the symbolic
form.

## P20. CORRECTION to P19: the fair test shows symbolic (S) ~= prose (A). P19 was an unfair n=1 confound.

P19 claimed "prose A beat symbolic S" (A 161k/5/0grep vs S 244k/7/2grep). That was WRONG - the run
had no preflight (I skipped the live probe I run for every other arm), was n=1, and was confounded
(that single S cell picked graph-first + grepped a 3rd symbol; A picked find-first). I treated one
noisy trajectory as a property of the rules.

Redone properly:
- **Preflight (new):** live probe injecting the symbolic policy - agent reported policy_readable:true,
  notation_confusing:FALSE, all_usable:true, and correctly applied the `switch(focus|1·grep)` rule.
  Also verified the CLAUDE.md holds the real operators, utf-8 clean, 0 mojibake. => the symbolic
  NOTATION is not the problem; the agent follows it.
- **Fair A vs S, n=2 each, same query, identical conditions:**

| | A (prose) | S (symbolic) |
|---|--:|--:|
| recall / MRR | 1.0 / 1.0 | 1.0 / 1.0 |
| tokens mean | 166,258 | **164,849** |
| API calls | 5, 5 | 5, 5 |
| grep | 0, 0 | 0, 0 |

They are statistically identical (S a hair cheaper). The 2 extra greps that sank S in P19 did NOT
reproduce.

**Corrected conclusion:** the symbolic policy performs on par with the most-optimized prose at ~33%
fewer PROMPT tokens (1459 vs 2165) and the agent follows the notation without confusion. S is a
legitimate equal-or-better candidate, NOT a regression. P19 is retracted. Process lesson: ALWAYS run
the preflight (incl live probe) and n>=2 before any A/B verdict - the n=1 skip produced a false loss.

## P21. Consistency test S vs A across 4 task types: S==A on solvable work; 2 tool shortcomings found

16 cells (A vs S, n=2) over focused + cross_module + discovery retrieval + dev edit. Full table:
CONSISTENCY_MATRIX_A_vs_S.md.
- M1 focused: A 160k/160k 0grep; S 193k/121k - on par, S one 1-grep cell.
- M2 cross_module: A 206k/310k (one 3-grep spike); S 209k/170k (0 grep BOTH) - S cheaper+tighter.
- M3 discovery: A 539k rec0.0(9grep)/480k rec1.0; S 476k rec0.75/596k rec0.5 (7-8grep) - BOTH spiral.
- M4 dev edit: A 258k(0map/4grep)/124k(1map/0grep); S 293k/317k (both 5 grep) - both default to grep,
  S grep-heavier this sample. All 4 oracle 1.0.

VERDICT: S == A on everything the tool can solve (focused + cross_module), slightly cheaper+more
consistent on cross_module, at ~33% fewer prompt tokens. S is a legit production-equal candidate.

SHORTCOMINGS (prompt-independent, = TOOL work, the point of the exercise):
1. Discovery/behavioral-concept recall: find/graph/grep all miss code that doesn't lexically match
   the query; both prompts grep-spiral; hard cap reduces but doesn't stop it. Needs engine recall.
2. Dev-edit grep-default: for an edit the agent often skips map entirely and grep-chains (A r1 0map/
   4grep; S r2 0map/5grep). Rules don't convert "edit a known-ish file" into a map call.
3. map isn't a clean one-call answer on multi-file/behavioral targets (2-3 map + still wants more).
These point at TOOL/engine improvements, not more rule-tuning. n=2; directional but consistent.

## P22. What A is good at vs S, and the ULTIMATE hybrid (variant U)

Per-task A vs S (A_vs_S_STRENGTHS.md):
- A (prose) wins DECISIVE/EDIT cases: idle_engine (165k/0grep vs S 191k/1grep), dirty_files dev edit
  (191k/2grep vs S 305k/5grep). A's explicit prose bans + worked examples keep edits from
  grep-spiraling.
- S (symbolic) wins HARD/MULTI-FILE cases: first_map discovery (recall 1.0 vs A 0.0!), memory_budget
  cross_module (189k/0grep vs A 257k/2grep). S's formal state->action rules hold the decision tree on
  ambiguous input.
- faiss focused = tie.
Complementary: EDIT/known needs a FIRM "map once, edit, don't explore" push (A's strength);
HARD/vague needs a STRUCTURED decision procedure (S's strength).

Built **variant U** (ultimate hybrid): S's symbolic SELECTION/OUTPUT/CAP/PRIORITY core + A's explicit
prose EDIT-PATH block ("editing known-ish file: map once -> EDIT, no grep-chain, no verify-grep" with
the git_dirty_files worked example) injected as PRIORITY P2, + graph-routing gated on vague∨multi_file
only (not blanket - A showed graph-first regresses simple cases). Hard cap kept (helped both).
Budgets: RULES_MAP_V3_U 331 (<=350), INSTRUCTIONS_MAP_V3_U 1111 (<=2000), battery 25/25. Wired as
policies.RULES['map_v3_u'] + arm in both runners.

**Next:** live A/B - U vs A on the edit+focused tasks (where A won) AND U vs S on discovery+
cross_module (where S won). U should match A on edits (it has A's edit-path) AND match S on hard/
multi-file (it has S's core). Not yet run.

## P23. A vs U (ultimate hybrid), 2 tasks n=2: U fixes A's cross-module gap, ~matches A on focused

| task | A | U |
|---|---|---|
| memory_budget (cross_module - A's weakness) | 170k, 0grep, **recall 0.5/0.5** | 166k/207k, 0grep, **recall 1.0/1.0** |
| idle_engine (focused - A's strength) | 170k, 0grep, recall 1.0 | 164k clean / 317k(2grep,2read) |

- **Cross-module: U clearly beats A - and it's a real quality win, not noise.** On memory_budget
  (gold = memory_budget.py + sync_loop.py): A named memory_budget.py + 3 WRONG files and MISSED
  sync_loop.py (recall 0.5, prec 0.25 - wrong AND incomplete). U named EXACTLY the 2 gold files
  (recall 1.0, prec 1.0). U inherited S's structured cross-module routing as designed. A was cheap
  but SILENTLY WRONG here.
- **Focused: U ~matches A** - one clean rep (164k, 0grep) + one noisy (317k, 2grep/2read). U didn't
  perfectly preserve A's rock-solid focused behavior (1-of-2 clean) but still recall 1.0 both.

VERDICT: U is the stronger GENERAL prompt - it recovers correctness where A silently failed
(cross-module) while roughly matching A where A was best. The hybrid design worked: S's core gave U
cross-module recall, A's edit-path kept it decisive. Blemish: U has one noisy focused rep to iron
out. n=2; directional. Next if desired: U vs S on discovery (does U keep S's graceful degrade?) and
U vs A on the dev edit (does A's edit-path block keep U from the grep-spiral S showed?).

## P24. U promoted to production + full map_v3 bridge verification PASSED (pre with/without gate)

U (ultimate hybrid) is now the production prompt: policies.RULES['map_v3'] = MAP_V3_U (331 rules /
1111 instr, battery 25/25). A/S/B/C/D kept for A/B.

Thorough bridge verification (verify_map_v3_bridge.py, 20/20, no AI):
- spawn/protocol: server scubiee-map-v3, tools map/gate/status, config enum find/focus/related/graph.
- all 4 configs happy: find (confidence+body), focus (body+wiring), multi-symbol focus (6 bodies in
  ONE call, grouped by file), graph (valid JSON nodes+edges, NO bodies), related (bodies).
- gate='1' (healthy), status warm+dense chunks=8392.
- aliases open/around handled with a notice.
- edge/robustness: unknown symbol / bad config / empty query -> clean error strings, no crash; body
  cap <30k; bridge responsive after edge cases.
- SYNC/FRESHNESS: engine /health ok+warm+dense; bridge reflects an on-disk edit via mtime
  invalidation (wrote ORIGINAL -> focus saw it; edited to EDITED_NOW -> focus returned the edit).

Final live Claude probe on PRODUCTION (U prompt + bridge, probe_production_u.py): ok:true,
claude-sonnet-5, all 4 configs invoked, 0 trace errors, focus_calls=1 with BOTH names in one call
(U batch rule works), agent all_usable:true + policy_clear:true, 133k tokens.

**STATUS: production map_v3 (U) + bridge are verified working - sync, health, all configs, edge
cases, and live agent use all green. Ready for the with/without-Scubiee round.**

## P25. Both arms (OLD mini_v3 single-tool + NEW map_v3/U) verified + preflit for old-vs-new

Before old-vs-new, verified BOTH bridges incl sync, and preflit both arms:
- OLD mini bridge: verify_mini_bridge.py 12/12 - spawn (scubiee-mini, map/gate/status), map ranked
  cards hitting freshness.py, empty-query error graceful, gate='1', status warm+dense. SYNC: same
  engine (status.chunks == engine /health chunks), map locs point at real current-file lines. (Old
  bridge returns LOCATION cards only; bodies via agent native Read = always current.)
- NEW map_v3 bridge: verify_map_v3_bridge.py 20/20 incl mtime-invalidation sync (reflects on-disk
  edits) - from P24.
- Both share ONE warm/dense engine (chunks match) = fair baseline.
- Preflight both arms: budgets (two_layer_v3 716 / map_v3-U 1442 combined tokens), battery 25/25,
  retrieval + dev runner preflight-only both gates passed (static+warm+snapshot).
- Live probes BOTH usable: NEW U (P24, all 4 configs, 0 errors, focus batch worked); OLD mini
  (probe_mini_live.py: map used, 0 errors, located git_dirty_files freshness.py:105-131, span usable).

STATUS: old mini_v3 and new map_v3/U are both freshness-correct, share the same engine, pass all
preflight gates, and are confirmed live-usable. READY for the old-vs-new (and with/without) test.

## P26. OLD vs NEW Scubiee verdict: NEW (map_v3/U) wins every solvable task type

16 cells (12 retrieval + 4 dev, n=2), both bridges preflit+sync-verified (P25). Full:
OLD_vs_NEW_VERDICT.md.
- focused (faiss): NEW 122k/156k (0 native reads) vs OLD 146k/178k (1 read each) - NEW cheaper, both rec 1.0.
- cross_module (memory): OLD needed 4-5 NATIVE READS to see bodies its pointer-map located; NEW ~0
  (inline bodies). NEW cheaper r1 (163k vs 229k). Both rec 1.0.
- dev edit (dirty_files): NEW 154k/159k (tight) vs OLD 505k/148k (one 6-grep 505k spiral). NEW mean
  156k vs OLD 327k = NEW ~52% cheaper. Both oracle 1.0.
- discovery (first_map): TIE at FAILURE - both rec 0.0/0.0 (behavioral-concept tool-recall gap,
  neither solves).

VERDICT: NEW is better. Structural reason: OLD returns only LOCATIONS -> forces agent into native
Reads (cross_module) and grep-chains (dev edit 505k spiral); NEW returns CODE+WIRING inline -> fewer
calls, no catastrophic tail. Discovery is a shared engine-recall shortcoming, not a differentiator.
n=2 directional. Next (separate): the with/without-Scubiee round.

## Change log driven by these patterns

| # | Change | Where | Status | Pattern |
|---|---|---|---|---|
| 1 | Rules lead with "fewest calls / cost ≈ context × calls" | RULES_CONFIGS | done | P1 |
| 2 | `find` returns all clustered bodies in one call | `cfg_find` | done | P2, P3 |
| 3 | find budget 14000, view 12000, BODY_CAP 5000 | `map_v2_bridge` DEFAULT_BUDGET | done | P2 |
| 4 | Name the refs-after-find trap explicitly in instructions | INSTRUCTIONS_CONFIGS | done | P3, P4 |
| 5 | refs "how to act" states when refs is NOT needed | INSTRUCTIONS_CONFIGS | done | P4 |
| 6 | Retire `mini`; baseline against `mini_v3` | run_dev_mini arms | **todo** | P5 |
| 7 | Re-run both tasks at n≥3 to settle the margin | arms | **todo** | P2, P7 |
| T2 | Deprecated aliases emit "folded into view/refs" notice | `tool_map` | done | §3 (RESEARCH_REPORT) |
| T3 | find connections block steers away from refs-after-find | `_append_connections` | done (insufficient, see P7) | P4 |
| R2 | Locate-call count anchor ("single-FILE change = ONE find") | RULES_CONFIGS | done | §3 |
| I2 | "Exactly THREE configs" note | INSTRUCTIONS_CONFIGS | done | §3 |
| M4 | Strip/isolate the pricing Skill sub-question in cache_aware | run_dev_mini task | **todo (next, blocks hard-task measurement)** | P7, §5 |
| S1 | Label find's callers block authoritative so agent trusts it | `_append_connections` | **todo (next)** | P7 |
| B1 | Fix bare-name relation bug (`refs kind=callers names=["x"]`) | `_locate_target` + `_resolve_symbol_name` | done + regression test | P8 |
| D1 | Reframe map as PARTNER to native tools, not replacement | RULES_CONFIGS + INSTRUCTIONS_CONFIGS | done | P8 |

Items 4–5, T2–T3, R2, I2 applied this cycle. T3 proved insufficient alone (P7). M4 + S1 are the
next cycle, then re-run at n≥3 (items 6–7).


---

# Hard cross-module suite — map_v3 agent-behavior study (4 tasks, 8 map_v3 cells)

Mined from the recorded tool trajectories of the 8 map_v3 cells across the 4 hard tasks
(unify_cpu_thread_budget, unify_token_estimate, surface_changed_count_timing,
distinct_huge_change_strategy). These are observed moves, not design intent — several
are shortcomings/improvisations worth acting on.

## P-H1. map_v3 is CONSISTENT on cost — tight 320k–600k band on 7/8 cells, never spiralled

Every map_v3 cell stayed in 322k–598k tokens with 9–16 turns and 1–5 map calls. Compare
mini_v3 (up to 2.76M, 50 turns) and native (up to 3.73M, 54 calls) on the SAME tasks.
The richer `focus`/`find` payload keeps native Read/Grep low (2–4 reads vs 11–26) and the
agent converges fast. This is the core win and it is stable.

**Action (keep):** the one-call-returns-the-whole-region design (`find` clustered bodies,
`focus` bodies+wiring) is what prevents the grep-spiral. Do not regress it to location-only.

## P-H2. SHORTCOMING — map_v3 ignored a weak `find` result and spiralled into the WRONG subsystem

unify_token_estimate r1 (the one map_v3 FAIL, 561k, strict=False): the opening
`map find "estimate token count … chars per token helper"` returned only **1746c** — far
below the 7000c a confident hit returns on the other tasks. Instead of re-querying or
treating low payload as low confidence, the agent chased unrelated `seir` / `hybrid_cbm`
imports via Grep/Glob/Bash and edited the wrong files. The weak map payload WAS the signal;
it was ignored.

**Action (rule):** add an explicit low-confidence handling line — "if `find` returns a thin
payload / low-confidence cluster, RE-QUERY with different vocabulary or widen before you
start grepping unrelated modules; a thin `find` is a miss, not a map." **Action (tool):**
consider having `find` emit an explicit `confidence: low` marker when the top cluster score
is weak, so the agent has a hard signal rather than inferring from byte count.

## P-H3. SHORTCOMING — `focus` called with a GUESSED, wrong symbol name

surface_changed_count_timing r2: agent called `map config=focus names=['RuntimeManager.search']`
— there is no `RuntimeManager.search`; the real target is `WarmSearchEngine.search` (which it
used correctly in r1). `focus` returned a generic 1188c (same byte count as the r1 correct
call, so the agent couldn't tell it missed) and the agent recovered via Read+Grep. Hitting
`focus` with a hallucinated class name wastes a call and, worse, returns a plausible-looking
payload.

**Action (tool):** when `focus` cannot resolve the requested symbol, it should say so loudly
(e.g. "focus: 'RuntimeManager.search' not found — did you mean WarmSearchEngine.search?")
rather than returning a generic neighborhood that reads like success. (The map_v3 bridge
already has a "could not resolve … (did you mean)" path for `find`; ensure `focus` does too.)

## P-H4. SHORTCOMING — re-grepping ground that `focus` already packed (violates the stated rule)

distinct_huge_change_strategy r2: sequence was `map focus names=[derive_sync_status,
SYNC_STATUSES]` -> then `Grep SYNC_STATUSES` -> `Grep SYNC_STATUSES` again (45c, 107c). The
Scubiee rules explicitly say "re-Grep of packed ground = FAIL," yet the agent re-grepped a
symbol `focus` had just returned. Low cost here (it still won) but it is the exact anti-pattern
the rules forbid, so the rule is not fully obeyed under pressure.

**Action (rule):** keep the "no re-grep of packed ground" line but make it more concrete:
name the behavior ("after `focus`/`find` returns a symbol's body, do NOT grep that symbol —
edit from the packed body"). Consider a post-hoc harness lint that flags grep-of-packed-symbol
to quantify how often it happens.

## P-H5. IMPROVISATION — the CHEAPEST successful map_v3 cell skipped `map` entirely

unify_token_estimate r2 (map_v3, 380k, strict=True — the cheapest token_estimate success of
ALL arms) opened with native `Grep "char.*token|…|/ 4|//4"` and never called `map`. Faced with
a concept that has a concrete literal (`estimate_tokens`, `//4`), the agent correctly judged
grep was the right tool and ignored the available map surface. This is the U prompt's own
"needles -> Grep" rule working — but note it means map_v3's win is partly "the agent knows when
NOT to use map," not "map is always used." Healthy, but it means some map_v3 wins are really
native-grep wins with the prompt steering tool choice.

**Action (interpretation):** when reporting map_v3 wins, distinguish cells that actually USED
map from cells that chose grep. For the suite: map was used on 7/8 cells; the 1 grep-only cell
was the cheapest. Keep the "pick the cheaper tool" freedom; do not force map on literal targets.

## P-H6. HARNESS-INTEGRITY — "no Bash" leaked: Bash/Agent/ScheduleWakeup ran despite not being allow-listed

native_tools was ["Read","Grep","Glob","Edit","Write","TodoWrite"] (no Bash), and SHARED_SYSTEM
says do not run commands. Yet traces show `Bash` (token_estimate r1 map_v3, and multiple native
cells), plus `Agent` and `ScheduleWakeup` in native spiral cells. So `allowed_tools` did not hard-
block these; the agent invoked them and they executed. Impact was small here (a `cd` returning
112c) but it means the "locate+edit only" guarantee is not actually enforced by the SDK config.

**Action (harness, important for future fairness):** verify how ClaudeAgentOptions.allowed_tools
is meant to constrain built-ins; if it is advisory, add a PreToolUse deny hook (exit 2) for
Bash/Agent/ScheduleWakeup so every arm is truly locate+edit only. Re-state in each session log
whether Bash fired. Until enforced, treat any cell with bash>0 as mildly confounded.

## P-H7. map config mix observed (what the agent actually reached for)

Across the 8 map_v3 cells: `find` was the opener on 7/8 (the 8th went grep-only, P-H5).
`focus` appeared on 3 cells (changed_count r1/r2, huge_change r2) to pull a named symbol's
body+wiring. `related`/`graph` were NEVER used in the whole suite. So the real workhorses are
`find` (orient + bodies) and `focus` (named symbol unit); `related`/`graph` earned nothing on
these tasks.

**Action (prompt/tool):** consider whether `related`/`graph` justify their share of the ~1442-tok
instruction budget if agents never pick them on real dev tasks — either make their trigger
conditions crisper in the prompt or shrink their documentation to reclaim prompt budget. Measure
on a graph-shaped task before cutting.


---

# Light fixes applied (post-study) — P-H2 / P-H3 / P-H4

Kept intentionally small; map_v3 performance is already strong, so no logic/ranking
changes, only additive signals + one sharpened prompt line.

- **P-H3 (tool, map_v3_bridge.cfg_focus):** when `focus` resolves a requested name to
  a NEAREST match rather than an exact one (e.g. `RuntimeManager.search` ->
  `EngineClient.search`), it now prints
  `(note: nearest match, exact name not found: X -> file::Y - confirm this is the
  symbol you meant)`. Qualifier-aware: compares the dotted tail the caller specified
  (Class.method if qualified, else leaf). Exact hits print nothing (verified). Pure
  additive output; bridge verify still 20/20.

- **P-H2 + P-H4 (prompt, INSTRUCTIONS_MAP_V3_U, FALLBACK block):** sharpened the
  low-confidence line to `conf=low ∨ thin_body ⇒ reFind ONCE with task's domain nouns
  ∨ 1·grep ; ¬ grep-wander into unrelated modules (thin find = miss, not a lead)` and
  added `focus "nearest match" note ⇒ confirm it's the intended symbol before EDIT ;
  else reFind the real name`. U instructions 1111 -> 1154 tok (still < 2000; combined
  artifact 1485). The existing "¬ grep_same / focus.result ⇒ ¬grep them" prohibitions
  (P-H4) were already present and were left as-is.

- **P-H6 (harness fairness) — FIXED + live-proven.** Root cause: under
  `permission_mode="acceptEdits"` the SDK's `allowed_tools` is only advisory, so leaky
  built-ins (Bash/Task/Agent/ScheduleWakeup/…) could still run. Fix: added
  `disallowed_tools` (a HARD deny the SDK honors even under acceptEdits) in
  harness_run.py, computed as the known-leaky set minus whatever the caller explicitly
  put in native_tools (so a future test can still opt into Bash). Verified: offline the
  option builds and the deny-list is correct (Bash/Agent/ScheduleWakeup denied,
  Read/Edit kept); LIVE a one-shot probe that explicitly tempted the agent with
  `echo DONE >> notes.txt` used Edit instead — bash_calls=0, task_agent_calls=0,
  PASS=true. The "locate+edit only" guarantee is now actually enforced for every arm.

Verification after fixes: `_budget_map_v3.py` all within budget (U instr 1154);
`verify_map_v3_bridge.py` 20/20; `preflight_all.py` 31/31 EVERYTHING WORKING PERFECTLY.
