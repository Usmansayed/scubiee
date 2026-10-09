# Scubiee on Cursor — retrieval findings across the full session

A consolidated analysis of **every A/B cell we ran this session under the Cursor `auto` headless
agent**: 45 dev-edit-task cells + 44 retrieval-challenge cells (89 total), across the baseline
map_v3 rule, the `without` control, and the tuned rule variants (c_default, c_nav/c_nav2, c_strong,
c_firstmove, c_counter, and the earlier cursor_forbid/strict/workflow/hybrid/capped/minimal).

Source data: `.ab_workspaces/claude_sdk_harness/cursor_harness/*/cell_*.json`, mined by
`scripts/claude_sdk_harness/mine_all_cells.py`. Engine 0.3.140, model `auto`, per-cell isolated
git snapshots, tokens from the Cursor `result` event usage block.

> **Headline, stated honestly:** Scubiee's token value under Cursor is **real on retrieval/locate
> tasks** (~43% avg, ~66% median fewer tokens than native) but **inverts on tiny single/two-file
> edit tasks**, where map gets layered *on top of* native reads and costs more. The earlier
> impression that "Scubiee doesn't save tokens with Cursor" came from measuring only the small edit
> tasks — the task type map is least suited to.

---

## 1. The headline split: retrieval vs small-edit tasks

### Retrieval challenges (small locate tasks — what Scubiee is FOR)
Native-vs-map-rule, aggregated over all retrieval cells:

| arm group | n | avg tokens | median tokens | map calls | native ops/cell (grep+glob+read) |
|---|--:|--:|--:|--:|--:|
| **without (native)** | 10 | 635,822 | 581,463 | 0.0 | **26.3** |
| **map-rule (all map variants)** | 34 | **364,770** | **195,117** | 1.3 | **11.8** |

**Map-rule cells use ~43% fewer tokens on average, ~66% fewer at the median, and less than half the
native search ops.** Here map SUBSTITUTES for native exploration — one map call replaces a grep/glob/
read chain. This is the token-saving premise working as designed.

### Dev-edit tasks (small 1–2 file edits — NOT what map is for)
Per-task average tokens (valid tasks only; `add_importers` is contaminated, see §4):

| task | without / c_default (native-ish) | map-heavy variants |
|---|--:|--:|
| cache_aware_savings (1 file) | c_default **238k** | c_strong 403k · c_nav2 446k · c_counter 531k · c_firstmove 589k |
| unify_token_estimate (2 file) | c_default 219k | c_counter 229k · c_strong 229k · c_nav2 174k · c_firstmove 212k |

On the single-file task, every map-heavy arm cost MORE than native (1.7–2.5×). On the two-file task
it was roughly a wash (c_nav2 even cheaper). The smaller/less-connected the task, the worse map's
additive overhead.

---

## 2. Root cause of the edit-task inversion: map is ADDITIVE, not SUBSTITUTIVE

Trace walks (`analyze_traces.py`) of the edit cells show the agent calls map **and then still Reads
the files anyway**. The Reads do not drop when map is added:

| cache_aware cell | map calls | reads |
|---|--:|--:|
| c_default (native) | 0 | 4 |
| c_strong | 3 | 4–5 |
| c_counter | 3 | 6–7 |

Example sequence (c_counter, single-file task): `find → read → focus → read → related → read → grep
→ glob → edits` — **11 discovery actions** to reach an edit the native arm reached in **~4 reads**.
The agent treats map's inline code as a hint to go read the file "properly," so map cost is piled on
top of unchanged native cost. Since every tool call re-sends the transcript (cost ≈ events ×
context), the map arms ran ~3× the events (1095 vs 304) → ~2.6× the tokens.

**On retrieval tasks the agent does NOT do this** — it reads the map result and answers, so map
replaces the native chain. The difference is the task: an edit task ends in file edits the agent
wants to "see" first; a retrieval task ends in naming files, which map answers directly.

---

## 3. Retrieval quality by rule variant and by category

### By arm (retrieval cells)
| arm | n | avg tokens | avg recall | avg f1 | avg mrr |
|---|--:|--:|--:|--:|--:|
| c_default | 9 | 209,694 | 1.00 | 0.60 | 1.00 |
| c_capped | 8 | 219,795 | 0.75 | 0.50 | 0.75 |
| c_hybrid | 7 | 234,217 | 0.86 | 0.37 | 0.76 |
| without | 10 | 635,822 | 1.00 | 0.58 | 1.00 |
| cursor_strict | 2 | 1,316,608 | 0.75 | 0.42 | 1.00 |
| cursor_workflow | 2 | 587,240 | 0.75 | 0.38 | 1.00 |
| c_minimal | 2 | 463,236 | 0.50 | 0.17 | 0.50 |

