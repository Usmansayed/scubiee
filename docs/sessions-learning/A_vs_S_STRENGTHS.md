# What A (prose) is good at vs what S (symbolic) is good at

From the consistency matrix (per-task means, A vs S). The point: build an "ultimate" prompt that
takes A's strengths AND S's strengths, since they are complementary.

## Per-task result (tokens | grep | map | recall)
| task | type | A | S | winner |
|---|---|---|---|---|
| faiss_reimport_segfault | focused 1-file | 159k \| 0 \| 2 \| 1.0 | 157k \| 0 \| 1 \| 1.0 | tie |
| idle_engine_self_retire | focused multi-sym | **165k \| 0 \| 2 \| 1.0** | 191k \| 1 \| 2 \| 1.0 | **A** |
| dirty_files_cap | dev edit | **191k \| 2 \| 0 \| 1.0** | 305k \| 5 \| 0 \| 1.0 | **A** |
| memory_budget_resets | cross_module 2-file | 257k \| 2 \| 2 \| 1.0 | **189k \| 0 \| 2 \| 1.0** | **S** |
| first_map_skips_graph | discovery (hard) | 543k \| 8 \| 2 \| **0.0** | 535k \| 8 \| 1 \| **1.0** | **S** |

## A (prose) is GOOD AT: decisive, simple, edit-path cases
- single-symbol focused edits + dev edits: terse `find->edit` / `map->edit`, 0-2 grep.
- A's explicit prose + worked "do NOT verify-grep" examples keep it from grep-spiraling on EDIT tasks
  (dirty_files: A 2 grep vs S 5 grep).
- WEAK AT: hard discovery (A FAILED first_map, recall 0.0 - grep-spiralled to nothing) and
  cross_module (spiked to 257k/2grep where S stayed 189k/0grep).

## S (symbolic) is GOOD AT: hard, multi-file, exploratory cases
- discovery: S recall 1.0 where A hit 0.0 - the symbolic graph-routing + "degrade gracefully /
  switch, don't spiral" logic kept it productive. cross_module: 0 grep, cheaper (189k vs 257k).
- the compact formal rules seem to help the model hold the decision tree on AMBIGUOUS inputs.
- WEAK AT: dev edits (grep-spiralled, 5 grep, 305k) and slightly noisier on simple focused (191k vs
  165k, one stray grep).

## Why they're complementary (hypothesis from the traces)
- EDIT / known-ish target: the agent needs a FIRM "stop exploring, map once, edit" push. A's prose
  bans + worked examples deliver that better; S's terse logic under-constrains the edit path so the
  agent falls to grep.
- HARD / vague / multi-file: the agent needs a STRUCTURED decision procedure (which config, when to
  switch, when to stop). S's explicit state->action rules deliver that better; A's prose lets the
  agent improvise into a grep-spiral.

## Design for the ULTIMATE prompt (variant U)
Hybrid: S's symbolic SELECTION / SEQUENCING / STOP skeleton (good on hard+multi-file) + A's explicit
prose EDIT-PATH discipline injected exactly where S is weak:
1. Keep S's compact [SELECT][OUTPUT->NEXT][CAP][PRIORITY] formal core (wins discovery+cross_module).
2. Add A's strongest prose bans verbatim for the EDIT path: "when editing a known-ish file, map ONCE
   then edit; do NOT grep-chain to the edit" + the verify-grep worked example that kept A's dev greps
   low.
3. Keep the hard cap (<=2 map, no spiral) - it helped both.
4. Keep graph-routing for vague/multi-file (S's discovery win) but NOT as a blanket (A showed
   graph-first regresses simple cases) - gate it on vague∨multi_file only.
Budget: rules <350, instructions <2000. Then A/B U vs A and U vs S across the same 5 tasks.

## Caveats
- n=2 per cell; idle/faiss include one earlier confounded S cell inflating S's focused mean.
- discovery is still a TOOL recall gap for both; S only degrades more gracefully, it does not "solve"
  it. U will not fix discovery either - that needs engine work.
