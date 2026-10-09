# Why the agent picks Grep over Map — evidence from decision traces

Built from the captured decision traces (Cursor `auto`, Run 4 `20261004T160838Z`, 4 cells:
c_default ×2, c_nav ×2) plus the earlier cells. Each trace records the agent's own reasoning
immediately before each tool call, so these are the agent's *stated* reasons, not inference.

This is the evidence base for drafting the "Map is the strong default, Grep is the narrow
exception" rules. **Do not draft wording without reconciling it against this list.**

---

## 0. Two confounds we must control for first (or the measurement lies)

Before any map-vs-grep reasoning, two artifacts dominated the traces and must be neutralized:

1. **Contaminated task — `add_importers_expand_alias` (hard7) is INVALID.**
   Its oracle expects edits to `packages/pipeline/mcp_locate.py` + the constant
   `_EXPAND_DIRECTION_VALUES`. That file was **archived** to `archive/old-mcp-map/mcp_locate.py`
   during the v3 doc/cutover. Verified: the file is absent from the live tree; the constant has
   0 hits in `packages/`, 3 in the archive. The agent correctly kept discovering the file missing
   and burned **40–60 greps** trying to reconcile with the oracle. This — not framing — is why
   hard7 swung 0.33↔1.0. **Discard hard7 as an instrument.** Valid tasks whose targets exist:
   `unify_token_estimate` (token_meter.py + session_store.py) and `cache_aware_savings`
   (token_meter.py).

2. **Task-spec hunting is a harness artifact, not a code-locate fork.**
   The prompt is vague and the workspace folder is literally named after the task
   (`..._cursor_add_importers_expand_alias`), so every cell opened with 2–4 grep/glob calls
   searching for the task spec string (`grep "add_importers_expand_alias"`, globbing the harness
   dir). Reasoning verbatim: *"The workspace is named `cursor_add_importers_expand_alias`… I will
   search the harness scripts for the exact requirement."* This inflates grep counts and is
   unrelated to map-vs-grep. Real benchmarks must give the prompt directly (not via a telltale
   folder name) so this phase disappears.

---

## 1. LEGITIMATE Grep (the narrow path we must preserve)

Cases where the agent reached for grep and it genuinely was the right/necessary tool. The rules
must keep a clear path for these, or stricter wording will backfire.

| # | Trigger (from traces) | Why grep is right |
|---|---|---|
| L1 | **Exact literal / known string** — "the exact files and strings are known, routing a known literal through map is unnecessary." | A known literal is one cheap grep; map adds nothing. |
| L2 | **Verify a specific line/edit site after you already hold the file** — confirm a brace set contains both `importers` and `callers`. | Pinpoint confirmation of a literal, not discovery. |
| L3 | **Map genuinely returned nothing usable** — "the prior find on context_trace.py only returned its module docstring… a direct grep is preferable." | Correct fallback when a map result is thin (see B3 — the upstream cause is often a bad query, but the fallback itself is legitimate). |
| L4 | **Non-code / structural checks** — `.gitignore`, git ls-files, "is this file tracked?" | Outside map's semantic code index. |

## 2. DEFAULT-TO-GREP (the behavior we must fix with wording)

Cases where **map was the better tool but the agent reverted to grep anyway**. These are the
targets. Each is a direct quote-backed pattern.

| # | Agent's stated reason (paraphrased from trace) | Root cause in CURRENT rules |
|---|---|---|
| B1 | *"Native Grep is correct for the known symbol `_EXPAND_DIRECTION_VALUES`, but the scubiee GATE mandates map for locate. **This creates a conflict between the two rules**"* → resolves to grep. | The rules present "known symbol → native" and "map is primary for locate" as two competing hard rules. The agent experiences a **conflict** and breaks it toward its native habit. |
| B2 | *"Confirmed that two calls are the maximum allowed… **the two-call limit forces a split strategy**"* → greps the second file instead of a 2nd map. | The **`<=2 map calls` hard cap** is read as "spend map sparingly," so the agent *rations* map and uses grep for the rest. The cap meant to stop spirals instead suppresses legitimate map use. |
| B3 | Keyword-salad `find` query → thin result → *"a direct grep is preferable to another map."* | No **query-quality** guidance. A bloated multi-clause query returns a docstring; the agent blames map and leaves. |
| B4 | *"map focus on `_EXPAND_DIRECTION_VALUES` alone would miss the routing sets in context_trace.py"* → so grep both. | The agent doesn't know `focus` takes **multiple names across files in one call**, or that `related`/`graph` cover cross-file spread. It assumes map is single-target. |
| B5 | Reflex: knowing *a* name at all is treated as "I'm past discovery, go native." | "known → native" is stated too broadly; knowing one symbol's name is NOT a reason to skip map's **wiring/relationships** (callers, siblings, the other file). |

## 3. What the navigator (c_nav) framing already changed

The c_nav traces show B1 and B2 **largely absent** at the first fork. Instead of "conflict / cap
forces split," the reasoning was: *"Switching to map **focus** for `_EXPAND_DIRECTION_VALUES` to
capture its **callers and wiring**."* So reframing map as "see a symbol **and its connections**"
(not "a mandated locate step I must minimize") already removed the two biggest default-to-grep
drivers. It did **not** fix B3 (query quality) or fully fix B4 (cross-file reach).

## 4. Design implications for the rule drafts (feeds task #3)

1. **Remove the conflict (fixes B1/B5).** Don't frame "known → native" as a peer rule to "map is
   primary." Reframe: *knowing a name is a reason to `focus` it* (you get its wiring), not a reason
   to leave map. Native is for a known **literal string**, not a known **symbol**.
2. **Drop or soften the hard `<=2 map` cap (fixes B2).** The cap suppresses the exact behavior we
   want (returning to map as the task moves). Replace "minimize map calls" with "re-enter map when
   you move to new code." Keep only the real anti-waste rule: *don't repeat the same query/search.*
3. **Add query-quality guidance (fixes B3).** One tight intent sentence or exact names, not a
   multi-clause keyword dump. A thin result means *refine the query or switch config*, not "give up
   on map."
4. **Teach cross-file reach (fixes B4).** `focus names=[A,B,...]` spans files in one call;
   `graph`/`related` cover spread-out changes. Knowing the change touches 2 files is a reason to
   pass both names to focus, not to grep.
5. **Preserve the narrow grep path (L1–L4) explicitly** so stricter wording doesn't push map onto
   genuine literal lookups and non-code checks.

## 5. Measurement hygiene for the A/B (feeds task #4)

- Use only **valid tasks** (`unify_token_estimate`, `cache_aware_savings`); drop hard7 until its
  oracle is retargeted to the v3 tree (or delete it).
- Expect a task-spec-hunt phase from the folder name; count **map calls** and **post-spec greps**
  separately from the initial spec-hunt greps, or feed the prompt without the telltale folder name.
- Keep trace capture ON every run so each new wording is judged by whether B1–B5 reasoning
  disappears — not just by tokens/oracle, which are high-variance on `auto` at low n.
