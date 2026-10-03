# Map-only rules & instructions — sentence-by-sentence rationale, backed by session evidence

This documents the two map-only rule sets we built (STRICT and GUIDED), explains **why each
sentence exists**, and backs each design choice with evidence from the actual A/B sessions.

**Honesty up front about how "perfected" these are.** The rules were iterated across three
versions — **flexible → strict → guided** — each revision driven by reading the previous run's
tool-call trace. That iteration is real. What is *not* yet done is statistical proof: every arm is
**n = 1**, and the task's run-to-run token variance is large (the "without" arm alone swung
0.86M → 1.42M on the identical task). So below, each rationale is tagged:
- **[PROVEN]** — directly observed in a trace, reproduced across runs.
- **[EVIDENCE]** — observed in a trace but on one/few runs (directional, not statistically firm).
- **[DESIGN]** — a logical choice to prevent an observed failure mode, not yet independently measured.

---

## 0. The evidence base (what the sessions actually showed)

Tool-call traces from `analyze_sessions.py` over the recorded runs:

| Run | rule | map calls | grep/glob | turns | tokens | outcome |
|---|---|---:|---:|---:|---:|---|
| 3-arm small | flexible | 2 | 2 | ~few | 0.77M | pass; map→read→stop |
| big task | flexible | 2 | 31 | 112 | 15.4M | pass; mapped once then grep-walked |
| small strict | strict | 2 | 7 | 25 | 1.13M | **fail (0.33)** |
| small guided | guided | 1 | 12 | 28 | 1.25M | pass |
| 4-arm: without | — | 0 | 0 | 30 | 1.25M | pass |
| 4-arm: flexible | flexible | 2 | 8 | 27 | 1.15M | **fail (0.33)** |
| 4-arm: strict | strict | 3 | 15 | 34 | 1.28M | pass |
| 4-arm: guided | guided | 1 | 7 | 20 | 0.83M | pass |
| gVs: guided | guided | 1 | 5 | 21 | 1.00M | **fail (0.33)** |
| gVs: strict | strict | 2 | 4 | 24 | 1.12M | pass |

**Three findings these traces establish, which every rule sentence is built on:**

1. **[PROVEN] Token cost tracks TURNS, not tool choice.** Total tokens are ~90%+ cache-read, which
   is the transcript re-sent each turn. Across all runs, tokens rank-correlate with `turns`, not
   with map/grep counts. → *A rule helps on cost only if it reduces turns-to-edit.*
2. **[PROVEN] The winning map pattern is `map → read the returned loc spans → stop`; the losing one
   is `map once → grep-walk anyway`.** The 3-arm win (0.77M, 2 grep) vs the big-task tie (15.4M, 31
   grep) is the same rule producing opposite results purely by whether the agent grepped after
   mapping.
3. **[EVIDENCE] Forcing more map calls does not reduce turns — it can increase them.** Strict
   averaged the *most* turns (25/34/24) and the most grep in the 4-arm run (15); it made the agent
   map *and* grep. Guided averaged the *fewest* turns (28/20/21) with the fewest map calls (1).

---

## 1. STRICT rule — sentence-by-sentence

> **"A managed Scubiee context system is available. For finding code you may use ONLY the Scubiee
> `map` tool (with `gate`/`status` for health). You may NOT use any other Scubiee tool."**

- **Why:** states the map-only surface plainly. **[DESIGN]** mirrors the product GATE's opening so
  the agent treats it as a real policy, not a hint. `gate`/`status` are allowed because they're
  health checks with ~0 token cost and no discovery value to abuse.

> **"You MUST follow this discovery protocol. It is not optional."**

- **Why:** **[DESIGN]** the flexible rule's soft phrasing ("prefer map over grep") was ignored on
  the big task (31 greps). Hard language was an attempt to make the agent actually change behavior.
  **Verdict from data:** this backfired — see §3. Hard-forcing changed behavior but not for the
  better.

> **"1. MAP FIRST, ALWAYS … you MUST call `map` first … This applies to EVERY new sub-question …
> If you move to a new area … `map` that area before touching it."**

- **Why written:** **[EVIDENCE]** directly targets the big-task failure where the agent mapped once
  (position 2 of 111 calls) then never mapped again while grep-walking 30+ times. The intent was
  "re-map instead of grep for each new sub-question."
