# New map tuned for fewest API calls: arm re-test

After the previous arm test showed the token gap was entirely extra API calls (not bigger results), two changes were made with "fewest calls" as the #1 goal:

1. **`find` now returns connections inline.** On high confidence, after the top result's code, it appends a compact block: the symbol's callers and same-file callees. So one `find` answers "where AND how it's wired" — removing the agent's reason to then call `refs`/`view`.
2. **Rules rewritten with fewest-calls as goal #1.** "One find is normally the whole discovery step; at most ONE follow-up before you edit." RULES 290 tokens, INSTRUCTIONS 1481.

All gates re-verified green before the run (battery 24/24, SDK preflight 11/11).

## Results (vs the prior tuning)

| Task | Arm | tokens | API calls | map calls | pass | prev newmap |
|---|---|---:|---:|---:|:--:|---|
| dirty_files_cap (keyword, 1 file) | mini_v3 | 147,004 | 5 | 1 | yes | — |
| dirty_files_cap | **newmap** | **122,271** | **4** | **1** | yes | was 255k / 8 calls |
| cache_aware_savings (multi-module) | mini_v3 | 318,481 | 9 | 1 | yes | — |
| cache_aware_savings | newmap | 546,890 | 14 | 4 | yes | was 692k / 17 calls |

Both arms 4/4 correct.

## What moved

**Keyword task: newmap now WINS.** 122k vs mini_v3's 147k, with ONE map call and 4 API calls — down from 255k / 8 calls in the prior run. The agent did `find` (got code + connections) and edited. First token win for the new map, and it's the clean case the design targets.

**Multi-module task: newmap improved but still costs more.** 547k vs 692k before (5 map calls -> 4), but mini_v3 did it in 1 map / 9 calls. newmap's 4 calls were: `find` -> `view` outline -> `view` [token_meter.py:1-65 + more] -> `refs` [compare_queries, ArmResult, QueryCompare, baseline_grep_read].

That is NOT aimless exploration. This task's correct fix edits four symbols (a dataclass, its pricing, and two functions). newmap read each one before editing. mini_v3 did one map, took the inline body, and edited largely from that single read — which is exactly why in an earlier run mini_v3 **failed this task (oracle 0.33)**. The extra calls buy a complete, correct understanding of a genuinely multi-symbol change.

## Honest standing

- **Fewest-calls tuning worked where it should.** On the single-symbol task the agent now reaches the edit in one map call and beats the old map on tokens.
- **On a genuinely 4-symbol task, 4 locate calls is close to the real floor.** You cannot edit 4 symbols correctly from 1 locate call without reading them; mini_v3's 1-call approach is cheaper precisely because it edits with less understanding, and that has failed the task before.
- **Payload is still tiny** (newmap result-chars 13.9k on the hard task), confirming the cost is calls, and calls now track the number of symbols the edit touches — which is the irreducible part.

So the lever is working: discovery calls dropped from 5->1 on the easy task and 5->4 on the hard one. The remaining hard-task gap is the agent correctly reading the four symbols it must change, not waste.

## What's left to settle (needs n>=3)

- n=1 still: mini_v3 swung 318k-998k on the hard task across runs. The newmap-vs-mini_v3 hard-task comparison needs repeats before calling it.
- The decisive test is a task where mini_v3's 1-call edit **fails** (as it did at 0.33 before) while newmap's few-call understanding passes — then the extra calls are clearly worth it. The current tasks are ones mini_v3 can sometimes do in one shot.

## Files
- find connections: `_append_connections` in `map_v2_bridge.py`
- rules: `two_layer.py` RULES_CONFIGS / INSTRUCTIONS_CONFIGS (290 / 1481), arm `policies.RULES['configs']`
- run dirs: latest `*_devmini_cache_aware_savings`, `*_devmini_dirty_files_cap`

---

# Update: multi-body `find` closes the hard-task gap (newmap now wins both)

The prior "find returns the top symbol body (+ connections)" still cost extra calls on the 4-symbol task because the agent had to `view`/`refs` the *other* symbols. The deeper reading of that run: the old map accidentally won by returning a whole-file null-symbol card, so the agent read the file once and edited; the new `find` returned a precise 36-line span, which is tighter but forced follow-ups to see the rest of the region.

Acting on the stated principle — **one big response beats forcing follow-up calls** — `find` was changed to return **every clustered relevant symbol body in one call**: when the top in-scope hits share one file, it packs all of their bodies (not just the top one), with a per-body cap that shares the budget. `find` budget raised to 14000, `view` 12000, `BODY_CAP` 5000. Rules/instructions updated to describe multi-body find (RULES_CONFIGS 296, INSTRUCTIONS_CONFIGS 1553). Battery re-passes 24/24.

Verified on disk: for the hard-task query, `find` now returns 3 clustered `token_meter.py` bodies (`compare_queries`, `QueryCompare.tokens_saved`, `QueryCompare.pct_saved`) in one 3.7k-char response headed `-- bodies: 3 relevant symbols ... (edit from these; no follow-up needed) --`.

## Results (fresh runs against the current bridge)

| Task | Arm | tokens | API calls | map calls | grep | pass |
|---|---|---:|---:|---:|---:|:--:|
| dirty_files_cap (keyword, 1 file) | mini_v3 | 147,465 | 5 | 1 | 0 | yes |
| dirty_files_cap | **newmap** | **128,712** | **4** | 1 | 0 | yes |
| cache_aware_savings (multi-module, 4 symbols) | mini_v3 | 404,813 | 11 | 1 | 2 | yes |
| cache_aware_savings | **newmap** | **271,702** | **7** | 2 | 0 | yes |

Both arms 4/4 correct (oracle 1.0 on every cell).

