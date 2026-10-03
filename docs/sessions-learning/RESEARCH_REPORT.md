# Research report: what to optimize in newmap, its rules, and its instructions

A sessions-grounded study of how a coding agent uses the Scubiee `map` tool, and a concrete
fine-tuning plan. Every claim cites the mined dataset (`data/sessions.jsonl`, 101 cells / 57
runs) via `PATTERNS.md` and `TRAJECTORIES.md`. Nothing here rests on a single run or memory.

---

## 0. The question

Cost of a coding agent ≈ (context carried per model call) × (number of model calls). The goal of
the map tool is to let the agent reach a correct edit in the **fewest model calls**. This report
asks: across every session we have, what actually drives call count up, and what should change in
the tool, the rules, and the instructions to drive it down — without losing correctness.

---

## 1. The central law: cost is call count (r = 0.978)

Correlation of API calls to total tokens, per arm (`TRAJECTORIES.md` §1):

| arm | n | corr(api_calls, tokens) | corr(grep, tokens) |
|---|--:|--:|--:|
| without | 10 | 0.974 | 0.38 |
| mini | 7 | 0.978 | 0.365 |
| mini_v3 | 11 | **0.993** | 0.842 |
| newmap | 8 | 0.987 | -0.121 |
| all dev | 36 | **0.978** | — |

Call count explains ~98% of token variance. **Result size does not** — newmap's result-chars are
tiny (3-14k) yet it was sometimes the priciest arm purely from extra calls. This confirms the #1
rule framing is correct and should stay the top line of both the rules and the instructions.

Two different cost engines sit underneath that law:
- **mini_v3** (old map): corr(grep, tokens) = **0.842** — its cost comes from **grep fallback
  chains** when one map + one whole-file Read doesn't cover the task.
- **newmap**: grep corr is negative (it almost never greps). Its cost comes from **extra `map`
  locate calls** (`refs`/`view` follow-ups after `find`).

So the two arms must be optimized against different failure modes. newmap's lever is "stop calling
`refs`/`view` after `find`"; mini_v3's lever is "stop grepping," which it can't fully fix because
the old map has no way to return multiple precise symbols at once.

---

## 2. The winning trajectory is two moves; the losing one adds a chain

Cheapest vs priciest trajectories, collapsed (`TRAJECTORIES.md` §3):

**mini_v3**
- 147k (win): `map Read Edit`
- 785k (loss-shaped): `map Read Grep*4 Read Grep*2 Skill Glob Grep Read Grep*3 Read Edit*2`

**newmap**
- 122k (win): `map:find Edit`
- 692k (loss-shaped): `map:find map:view Read Skill Edit*6 map:refs*2 map:view Read Bash`

The cheap cells are a clean two-step: locate once, edit. The expensive cells append an
exploration chain — grep for mini_v3, `refs`/`view` for newmap. **The optimization target is the
tail, not the first move.** Every arm's first move is already a single map call; the waste is what
comes after.

---

## 3. newmap's over-ask is concentrated in `refs`/`view` after `find`

Locate calls before the first edit, per newmap cell (`TRAJECTORIES.md` §4). cache_aware edits ~4
symbols; dirty_files edits 1:

| task | run | locate calls | sequence | tokens |
|---|---|--:|---|--:|
| dirty_files | 1921 | 1 | `find` | **122k** |
| dirty_files | 2001 | 1 | `find` | **129k** |
| dirty_files | 1827 | 4 | `find refs refs view` | 255k |
| dirty_files | 1731 | 5 | `find around refs refs refs` | 353k |
| cache_aware | 1955 | 2 | `find view` | **272k** |
| cache_aware | 1818 | 2 | `find view` | 692k |
| cache_aware | 1912 | 4 | `find view view refs` | 547k |
| cache_aware | 1738 | 3 | `find refs open` | 544k |

The pattern is unambiguous: **1 locate call → cheapest; each extra locate call adds ~100-130k.**
On `dirty_files` (a 1-symbol edit) the agent sometimes made **5** locate calls. That is pure
over-ask: a one-symbol change needs one `find`.

Two root causes, both fixable:
1. **`refs` reflex after `find`.** `refs` is the most-used config (9 calls vs 8 finds) and most
   of those are "get the callers to be thorough" after `find` already returned connections (P4).
2. **Deprecated aliases still fire.** Trajectories show `map:open` and `map:around` — the agent
   reached for the old 5-config names. The consolidation to 3 isn't fully landing in the agent's
   head, so it treats "look around" as a distinct tool.

---

