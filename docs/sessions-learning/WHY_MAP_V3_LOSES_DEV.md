# Why map_v3 loses dev despite being designed from the sessions

Trace-level root cause of the dev losses, from the actual failing cells. Short version: the TOOL is
sound (13/16 retrieval cells are clean one-shots); the losses are 3 specific agent-BEHAVIOR leaks the
rules don't yet bind, plus one task confound. We optimized the tool's output but under-optimized the
rules that make the agent STOP after a good result.

## The evidence: grep usage is rare and concentrated

Of 19 map_v3 cells, only 3 have grep/re-map leaks; the other 16 are clean:
- 13/16 retrieval cells: 0 greps, clean `find -> focus -> Write`.
- `first_map_skips_grap` (retrieval): `find->find->focus->find->find->Grep` - 4 greps, 14 calls.
- `dirty_files_cap` (dev): `find -> Grep -> Grep -> Read -> Edit` - 2 greps.
- `cache_aware_savings` (dev): `find -> Read -> Skill -> Glob -> Grep*3` - 4 greps.

## Leak 1 - the agent grep-VERIFIES a high-confidence find (dirty_files_cap)

The `find` call returned a PERFECT result: `confidence: high`, top hit `git_dirty_files` at
`freshness.py:105-129`, with the full function body inline. The agent had everything to edit now.
It still ran `Grep git_dirty_files` TWICE before editing.

Root cause: "trust but verify." The rules say "do NOT grep what find showed" but it is not binding
when the agent feels any uncertainty. Crucially, the OLD map never triggers this because it returns a
whole-file Read - there is nothing left to verify. **map_v3's precise 25-line body ironically invites
verification** ("is that really all of it?"). Precision can reduce trust.

## Leak 2 - the agent re-MAPS instead of acting (first_map_skips_graph)

`find -> find -> focus -> find -> find -> Grep`. On a medium/low-confidence first find, the rules give
no hard "stop re-mapping, switch to grep/act" cutoff, so the agent loops find calls (and only then
greps). This is the discovery-category spike (611k, the worst retrieval cell).

## Leak 3 - task confound, NOT the map (cache_aware_savings)

`find` located the code in ONE call. The 400k tail (Skill + Glob + 3 greps) was the agent researching
the prompt-caching PRICING sub-question (`cache_read_input_tokens`, `CACHE_DISCOUNT`), which no map
config addresses. On the dev task WITHOUT this confound (health_reason_flag) map_v3 beat mini_v3
(216k vs 269k). So the dev "loss" is ~half confound.

## Why "designed from the sessions" still under-delivered on dev

1. **We measured the sessions on RETRIEVAL-shaped behavior.** The call-purpose study (79x wire-chains,
   57x find->read) was locate behavior. map_v3 is tuned for locate and WINS locate. The edit workload
   has a different shape (edit a known file + sometimes a non-locate sub-task) and we had ZERO map_v3
   dev data at design time. We optimized for the sessions we had, not the workload we now test.
2. **Token cost = tool quality x agent trust.** We improved the tool's output (bodies+wiring in one
   call) but did not equally harden the rules that make the agent ACT on it. The old map wins dev
   partly by accident: a whole-file read leaves nothing to re-check, so no verify-grep.
3. **Precision vs trust tension.** map_v3 returns the minimal right span; the old map returns the
   whole file. The whole file is more tokens up front but kills the follow-up, and it never makes the
   agent doubt completeness. map_v3's tight body saves up-front tokens but can cost a verify call.

## Fixes this points to (behavior/rules, not more tool)

- **F1 - bind the no-verify rule with a confidence hook:** when find returns `confidence: high` with a
  body, the result line should say "high confidence + full body shown - edit now, do NOT grep to
  verify". Make it part of the body block (adjacent to the code), not a trailing rule - the P8/B1
  lesson that adjacent beats trailing.
- **F2 - hard re-map cutoff:** rules + find output: "if a find is not high-confidence, do NOT call
  find again - switch to focus (if you can name it) or one native grep. Never 2+ finds for one
  question." Kills Leak 2.
- **F3 - optional completeness signal:** when find returns a full symbol body, label it
  "(complete symbol, lines a-b)" so the agent knows nothing is truncated - directly answers the
  "is that all of it?" doubt behind Leak 1.
- **F4 - the confound is not a map problem:** strip/990 isolate the pricing sub-question in
  cache_aware before using it to judge map cost (M4).

Net: map_v3 does not need more configs or different bodies. It needs the RULES to convert its
good results into action without a verify-grep or a re-map loop. That is the cheapest, highest-ROI
fix and it is pure rules/output-labeling work.
