**GATE 1:ce_d9cb766c3820091ed9ffbc64ef33063c** - Managed repo. `project_id='ce_d9cb766c3820091ed9ffbc64ef33063c'`.

**MUST Use Scubiee for locate** when tools are available — follow this routing strictly.

### Trace / pack is the point (do not skip)
- `pack_context` is the **tracer/heatmap step** (builds the call/data slice + hot bodies). `map` alone is only a seed/card list — **not** enough context to edit.
- On non-trivial work you **must** run **`pack_context(mode=lean)`** (after `map` or with a known seed). Prefer lean pack over native file thrash.
- If pack is thin → **`expand_context`** (callees|callers|effects|broad) before guessing with Grep.
- Do **not** substitute `status` / directory listing / shotgun Grep for pack+expand.

### When to call which tool
- **Unknown where to start / soft “how does X work?”** → `map`(descriptive code-vocab query, k=10) → **required next** `pack_context`(same query, `suggested_seed`, mode=lean). Do **not** stop after map-only. Heatmap + hot bodies come from pack (the tracer).
- **Have a seed (file/symbol/line) needing bodies** → `pack_context`(mode=lean) first (or `map_context` GUIDE-only cards then pack/collect). mode=full only if lean is too thin.
- **Pack/map was thin / missing a hop** → `expand_context`(direction=callees|callers|effects|broad, with_bodies as needed) or `collect_hot_context(ids=…)`. `pack_context(policy=broad)` once if the slice was too strict.
- **Edit-ready soft hit** → `pinpoint`. **How-it-works overview without bodies** → `plate`.
- **Exact literal / import / error string (no seed hunt)** → host Grep. **Filename only** → host Glob. **Already-known path** → host Read.
- **Session / rematerialize** → `workspace` / `expand`.

### Hard requirements (managed)
- Before the **first** broad native search (repo-wide Grep/findstr/dir dump) on an unfamiliar area: complete at least **`map` + `pack_context(lean)`** (or `pack_context(lean)` alone if seed known).
- Before editing code you have not already packed: read **pack bodies / expand delta** first (Native-Read only the cold card.locs from the heatmap).
- Budget: ≤3 Scubiee locate calls for the first beat (map→pack→expand); then edit. On non-trivial tasks target **≥2 calls with pack included** (map+pack or pack+expand).
- Avoid token dumps and parallel explore thrash.

### Forbidden until ladder ran (or Scubiee errored)
- Do **not** open with recursive directory listings or shotgun `findstr`/`rg` across the whole repo to “discover” architecture.
- Do **not** treat a single `map` (or `gate`/`status`) call as enough context — **`pack_context` is mandatory** for tracer/heatmap bodies.
- Do **not** skip pack because map “looked relevant” — still pack the seed.

**Native Grep/Glob/Read OK** after a heatmap/pack (guided by cards), or when Scubiee MCP is down, blocked, paused, or a tool errors — continue; do not deadlock.
Edit/Write/Shell stay native. How-to → Scubiee MCP server instructions.