- **What the data said:** this is the sentence that **hurt**. In the 4-arm run strict did 3 maps
  AND 15 greps and 34 turns (the most of any arm). Forcing a map per sub-question added map calls
  *on top of* the greps rather than replacing them, and each extra map+read is an extra turn →
  more tokens. **This sentence is the main reason strict is the most expensive rule.** **[PROVEN]**
  forcing map ≠ fewer turns.

> **"2. TRUST THE MAP — READ ITS `loc` SPANS, DON'T RE-SEARCH … Do NOT Grep for the same thing the
> map already located. Do NOT read whole files when the map gave you a line range."**

- **Why:** **[PROVEN]** this encodes the winning pattern from the 3-arm run (`map → Read the loc →
  stop`, 2 greps total). The "don't read whole files, read the range" clause targets the token
  cost of whole-file reads (a 2,000-line file vs a 56-line span). This is the **best** sentence in
  the strict rule and is preserved (reworded) in guided.

> **"3. GREP IS A LAST RESORT … ONLY when (a) map for this question failed, OR (b) exact literal you
> already know … Do NOT open an exploration by grepping. Do NOT grep to 'verify' what map pointed
> to."**

- **Why:** **[PROVEN]** the "don't grep to verify" clause is aimed squarely at the deep-dive's
  documented waste ("ran map and then grepped the same thing anyway, paying for both",
  `docs/scubiee-token-ab-deep-dive.md`). Clause (b) preserves grep for the case where it genuinely
  wins (known literal) — **[PROVEN]** grep beats map for exact strings.
- **Weakness:** **[EVIDENCE]** in practice strict still logged 2 `map→grep-within-2` sequences in
  the 4-arm run — the agent grepped right after mapping anyway. Telling it "grep is last resort"
  did not fully stop it; the *guided* framing ("map already located it, read the span") worked
  slightly better (guided map→grep = 1).

> **"4. ONE MAP PER QUESTION, THEN ACT … Avoid re-mapping the same query."**

- **Why:** **[DESIGN]** prevents re-map thrash (the product GATE also bans this). Low harm, low
  measured effect.

> **"5. Editing is native."**

- **Why:** **[DESIGN]** map is discovery-only; editing must stay on native tools. Uncontroversial.

