# Symbolic map_v3 policy (variant S) - build + consistency audit

Instructions-only experiment: the current optimized map_v3 rules (variant A) re-encoded as a compact
symbolic policy. NO tool/schema/ranking change. Variant S added alongside A/B/C/D (same bridge),
wired in policies.RULES['map_v3_s'] and both runners.

## Token count (final)
- RULES_MAP_V3_S = **340** tokens (budget < 350: OK)
- INSTRUCTIONS_MAP_V3_S = **1119** tokens (budget < 2000: OK)
vs prose A: rules 337, instructions 1827 -> S encodes the same behavior with ~39% fewer instruction
tokens.

## Operator vocabulary (fixed, common-logic only)
and and or or not ¬  if-then if-then  then/becomes then  in/member in  not-in not-in  all all
exists exists  is =  is-not is-not  at-most <=  one · ; plus superset superset, union union for set
results. All survive the harness utf-8 CLAUDE.md round-trip (verified) - operators reach the agent
intact. (Note: these glyphs are intentionally non-ASCII per the experiment brief; safe on the MCP
file path, which is utf-8, unlike the CLI console path that had the historical mojibake rule.)

## Consistency audit: every original behavior -> symbolic representation

| # | Behavior in A (prose) | Encoded in S | Section |
|---|---|---|---|
| 1 | Goal = fewest calls; cost = context x calls | [GOAL] min(calls); cost = context x calls | rules+instr |
| 2 | map is PARTNER to native, not replacement | map ALONGSIDE native, map != replacement | [GOAL] |
| 3 | known literal/path/symbol -> native Grep/Read/git | known ⇒ native ; ¬map(known) | [SELECT][PROHIB] |
| 4 | can name symbol(s) -> focus, ALL names in one call | can_name(S) ⇒ focus(names=[∀S]); ¬(focus per symbol) | [SELECT][SEQ][PROHIB] |
| 5 | describe/unknown location -> find | describe ∧ loc=unknown ⇒ find(query) | [SELECT] |
| 6 | vague/big area -> graph once, then focus | vague ∨ multi_file ⇒ graph→focus ; graph ≤1 | [SELECT][SEQ][PROHIB] |
| 7 | have chunk + "what else" -> related | have_chunk ∧ ask ⇒ related(anchor,query) | [SELECT] |
| 8 | find conf=high+body -> EDIT, no verify | find.conf=high ∧ body ⇒ EDIT ; ¬grep∧¬reRead∧¬reFind | [TRUST][OUTPUT->NEXT] |
| 9 | find conf=medium -> edit if matches else switch, no reFind | medium ∧ matches ⇒ EDIT ; medium ∧ ¬matches ⇒ switch | [OUTPUT->NEXT] |
| 10 | find conf=low -> no reFind, refine once/switch | low ⇒ ¬reFind ; refine·1 ∨ focus ∨ 1·grep | [OUTPUT->NEXT] |
| 11 | find body = complete symbol | body := full source over stated range ; (comment on rule 8) | [DEFINITIONS][TRUST] |
| 12 | <=2 map calls/locate; no find-loop; no grep-spiral | map_calls ≤ 2 ; ¬loop(find→find); ¬spiral(grep→grep) | [CAP][PROHIB] |
| 13 | after result -> act; no verify-grep/re-map/2nd-config | result ⇒ act ; ¬(grep_same∨reRead∨reFind∨2nd "verify") | [STOP][PROHIB] |
| 14 | focus returns wiring+siblings -> don't re-fetch them | focus.result ⇒ EDIT ; wiring+siblings present ⇒ ¬refetch | [OUTPUT->NEXT] |
| 15 | don't read whole file when body/range given | ¬Read(whole_file) when body ∨ line_range given | [PROHIB] |
| 16 | answer: PRIMARY first, neighbors under related: | answer ⇒ PRIMARY first ; neighbors ∈ "related:" | [STOP] |
| 17 | gate/status = health only, not locate | gate|status = health ; ∉ locate | [TOOLS][PRIORITY] |
| 18 | stop/act as soon as evidence sufficient | evidence=sufficient ⇒ STOP → act | [STOP] |
| 19 | minimize context, maximize relevance | ∀Q: minimize_context ∧ maximize_relevance | [STOP] |
| 20 | precedence (known>cap>trust>select) | [PRIORITY] P1 known>P2 cap>P3 trust>P4 select>P5 min_ctx | [PRIORITY] |
| 21 | fallback: 2 tries failed -> 1 grep/Read then act | map ¬found after 2 ⇒ 1·(grep|Read) → act ; ¬further map | [CAP][FALLBACK] |
| 22 | single-file edit = 1 call; multi-symbol = 1 focus | single_file ⇒ |calls|=1 ; multi_symbol ⇒ 1·focus | [SEQ] |
| 23 | tool capabilities (what each config returns) | [TOOL CAPABILITIES] find/focus/graph/related signatures | [TOOLS] |

All 23 behaviors present. Nothing dropped to meet budget.

## Ambiguities under compression -> fixes applied

1. `switch` was undefined -> pinned to `switch → focus(name_seen) ∨ 1·grep` in [OUTPUT->NEXT] so it
   can't be read as "switch to anything".
2. `·1` / `1·` (the "exactly one" quantifier) could be misread -> operator legend defines `· = one`
   and it is used consistently (1·grep, refine·1, graph ≤1).
3. "first matching rule wins" for [SELECTION] made explicit, and [PRIORITY] P1 (known⇒native) is
   stated to override the map SELECT rules so a known-symbol case can't fall into find/focus.
4. `result ⊇ {code, wiring, siblings}` clarifies that re-fetching wiring/siblings is redundant
   (removes the "maybe I still need callers" doubt that drove verify calls).
5. CAP vs TRUST order: PRIORITY lists P2 CAP above P3 TRUST so "<=2 calls" always wins over any
   verify urge, matching A's intent.

## What is NOT changed
- No tool, schema, ranking, or retrieval change. Only policies.RULES['map_v3_s'] text.
- A/B/C/D variants retained; S is the symbolic candidate to A/B test when running the variant matrix.

## Status
Offline-verified: budgets (340/1119), battery 25/25, utf-8 round-trip of all operators, wiring in
both runners. Live A/B (S vs A on the same queries) is the next step - run the variant matrix
(map_v3_a vs map_v3_s) to see whether the symbolic form changes adherence/cost. Not yet run.