## What moved

**Hard task flipped — newmap now WINS.** 272k vs mini_v3's 405k (33% cheaper), 7 calls vs 11. Trace: `find` (returned the 3 clustered bodies) -> one `view` (imports lines 1-66 + `context_engine_arm`) -> 3 Edits. The extra `view` outline + `refs` calls from the prior run are gone; `find` handed over the whole relevant region at once, dropping map calls 4->2 and total calls 14->7.

Note mini_v3 was noisier this run (405k / 11 calls, with 2 greps) than its best prior run (318k / 9) — consistent with its known high variance. newmap's run was both cheaper and tighter.

**Easy task — newmap still wins, no regression.** 129k vs 147k, 4 calls vs 5, one map call each.

## Standing

- The fewest-calls goal is met on both tasks: newmap reaches a correct edit in fewer API calls and fewer tokens than the old single-tool map, on the easy single-symbol task AND the hard 4-symbol task.
- The mechanism is exactly the stated principle: `find` spends a few k characters once to return all the clustered bodies, which saves the follow-up locate calls that would otherwise re-pay ~35k of cached context every later turn.
- Still n=1 per cell; mini_v3's variance means the hard-task margin should be confirmed with repeats, but the direction is now a clean win rather than a loss.

## Files / run dirs
- multi-body find: `cfg_find` in `map_v2_bridge.py` (cluster = top in-scope hits sharing the top file; per-body budget share)
- rules: `two_layer.py` RULES_CONFIGS / INSTRUCTIONS_CONFIGS (296 / 1553)
- run dirs: `20261001T195500Z_devmini_cache_aware_savings`, `20261001T200122Z_devmini_dirty_files_cap`

---

# Update: post-tuning arm test (all 4 preflight gates green) — mixed, with a clear confound

After applying the research-report tuning (T2 alias notices, T3 "don't call refs after find" nudge
in the connections block, R2 locate-call count anchor in rules, I2 three-config note, I3 count
paragraph in instructions), all four preflight gates passed first: token budgets (295/1765),
battery 24/24, SDK preflight ok (config_enum=[find,refs,view], find 9219 chars), both dev-task
preflights, and a live Claude probe (ok:true, all 3 configs usable, 0 trace errors). Then the arm
test ran clean.

## Results

| Task | Arm | tokens | API calls | map | grep | pass |
|---|---|---:|---:|---:|---:|:--:|
| cache_aware_savings | mini_v3 | 328,086 | 9 | 1 | 0 | yes |
| cache_aware_savings | newmap | 765,982 | 17 | 3 | 2 | yes |
| dirty_files_cap | mini_v3 | 248,622 | 8 | 1 | 2 | yes |
| dirty_files_cap | newmap | 221,315 | 7 | 4 | 0 | yes |

Both arms 4/4 correct (oracle 1.0). But newmap **lost the hard task badly** (766k vs 328k) and
won the easy task only narrowly — the opposite of the clean win in the prior run (272k/7). This is
honest: a single clean win did not reproduce. Two causes, both diagnosed from the traces.

## Cause 1 (hard task): the pricing Skill rabbit hole, not the map

newmap's hard-task trajectory was: `find` (got the bodies) -> `view` -> **`Skill` claude-api ->
Grep -> Grep -> Read -> Read** -> `refs callers` -> 7 Edits. Calls #3-7 were the agent chasing the
task's **prompt-caching pricing sub-question** (`cache_read|cache_discount|cache_multiplier`), not
locating code. This is exactly the Skill-noise confound flagged in the research report (§5 / M4):
the cache_aware task asks for pricing math, so the agent sometimes goes down a pricing research
chain that has nothing to do with map. mini_v3 skipped it this run purely by variance. **The map
tool worked** — one find, one view, one refs. The 400k+ tail was pricing research.

## Cause 2 (easy task): the refs-after-find reflex still fires

newmap's easy-task trajectory: `find` -> `refs callers` -> `refs callers` (scoped retry) ->
`refs uses` -> 1 Edit. **Three refs calls after find, on a ONE-symbol change.** The T3 nudge
("you already have the wiring — do NOT call refs for callers/callees") and the R2/I2 count anchor
did NOT suppress it. The agent even retried `refs callers` with a scoped name, suggesting it did
not trust / notice the connections `find` already returned. newmap won the token count only because
mini_v3 happened to grep-fall-back (2 greps) that run.

## What this means

- **The map itself is sound** (gates + probe + find/view/refs all correct). The losses are agent
  behavior around it, not tool breakage.
- **n=1 is not decisive here.** Across all matched pairs now (10): newmap cheaper in **4/10**, and
  find-alone-sufficed in only **2/10**. The clean 2-move win is real but not yet the common case.
- The two open levers from the report are now **empirically confirmed as the blockers**:
  - **M4 (confound):** the pricing Skill chain dominates the hard task's tokens and must be
    separated or removed before the hard-task delta means anything.
  - **refs-after-find:** instruction nudges alone did not stop it; the next lever is structural —
    make `find` surface callers so prominently (or label them "callers (complete)") that the agent
    stops re-asking, and/or run the comparison on a task without a research sub-question.

## Honest standing

Correctness is solid (100%). On cost, the tuning did not deliver a reproducible newmap win this
round. The dominant hard-task cost is a task-design confound (pricing research), and the residual
easy-task waste is a refs reflex the instructions haven't fully suppressed. Next steps are M4
(strip the pricing sub-question or score Skill tokens separately) and a stronger structural signal
on find's callers — then re-run at n≥3. Run dirs: `20261001T204350Z_devmini_cache_aware_savings`,
`20261001T205*_devmini_dirty_files_cap`.
