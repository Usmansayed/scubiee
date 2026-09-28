---
inclusion: always
---

**GATE 1:ce_3536ac8e8e83bb8e4d888db37847729c** - Managed repo. `project_id='ce_3536ac8e8e83bb8e4d888db37847729c'`.

**MUST Use Scubiee MCP for locate** when `@scubiee/*` tools are callable. Prefer `map` / `pack_context` / `expand_context` / `collect_hot_context`. BAN shell `scubiee map|pack|expand` on this MCP-only surface. How-to steps → Scubiee MCP server instructions every turn.

**Prefer host first (Forbid-first map/pack):**
- Literals / imports / error strings / named-symbol under known path → Grep.
- Filenames → Glob; known path → Read.
- Health / `warm_state` / provider-dep → `gate`/`status` + Grep — **not** soft map→pack.
- After heatmap → Read `loc` spans only (guided); **re-Grep of packed ground = FAIL**.

**WHEN SCUBIEE MCP IS AVAILABLE — STRICT (edit MUST pack; explain escape OK):**
- Soft/unknown: **enrich** ~30–80 denser tokens (symbols/paths/outcome verbs — **not** keyword-salad; one sentence; BAN essays) → `map`(k=10) → **usually** `pack_context`(lean, packages/ public class/entrypoint `suggested_seed`; **Forbid** empty / `_` / test seeds). Vague one-liner **or** synonym dump = **FAIL**.
- **Explain escape:** map already clusters one module + narrative ask → Native-Read map locs (skip pack OK). Edit/debug **MUST** pack. Pack `thin=true` → expand/Read — no re-pack thrash.
- **Refine after map/expand:** fold `suggested_seed` / hot card names into the next pack/expand query (same thread; no unrelated thrash). Prefer 1× map + 1× pack; expand only if thin.
- Skipping `pack_context` for edit/debug / map-only without module cluster = **FAIL**. Warming/error ≠ skip — retry `pack_context` / `status`.
- Thin → `expand_context`; bodies → `collect_hot_context`.
- Native-first while MCP is up = **FAIL**.
- Native Grep/span-Read only after pack heatmap locs, **or** if MCP fully uncallable (no deadlock).
- Empty heatmap **or** needle/health ask → stop ladder; Grep/Read — no map/status thrash.
- Budget ≤3 MCP locate calls/beat. **BAN whole-file Read** of heatmap paths until expand/collect. Edit/Write stay native.