**Strict rule net verdict (from data):** the *forcing* sentences (#1, "MUST … not optional")
changed behavior but **increased turns and tokens** (most expensive rule in both clean runs:
1.28M @ 34 turns, 1.12M @ 24 turns). The *pattern* sentences (#2, #3) are sound and were kept. So
strict's failure is specifically the **"map everything, forced" clauses** — exactly the thing to
avoid.

---

## 2. GUIDED rule — sentence-by-sentence

> **"A managed Scubiee context system is available, but the ONLY Scubiee locate tool exposed is
> `map` … Use your native tools … freely for everything else."**

- **Why:** **[DESIGN]** sets the surface and — critically — *grants native freedom explicitly*.
  The strict rule's adversarial framing ("you MUST … not optional") likely made the model
  over-map; telling it native tools are fine removes that pressure. **[EVIDENCE]** guided used the
  fewest tools (19–20) and fewest maps (1) — it didn't over-call.

> **"`map` is a semantic code locator … it searches by meaning, not by literal string — so it finds
> relevant code even when you don't know the exact name."**

- **Why:** **[DESIGN]** *explains the tool's comparative advantage* rather than commanding its use.
  The model can only decide *when* map helps if it knows *what map is good at*. This sentence is the
  hinge of the "guidance not forcing" approach you asked for.

> **"Follow this guidance (be strict about following it; you are NOT required to call map on every
> task)."**

- **Why:** **[DESIGN]** the exact brief you gave — strict about *following the guidance*, not about
  a rigid workflow. Directly fixes the strict rule's turn-inflation by removing the per-question
  map mandate.

> **"Prefer `map` for semantic / 'where does this happen' search … the right first move over
> grepping guesses."**

- **Why:** **[PROVEN]** the 3-arm win was exactly a semantic "where is the savings logic" question
  that map answered in one shot vs the without-arm's grep-walk. Encodes map's strongest case.

> **"Use `map` when you don't know exactly what you're looking for … strongest at the *start* of an
> unfamiliar area."**

- **Why:** **[EVIDENCE]** from the big-task analysis: map's value is highest for *discovery* and
  drops once the agent is oriented. "At the start" steers it to the high-ROI moment and away from
  re-mapping mid-edit (which cost strict turns).

> **"If you're unsure of a keyword, function name, concept, or where related functionality lives,
> consider `map` instead of firing several speculative greps."**

- **Why:** **[PROVEN]** the without/flexible arms fired 8–20 speculative greps to locate code; the
  point of map is to replace that scatter with one semantic call. "Consider" (not "must") keeps it
  a judgment call.

> **"After a `map`, read the `loc` spans it points to directly … Don't re-grep for something `map`
> already located, and don't dump whole files when it gave you a line range."**

- **Why:** **[PROVEN]** this is the single most important behavior (the winning pattern) and the
  direct fix for the deep-dive's "map then grep the same thing" waste. Kept verbatim-in-spirit from
  the strict rule because it's the one clause proven to help.

> **"When you ALREADY know the exact file, symbol, or path, just use your normal tools … Do not call
> `map` for something you can pinpoint directly; that only wastes a call."**

- **Why:** **[PROVEN]** grep/Read beat map for known literals/paths (product GATE's "needles → host
  Grep"). This sentence *prevents the strict rule's failure mode* — it explicitly licenses skipping
  map, which is why guided made only 1 map call vs strict's 3.

> **"Reach for `map` when broader context helps — multi-file answers or relationships an exact
> search would miss."**

- **Why:** **[EVIDENCE]** map's file-level recall spans relationships grep can't see (the retrieval
  experiments showed map surfaces cross-module candidates). Names the case where map's breadth is
  the differentiator.

> **The five examples** (`where/how` → map; unknown keyword → map; known `foo` in `bar/baz.py` →
> just edit; literal `"cache miss"` → grep; after map returns a `loc` → read that span).

- **Why:** **[DESIGN]** concrete worked examples out-perform abstract rules for LLM instruction-
  following. Each example maps 1:1 to a decision boundary above (semantic→map, known→native,
  literal→grep, post-map→read-span) so the model can pattern-match its situation.

**Guided rule net verdict (from data):** cheapest rule in **both** clean runs (0.83M @ 20 turns;
1.00M @ 21 turns) — the "you decide / native is fine / here's when map wins" framing produced the
fewest turns. **[PROVEN]** on cost. Correctness was split (passed 1/2), so guided is **not** proven
better on task success — see limits.

---

## 3. Why guided beats strict on cost, in one line (backed by the mechanism)

**[PROVEN]** tokens ≈ turns × transcript. Strict *forces map per sub-question* → extra map+read
turns *on top of* grep → most turns (34/24) → most tokens. Guided *lets the agent map once at the
discovery moment and skip map when it already knows the target* → fewest turns (20/21) → fewest
tokens. The forcing sentences are the difference, and they cost turns without removing greps.

## 4. Honest limits (do not over-read this)

- **n = 1 per arm.** Cost ordering (guided < strict) reproduced across **two** clean runs, so the
  *direction* is credible; the exact percentages are not.
- **Correctness is unresolved.** Guided passed 1/2, strict 2/2 across our runs — a real split, too
  few samples to rank rules on quality. Strict's extra grounding *may* help correctness at a cost;
  needs repeats to confirm.
- **One task.** All of this is the `cache_aware_savings` task. Rule effects may differ on
  discovery-heavy vs edit-heavy tasks (the token-savings work showed map's value scales with the
  discovery fraction).
- **To promote any sentence from [EVIDENCE]/[DESIGN] to [PROVEN]:** run guided vs strict ≥5× each,
  report mean turns/tokens + pass-rate with spread.

## 5. Bottom line on the rule design

- **Keep (proven helpful):** "read the returned loc spans, don't re-grep what map found, don't dump
  whole files"; "use map for semantic/unknown discovery"; "use native tools for known literals/paths".
- **Drop (proven harmful):** "MAP FIRST always / map every sub-question / not optional" — it
  inflates turns and tokens without improving discovery.
- **The GUIDED rule is the recommended design:** it keeps every proven-helpful clause and none of
  the harmful forcing, and was the cheapest in both controlled runs. Its one open risk (a correctness
  miss on 1 of 2 runs) is the thing to settle with repeats before shipping.

Rule source of truth: `GUIDED_MAP_RULE` in `run_small_ab_guided.py`, `STRICT_MAP_RULE` in
`run_big_ab_strict.py`. Evidence: arm JSONs under `.ab_workspaces/claude_sdk_harness/*/` and the
prior reports (`scubiee-map-rules-4arm.md`, `scubiee-guided-vs-strict.md`,
`scubiee-strict-map-only.md`, `scubiee-token-ab-deep-dive.md`).
