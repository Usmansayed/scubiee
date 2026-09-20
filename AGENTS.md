<!-- scubiee:start -->
**GATE 1:ce_0a779347a9061995489923aad707cb0b** - Managed repo. `project_id='ce_0a779347a9061995489923aad707cb0b'`.

**LOCATE PRIORITY (managed):** Soft/structural → Prefer Scubiee over host explore-first (Task / codebase_search). Needles/names/paths → Prefer host Grep/Glob/Read (Forbid-first map/pack).

**MUST Use Scubiee MCP for locate** when `@scubiee/*` / MCP locate tools are callable. Prefer `map`→`pack_context`(lean)→`expand_context`/`collect_hot_context`. **BAN shell** `scubiee map|pack|expand` while MCP locate tools are callable. Shell CLI locate only if MCP is fully uncallable (no deadlock). How-to → Scubiee MCP server instructions every turn (this GATE is the duty to enter the ladder).

**Prefer host first (Forbid-first map/pack):**
- Literals / imports / error strings / JWT-like / named-symbol under a known path → Grep.
- Filenames → Glob; known path:lines → Read.
- Health / readiness / `warm_state` / provider-dep errors → `gate`/`status` + Grep — **not** soft map→pack.
- After a Scubiee heatmap → guided Grep/Read on `loc` spans only; **re-Grep of packed ground = FAIL**.

**WHEN SCUBIEE MCP IS AVAILABLE — STRICT (edit MUST pack; explain escape OK):**
- **Query quality (high ROI — few map/pack calls):** Before map, write ~25–120 denser code-vocab tokens (target ≥40): concrete **symbols**, **module paths**, **APIs**, **error strings**, **technologies**, and **outcome verbs** across the problem surface — not a synonym/keyword dump. One tight sentence; **BAN** multi-paragraph queries and <25-token vibe queries. Vague one-liner **or** keyword-salad = **FAIL**.
- Soft/unknown → `map` (k=12) → use `suggested_seeds` (1–3) → **re-enrich** the pack query with every seed `file::symbol` + hot cards (pack query should be denser than map) → `pack_context` lean with `seed_*` + `seed2_*`/`seed3_*` when multi-module (public `packages/` class/entrypoint; **Forbid** empty / `_` / test / docs seeds).
- **Explain escape (skip pack OK):** if map already clusters one packages/ module and the ask is narrative/how-it-works (not edit), Native-Read top map card locs — do not pay pack tax. Edit/debug still **MUST** pack. If pack returns `thin=true` → expand or Read seed file; **do not** re-pack thrash.
- **Refine after evidence:** After map (and after expand if used), fold `suggested_seed` / hot card `file`+`symbol` into the next pack/expand query. Same problem thread; **BAN** unrelated rewrite thrash. Prefer **1× map + 1× pack**; expand only if thin — do not burn the ≤3 budget remapping.
- Skipping `pack_context` for edit/debug / map-only without a module cluster = **FAIL**. Warming/error ≠ skip — retry `pack_context` and/or `status`/`gate`.
- Thin after pack → `expand_context`; need bodies → `collect_hot_context` (or include_bodies as the surface provides).
- Native-first while MCP is up = **FAIL** on soft/structural.
- Shell `scubiee map|pack|expand` while MCP is up = **FAIL**.
- Native Grep/span-Read only after pack heatmap locs, **or** if Scubiee MCP is fully uncallable (no deadlock).
- Empty/useless heatmap **or** needle/health ask → **stop the ladder**; Grep/Read — do not stack map/status + shotgun thrash.
- Budget ≤3 locate calls/beat. **BAN whole-file Read** of heatmap paths until expand/collect.
- Edit/Write stay native.


<!-- scubiee:end -->