## 4. Grep fallback is mini_v3's tax — and newmap already avoids it

Grep-fallback incidence and penalty (`TRAJECTORIES.md` §2):

| arm | fell back to grep | mean tok w/ grep | mean tok no grep |
|---|--:|--:|--:|
| mini_v3 | 6/11 | 439k | 281k |
| newmap | 2/8 | 304k | 384k |

mini_v3 greps in over half its cells, paying a **~158k penalty** when it does. This is the old
map's structural weakness: a whole-file Read gives the agent one file, and the moment the task
needs a second symbol or file it greps. newmap's `find` returning the clustered region is exactly
the fix — and newmap's grep rate is already low. **Do not add grep affordances to newmap;** its
near-zero grep rate is a feature.

---

## 5. Confound to control: Skill-call noise

The cache_aware task asks for pricing math, so the agent calls the `claude-api` Skill (5/11
mini_v3, 2/8 newmap cells; `TRAJECTORIES.md` §5). Those calls inflate tokens in **both** arms and
are not a map signal. Future arm comparisons should either strip the pricing sub-question or note
Skill calls separately, so they don't muddy the newmap-vs-mini_v3 token delta.

---

## 6. What to optimize — prioritized

### Tool (`cfg_find` / bridge)
- **T1 (done, keep).** `find` returns all clustered symbol bodies in one call. This is the single
  change that flipped newmap from losing to winning (P2) — it attacks the §3 root cause directly.
- **T2 (do).** Make the deprecated aliases **loud**: when the agent calls config `open`/`around`/
  `outline`, prepend a one-line notice to the result: "note: `open`/`around` are folded into
  `view`/`refs`; prefer those." Addresses §3 cause #2 without breaking the aliases.
- **T3 (do).** In `find`'s connections block, when connections are present, end with an explicit
  "— you already have callers/callees; a `refs` call for wiring is NOT needed —" line. Addresses
  §3 cause #1 at the point of temptation (the result the agent is reading).
- **T4 (consider, measure first).** `find` could accept `scope` already; add a cheap hint when
  the top hits span **multiple files** (a true multi-file change) vs one file, so the agent knows
  whether one `find` covered everything. Only build if §3 recurs on a multi-file task.

### Rules (`RULES_CONFIGS`, <300 tokens)
- **R1 (keep).** "#1 GOAL: fewest calls; cost ≈ context × calls." Confirmed by §1 (r=0.978).
- **R2 (tighten).** Add a hard numeric anchor: "A 1-symbol edit needs exactly ONE find. A
  multi-symbol edit in one file needs ONE find (it returns them all). Only a genuinely multi-file
  change may need a second locate call." §3 shows the agent made up to 5 locate calls on a
  1-symbol task; a concrete count is stickier than "fewest."

### Instructions (`INSTRUCTIONS_CONFIGS`, <2000 tokens)
- **I1 (done this cycle).** Named the refs-after-find trap in the bad-trajectory list and in the
  `refs` how-to. §4/P4 justify it.
- **I2 (do).** Add the 3-config consolidation note so the agent stops reaching for `open`/`around`:
  one line — "there are exactly THREE configs: find, refs, view. `open`/`outline`/`around` are old
  names; use view/refs." Addresses §3 cause #2 in the instruction the agent reads before acting.
- **I3 (do).** Replace the generic "stop and edit as soon as you can" with the §3 count anchor so
  rules and instructions agree.

### Measurement / methodology
- **M1.** Retire the `mini` arm (strictly dominated, P5). Baseline newmap against `mini_v3` only.
- **M2.** Re-run both tasks at **n≥3** — all current wins are n=1 and mini_v3's variance is large
  (§3: 147k-785k on the same task). The newmap win is directional until repeated.
- **M3.** Add a **multi-file** task (edit spanning 2+ files) — the current tasks are 1-file, so
  they can't exercise whether one `find` covers a multi-file change (T4's open question).
- **M4.** Separate Skill-call tokens in the report (§5) so they don't distort the delta.

---

## 7. Expected effect

If T2/T3 + I2/I3 + R2 land, the §3 table predicts the losing newmap cells (2-5 locate calls)
collapse toward 1-2, i.e. ~100-250k saved per hard-task cell, closing the remaining gap and
turning the n=1 wins into a stable margin. Correctness is not at risk: the winning cells already
reach oracle 1.0 with the two-move trajectory; we are removing the exploration tail, not the
discovery step.

The one thing this study cannot yet answer is the multi-file case (M3/T4). Until a multi-file task
is run, "one find covers the whole region" is proven only for single-file clusters.