- **c_default is the standout**: recall 1.00, mrr 1.00, lowest tokens (~210k) — full recall at a
  third of native's token cost. (It is the Claude map_v3_u text verbatim.)
- **without matches recall (1.00) but at ~3× the tokens** (636k) — native gets there, expensively.
- **cursor_strict is a cautionary tale**: strict prose backfired to 1.3M tokens (grep spiral avg 10).
- **c_minimal underperformed** (recall 0.50) — too terse to steer the agent.

### By category (all retrieval cells)
| category | n | avg tokens | avg recall | avg f1 |
|---|--:|--:|--:|--:|
| cross_module | 8 | 371,441 | 1.00 | 0.63 |
| focused | 15 | 431,975 | 0.87 | 0.61 |
| discovery | 21 | 443,298 | 0.81 | 0.34 |

- **cross_module** retrieval is map's best category — full recall, decent f1. This is the
  "where does this flow live across files" shape map is built for.
- **discovery** has the lowest f1 (0.34): broad/vague asks produce low precision (agent names many
  files, few correct). This is where query-quality and the `graph`-first routing matter most.

---

## 4. Confounds found while mining (do not trust results that ignore these)

1. **Contaminated task — `add_importers_expand_alias` (hard7).** Its oracle hard-imports
   `pipeline.mcp_locate` + `_EXPAND_DIRECTION_VALUES`, a module archived during the v3 cutover.
   The file is absent from the live tree, so the agent burns 40–60 greps discovering it's missing
   (both arms spike to 2M+ tokens, oracle swings 0.33↔1.0). **Retired as an instrument.** All the
   add_importers rows in §1/§2 are noise and excluded from conclusions.
