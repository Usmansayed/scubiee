# 3-way multi-file dev: old mini_v3 vs new map_v3 vs native-only

Follow-up to MULTIFILE_WITH_vs_WITHOUT.md. Same two genuine 2-file tasks
(merkle.py accessor + freshness.py `to_dict`), same oracles, now THREE arms:

- **without**  — native tools only (Read/Grep/Glob/Edit), no MCP.
- **mini_v3**  — OLD Scubiee: single `map` tool returning LOCATION cards only (no
  bodies), + the `two_layer_v3` rules. Agent reads bodies natively.
- **map_v3**   — NEW Scubiee (production U): `map` with find/focus/related/graph,
  `focus` returns bodies + wiring, + the 1442-token U prompt.

n = 2 per arm per task. Full offline preflight (`preflight_all.py`) was 15/15
"EVERYTHING WORKING PERFECTLY" before any live token was spent.

## Results (means, n=2)

### MF1 — total_changed_field (LITERAL target: `changed_count`, `to_dict`, SyncDiff)

| arm | tok mean | calls | map | grep | read | success | oracle strict |
|-----|---------:|------:|----:|-----:|-----:|:-------:|:-------------:|
| without | 239,849 | 8.0 | 0 | 3.0 | 2.0 | 2/2 | 2/2 |
| mini_v3 | 236,428 | 7.0 | 1.0 | 0.5 | 2.5 | 2/2 | 2/2 |
| **map_v3** | **227,728** | 7.0 | 2.0 | 0 | 1.5 | 2/2 | 2/2 |

Near-tie, slight ordering map_v3 < mini_v3 < without. All three fully correct.

### MF2 — root_hash_fingerprint (SEMANTIC target: "short fingerprint of content hash")

| arm | tok mean | calls | map | grep | read | success | oracle strict |
|-----|---------:|------:|----:|-----:|-----:|:-------:|:-------------:|
| **mini_v3** | **228,975** | 7.0 | 1.0 | 1.0 | 2.5 | 2/2 | 0/2 |
| without | 293,283 | 8.5 | 0 | 3.0 | 2.5 | 2/2 | 0/2 |
| map_v3 | 336,208 | 8.5 | 1.0 | 0.5 | 3.5 | 2/2 | **2/2** |

## Verdict (honest, and it is not a clean "new wins")

**Correctness: all three solved both tasks every time (12/12 success).** On tasks this
well-specified, none of the three is *required*.

**MF1 (literal): new map_v3 is marginally leanest, but it's a wash** — 228k vs 236k vs
240k, inside the noise. The literal target is greppable, so semantic retrieval adds
little; the new surface's richer `focus` payload roughly cancels the reads it saves.

**MF2 (semantic): the headline is counter-intuitive — OLD mini_v3 was the cheapest
(229k), and NEW map_v3 was the most expensive (336k).** But the token number alone is
misleading, because the arms did not do equally correct work:
- **map_v3 was the ONLY arm that passed the oracle strictly (2/2).** It kept the full
  root_hash AND added the short fingerprint (3 edits on r1), satisfying the
  backwards-compat check in the prompt ("keep the full hash too").
- **without and mini_v3 both scored oracle_strict 0/2** — they added the fingerprint
  but dropped/omitted the full hash, so they only reached the lenient 2/3 pass. They
  were "cheaper" partly by doing *less* of what the task asked.
- map_v3's extra reads (3.5 mean) and edits are the cost of that completeness: it
  verified surrounding code before touching the dict and preserved the existing field.

So on MF2 the fair reading is: **new map_v3 traded ~45% more tokens for the only fully
correct, backwards-compatible implementation.** Whether that is a "win" depends on what
you value — raw token economy (mini_v3) vs implementation completeness (map_v3).

**Old vs new, head to head:**
- MF1: new ~4% leaner than old, both fully correct. Slight edge new.
- MF2: old ~32% leaner than new, but old was NOT backwards-compatible (0/2 strict)
  while new was (2/2 strict). Different quality, not just different cost.

**Bottom line:** On tidy, well-specified 2-file tasks neither Scubiee variant unlocks
*capability* over native — all three succeed. The NEW surface's advantage is behavioral:
it pushes the agent toward the complete, spec-faithful edit (kept the full hash) at a
token premium, and it suppresses grep in favor of semantic `map`. The OLD surface is
leaner because it does less (location-only, agent reads just enough). The large wins
Scubiee showed earlier still require harder-to-locate or cross-module seams, which these
2-file literal/semantic edits are not.

### Caveats
- n=2; MF2 map_v3 had high variance (297k vs 375k).
- The MF2 "strict" split hinges on one backwards-compat check; a different oracle weight
  would change the economy/quality tradeoff reading.
- One shared seam (merkle<->freshness) across both tasks.

## Why new map_v3 did not simply beat the others (ties into the MF1 autopsy)
See MULTIFILE_WITH_vs_WITHOUT.md "Why map did NOT beat native on MF1". The new surface
carries fixed overhead every run: a ToolSearch turn to load `map`, the 1442-token U
prompt re-sent each turn, and larger `focus` payloads. That overhead is only repaid when
locating is genuinely hard OR when the agent trusts `focus` and skips native reads. On
MF2 the agent did NOT fully skip reads (3.5 mean) — it mapped once then still read to
verify before a careful, complete edit — so it paid both the map tax and the read cost.
The old mini_v3, returning only locations, nudged the agent straight to a minimal native
read-and-edit, which was cheaper but less thorough.
