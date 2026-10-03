# mini+ : old map + include_bodies + names — arm test

Tests the two additions the sessions study picked for the OLD single-tool map:
1. **include_bodies** (output): return the top symbols' source inline, all of them when several
   share one file — kills the `map -> Read` follow-up.
2. **names** (input): exact identifiers anchor the ranking and are guaranteed to surface — folds
   in the `grep <name>` the agent would otherwise run.

Framing in the rules/instructions: map is a PARTNER to native Grep/Read, not a replacement.
Built as `mini_plus_bridge.py` (tools map/gate/status, namespaced scubmini); rules
`RULES_MINI_PLUS` (290 tok) / `INSTRUCTIONS_MINI_PLUS` (933 tok). All preflight gates passed first:
budgets, MCP-stdio spawn (schema exposes query/names/include_bodies/k, live map returns bodies),
dev-runner preflight.

## Results (3 arms, n=1 each)

| Task | Arm | tokens | API calls | map | grep | oracle | pass |
|---|---|---:|---:|---:|---:|---:|:--:|
| cache_aware_savings | mini_plus | 507,538 | 13 | 1 | 1 | 0.33 | **no** |
| cache_aware_savings | mini_v3 | 480,211 | 12 | 1 | 0 | 1.0 | yes |
| cache_aware_savings | newmap | **292,292** | **8** | 3 | 0 | 1.0 | yes |
| dirty_files_cap | mini_plus | 271,097 | 8 | 1 | 3 | 1.0 | yes |
| dirty_files_cap | mini_v3 | 401,189 | 12 | 1 | 4 | 1.0 | yes |
| dirty_files_cap | newmap | **160,057** | **5** | 2 | 0 | 1.0 | yes |

## What the two additions DID do

**On the easy task, include_bodies helped old map: mini_plus beat mini_v3** (271k vs 401k, 8 calls
vs 12, 3 greps vs 4). The one `map(include_bodies=true)` gave the agent the body, so it edited with
fewer total calls than plain old-map. That is the intended effect, and it's a real win over the
baseline old map.

## What they did NOT do (honest)

1. **The agent did not pass `names` on its own.** In both mini_plus traces it called
   `map(query, include_bodies=true)` with NO `names`, even on the easy task where it knew
   `git_dirty_files`. The input exists and works (verified offline), but the model didn't reach for
   it. An input the agent won't use can't help — this is an instruction/affordance problem, not a
   bridge bug.
2. **include_bodies returns the queried symbol's cluster, not the call sites.** On the easy task the
   agent still grepped 3x — not to re-find the symbol, but to see the CALL SITES where the `cap`/
   slice behaviour had to change. The single returned body didn't contain them, so the agent fell
   back to grep. Bodies kill the `Read` call; they don't kill the "understand the call sites" greps.
3. **mini_plus FAILED the hard task (oracle 0.33)** — same pricing-math confound as before. It got
   the body in one map, but botched the prompt-caching pricing calculation. Not a map issue; the
   task's Skill/pricing sub-question (M4) is still the dominant variable on cache_aware.

## Standing vs the three arms

- **newmap won both tasks this round** (292k hard, 160k easy; both correct), and never grepped.
  Its multi-config surface (find returns clustered bodies + connections) covers the call-site need
  that made the old-map arms grep.
- **mini_plus improved on plain old map on the easy task** (the include_bodies win) but did not
  catch newmap, because (a) the agent didn't use `names`, and (b) bodies alone don't supply call
  sites — which is exactly what newmap's `refs`/connections give.
- **The hard task remains dominated by the pricing confound**, so its numbers don't cleanly measure
  map behaviour (M4 still open).

## Takeaways for the two additions

- `include_bodies` is worth keeping — it measurably cut old-map cost on the clean task. It's the
  high-value one, as predicted.
- `names` as a *passive input* is not enough: the agent won't volunteer it. To get its value, the
  instruction must make passing known names non-optional, OR the bridge should auto-extract likely
  names from the query (so the lexical anchor happens without the agent's cooperation).
- A body-only old map still greps for call sites. The gap between mini_plus and newmap IS the
  call-site/wiring info — which is the argument FOR newmap's `refs`, used sparingly.

## Files / run dirs
- bridge: `scripts/claude_sdk_harness/mini_plus_bridge.py`
- rules: `two_layer.py` RULES_MINI_PLUS / INSTRUCTIONS_MINI_PLUS; `policies.RULES['mini_plus']`
- run dirs: latest `*_devmini_cache_aware_savings`, `*_devmini_dirty_files_cap` (3-arm)
