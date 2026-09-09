<!-- scubiee:start -->
**GATE 1:ce_f4e1adced6e0dd72db51bf587464e982** - Managed repo. `project_id='ce_f4e1adced6e0dd72db51bf587464e982'`.

**LOCATE PRIORITY (managed):** Soft/structural → Prefer Scubiee over host explore-first (Task / codebase_search). Needles/names/paths → Prefer host Grep/Glob/Read (Forbid-first map/pack).

**MUST Use Scubiee** when CLI or MCP locate tools are callable. Prefer CLI `scubiee map`→`pack --mode lean`→`expand` if thin; else MCP `map`→`pack_context`(lean)→`expand_context`/`collect_hot_context`. Tool how-to → MCP server instructions / `scubiee map|pack|expand --help` (follow those steps; this GATE is the duty to enter the ladder).

**Prefer host first (Forbid-first map/pack):**
- Literals / imports / error strings / JWT-like / named-symbol under a known path → Grep.
- Filenames → Glob; known path:lines → Read.
- Health / readiness / `warm_state` / provider-dep errors → `gate`/`status` + Grep — **not** soft map→pack.
- After a Scubiee heatmap → guided Grep/Read on `loc` spans only.

**WHEN SCUBIEE IS AVAILABLE — STRICT, NO ESCAPE (soft/structural):**
- **Query quality (high ROI — few map/pack calls):** Before map, write ~30–80 denser code-vocab tokens: concrete **symbols**, **module paths**, and **outcome verbs** from the ask — not a synonym/keyword dump. One tight sentence; **BAN** multi-paragraph queries. Vague one-liner **or** keyword-salad = **FAIL**.
- Soft/unknown → map (k=10) → **required next** pack lean (public `packages/` suggested_seed; **Forbid** empty / `_` / test / docs seeds).
- **Refine after evidence:** After map (and after expand if used), fold `suggested_seed` / hot card `file`+`symbol` into the next pack/expand query. Same problem thread; **BAN** unrelated rewrite thrash. Prefer **1× map + 1× pack**; expand only if thin — do not burn the ≤3 budget remapping.
- Skipping pack / map-only = **FAIL**. Warming/error ≠ skip — retry pack and/or `status`.
- Thin after pack → expand; need bodies → collect_hot / `--with-bodies` as the surface provides.
- Native-first while Scubiee is up = **FAIL** on soft/structural.
- Native Grep/span-Read only after pack heatmap locs, **or** if Scubiee is fully uncallable (no deadlock).
- Empty/useless heatmap **or** needle/health ask → **stop the ladder**; Grep/Read — do not stack map/status + shotgun thrash.
- Budget ≤3 locate calls/beat. **BAN whole-file Read** of heatmap paths until expand/collect.
- Edit/Write stay native.


<!-- scubiee:end -->