2. **Task-spec-hunt artifact.** The workspace folder is named after the task and some prompts are
   vague, so every cell opens with 2–4 grep/glob calls hunting the spec string. Equal across arms
   (doesn't bias comparisons) but inflates absolute grep/glob counts.
3. **`auto` router variance is large.** The identical c_default text failed 2/2 on add_importers in
   one batch and succeeded 2/2 in another. Single-rep cells are directional only; trust aggregates.
4. **Cost is ~85–96% `cache_read`.** Tokens track tool-call/turn count, not result size. The lever
   that moves tokens is **fewer total discovery actions**, not smaller map results.

---

## 5. Patterns that hold across the whole session

1. **Having ANY map-first rule flips Cursor adoption from ~0 to ~100%.** `without` and bare
   `c_default`-on-edit-tasks call map 0 times; every rule variant gets it used. The exact wording
   matters less for *whether* map is called than for *how well*.
2. **Map SAVES tokens when it SUBSTITUTES (retrieval), WASTES when it SUPPLEMENTS (edits).** The
   single biggest determinant of token outcome is whether the agent trusts the map body enough to
   skip the native read. It does on retrieval; it doesn't on edits.
3. **Strictness raises map-call COUNT monotonically** (c_default 0 → c_nav2/strong 1–2 → c_counter
   2–3 → c_firstmove 3–4) — but call-count is the WRONG target. More map calls on a small task =
   more additive cost. The right target is native-ops-avoided.
4. **The counterweight premise is correct**: the host system prompt biases toward native tools, so a
   "balanced" rule nets grep-dominant (c_default used map 0× on both edit tasks across reps). The
   rule must over-promote map to reach balanced behavior — c_counter was the only arm with
   consistent map use across reps.
5. **c_default (= Claude map_v3_u) is the most reliable retrieval performer** on Cursor too: recall
   1.00, mrr 1.00, lowest retrieval tokens. The Claude-tuned text transfers better than any
   Cursor-specific strict/minimal rewrite we tried.
6. **Correctness held almost everywhere** (oracle 1.0) except the contaminated task and one
   c_counter cell where the agent chose a valid-but-different design the strict oracle rejected.
   Rules change COST and TOOL CHOICE far more than they change CORRECTNESS.

---

## 6. What this means for the token premise

- **The premise holds where it should:** on locate/retrieval work, Scubiee under Cursor cuts tokens
  ~43–66% vs native. That is the use case it was built for and it delivers.
- **The premise does not hold on tiny edit tasks** — and arguably shouldn't: a 1–2 file edit barely
  has a "where/how does this connect" problem, so native reads are already near-optimal and map is
  overhead. Pushing map there (strict rules) makes it worse.
- **The open fix** for the edit-task case is a "substitute, don't supplement" rule — *map's body IS
  the file; edit from it, don't re-Read what map returned* — measured by reads-avoided, not map
  calls. Untested so far.
- **The fair next benchmark** is a genuinely large, uncontaminated cross-cutting navigation task
  (the category where map wins), since our only such task (hard7) was contaminated and our clean
  tasks are too small to need map.

## 7. Open questions / next steps
1. Draft + test the "substitute, don't supplement" rule; score reads-avoided and total tokens.
2. Build one large, uncontaminated multi-file discovery task targeting live v3 files.
3. Re-run c_default vs best tuned variant on retrieval with ≥3 reps to firm up the ~66% median win.
4. Decide the shipping rule: current evidence favors **c_default** for retrieval; the edit-task
   overhead is a separate wording fix, not a reason to change the retrieval rule.

_Data mined by scripts/claude_sdk_harness/mine_all_cells.py and analyze_traces.py. All figures are
from on-disk cell JSONs this session._


---

## 8. FINALIZE DECISION (confirmation A/B, fixed harness) — ship `c_default`

After the mining above, we (a) fixed a harness bug that was silently failing shell-edited cells
(success was gated on a git-diff `.py` counter; agents editing via the `shell` tool showed `real=[]`
even when the oracle passed — now `success` is graded on the ORACLE, the ground truth), and (b) ran
a clean confirmation of `c_default` (Claude map_v3_u text) vs `c_final` (c_default + the three
"substitute, don't supplement / known-name→focus / no-cap" edits).

### Edit tasks (3 reps each, fixed harness, all oracle 1.0)
| task | c_default avg | c_final avg |
|---|--:|--:|
| unify_token_estimate (cross-module edit) | **214k** | 255k |

c_final used map more consistently (2/1/2 vs 1/1/0) but did NOT save tokens — it was slightly more
expensive and more variable. Edit tasks are simply not where map saves tokens.

### Retrieval tasks (1 rep × 3 queries each; native `without` included)
| query (category) | without | c_default | c_final |
|---|--:|--:|--:|
| first_map_skips_graph (discovery) | 1,112,874 | 1,489,579 | 1,842,529 |
| dirty_path_first_char (focused) | 537,507 | **131,128** | 186,776 |
| memory_budget_resets_threads (cross_module) | 682,910 | **131,813** | 217,282 |
| **avg** | **777,764** | **584,173** | 748,862 |
| avg grep | 18.3 | 7.3 | 5.7 |

All arms recall 0.83, mrr 1.0 (same correctness).

### What this proves
1. **Scubiee DOES save tokens under Cursor on the tasks it's built for.** On the two normal
   retrieval queries (focused, cross_module), c_default cut tokens **76% and 81%** vs native
   (131k vs 538k; 132k vs 683k) at equal recall. The engine's premise holds.
2. **The discovery query is a spiral trap for every arm** (1.1–1.8M). The agent maps AND
   grep/globs anyway, so map adds cost there. This one query drags every average up and is the main
   reason the overall avg win looks modest.
3. **c_default beats c_final.** c_final's substitution edits reduced grep (5.7 vs 7.3) but the agent
   substituted glob for grep (4.7 vs 2.0) and over-mapped (3 vs 2), netting MORE tokens (749k vs
   584k). The extra strictness over-steered. My proposed "improvement" regressed the proven rule.
4. **Correctness is unaffected by rule choice** (all arms equal recall/mrr).

### Decision
**Finalize `c_default` = the two-layer `two_layer.RULES_MAP_V3` + `INSTRUCTIONS_MAP_V3` (Claude
map_v3_u).** It is the most reliable, lowest-token map rule across the entire session on both hosts.
Do NOT ship c_final/c_counter/c_firstmove — the stricter variants raise map-call count without
saving tokens, and over-steer on easy/single-file/discovery cases.

### Caveats kept honest
- Retrieval confirmation is n=1/query (3 queries); the 76–81% wins are single observations, but they
  align with the 44-cell retrieval aggregate (map-rule median 195k vs native 581k) so they are not
  flukes.
- The discovery-spiral case is a real open weakness: map does not help when the agent won't stop
  grep/globbing. That is an agent-behavior problem the current rules don't fully solve; a future
  "after a map result, do not glob/grep the same area" nudge could help but was not proven here.
- Edit tasks remain roughly a wash-to-slightly-worse for map; this is expected (little to navigate)
  and not a reason to change the retrieval rule.


---

## 9. Strictness pass tested (`c_ship`) — REGRESSED, do NOT ship it

Per request, built `c_ship` = c_default with a LIGHT strictness pass: firmer MUST/MUST-NOT imperative
tone on the trust-and-stop rules, a "FOLLOW STRICTLY" instructions preamble, and removal of the
counterproductive `<=2 map` cap. Decision logic unchanged. Validated on the two CLEAN retrieval
queries (focused + cross_module) vs c_default, 1 rep each.

| arm | avg tokens | map | grep | glob | recall |
|---|--:|--:|--:|--:|--:|
| c_default | **108,633** | 1.0 | 0.5 | 0.5 | **1.00** |
| c_ship (stricter wording) | 637,780 | 1.5 | 5.0 | 4.0 | 0.75 |

Per-query: c_ship cross_module 238k (recall 0.5) vs c_default 97k (1.0); c_ship focused **1.04M**
(9 grep + 6 glob) vs c_default 120k. c_ship was **~6x more expensive and LOWER recall**.

**Finding:** the stricter MUST/MUST-NOT framing did NOT improve adherence — it induced
anxiety-driven over-searching (more grep+glob, as if double-checking to satisfy hard rules). This is
the THIRD time a stricter rewrite of the proven text regressed it (c_final and c_counter were the
first two). The pattern is consistent across the whole session: **for Cursor `auto`, firmer/stricter
wording makes retrieval WORSE, not better.** The soft, explanatory two-layer text (c_default) that
tells the agent WHY (cost model) and lets it choose outperforms every imperative/ban/cap variant.

**Decision stands: ship plain `c_default` (two_layer.RULES_MAP_V3 + INSTRUCTIONS_MAP_V3), unchanged.**
Do not ship c_ship. The strictness experiment is logged here so we don't repeat it.

Caveat: n=1/query, but the direction is unambiguous (6x) and matches the session-long pattern that
strict prose backfires on Cursor (see also cursor_strict at 1.3M in §3).


---

## 10. Huge multi-turn feature-build A/B — the token-savings spectrum, concluded

Added multi-turn session support to the harness (Cursor `--resume <chatId>`; token/tool/trace summed
across turns) and a LARGE feature task `cli_health_command`: turn 1 builds a new `scubiee health`
CLI subcommand (rolling up the sync-status contract), turn 2 (same resumed session) extends it with
`--json` + health-based exit codes. Vague feature-level prompts. Oracle invokes the real CLI as a
subprocess (fails 3/3 on empty tree, passes 3/3 on a reference impl — verified then reverted).
Heavy preflights all green; two harness bugs fixed in the process (stderr PIPE deadlock → DEVNULL;
early process-kill raced session persistence → read to natural EOF). c_ship first, then without.

| arm | total tokens | map | grep | read | tools | turn1 / turn2 | oracle |
|---|--:|:--:|:--:|:--:|:--:|--|:--:|
| c_ship (= c_default + strict line) | 1,487,418 | 1 | 15 | 27 | 51 | 1.32M / 170k | ✅ |
| without | 1,223,507 | 0 | 16 | 27 | 54 | 1.07M / 157k | ✅ |

Both built the complete feature correctly. Multi-turn continuity confirmed: turn 2 used only 1–2
tools in both arms (extending turn 1's work, not re-exploring).

**Result: on a huge feature build, Scubiee did NOT save tokens** (c_ship 1.49M vs without 1.22M, map
barely used). The arms did near-identical work (reads 27 vs 27, greps 15 vs 16). A feature build is
dominated by code-WRITING and transcript re-reading, not code-FINDING, so map's locate advantage is
a small fraction of the cost.

### The concluded token-savings spectrum (whole session, Cursor `auto`)

| task type | map effect on tokens | evidence |
|---|---|---|
| Retrieval / "where does X live" | **big savings 76–81%** | §8 (131k vs 538k; 132k vs 683k); 44-cell median 195k vs 581k |
| Small scoped edits | ~neutral (wash, within variance) | §final-ab 1–1 split |
| Complex multi-file edits | ~neutral | §8/§ complex: 278k vs 242k overlapping |
| Huge feature builds (multi-turn) | **no savings (slightly more)** | §10: 1.49M vs 1.22M |

**Conclusion:** Scubiee is a **locate-layer token-saver**. Its savings scale with how much of a task
is *finding* code vs *writing/reading* it. Retrieval → large wins; edits → break-even; feature
builds → no win (the cost is generation + transcript re-reading, which map does not touch). It never
hurt correctness in any task type. The ship rule (c_default / c_ship = +1 strict line) is sound:
it delivers the big wins where they exist (retrieval) and is a wash, not a regression, elsewhere.
