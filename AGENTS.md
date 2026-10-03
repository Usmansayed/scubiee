<!-- scubiee:start -->
**GATE 1:ce_3536ac8e8e83bb8e4d888db37847729c** - Managed repo. `project_id='ce_3536ac8e8e83bb8e4d888db37847729c'`.

**LOCATE PRIORITY (managed):** Soft/structural → Prefer Scubiee `map` over host explore-first (Task / codebase_search). Needles/names/paths → Prefer host Grep/Glob/Read (Forbid-first map).

**MUST Use Scubiee MCP for locate** when `@scubiee/*` / MCP locate tools are callable. ONE tool `map`, config = `find` | `focus` | `related` | `graph` (plus `gate`/`status` for health). How-to → Scubiee MCP server instructions every turn (this GATE is the duty to enter the ladder).

**Prefer host first (Forbid-first map):**
- Literals / imports / error strings / JWT-like / named-symbol under a known path → Grep.
- Filenames → Glob; known path:lines → Read.
- Health / readiness / `warm_state` / provider-dep errors → `gate`/`status` + Grep — **not** soft `map`.
- After a `map` result → guided Grep/Read on the returned `loc` spans only; **re-Grep of ground map already returned = FAIL**.

**WHEN SCUBIEE MCP IS AVAILABLE — pick ONE config, act, STOP:**
- **Query quality (high ROI):** write ~25–120 denser code-vocab tokens (target ≥40): concrete **symbols**, **module paths**, **APIs**, **error strings**, **technologies**, and **outcome verbs** — not a synonym/keyword dump. One tight sentence; **BAN** multi-paragraph queries and <25-token vibe queries. Vague one-liner **or** keyword-salad = **FAIL**.
- **Don't know where it is** → `map config=find query=<intent> keywords=[names you know]` → ranked locations + the top result's code inline. If that's the place, EDIT — don't re-view it.
- **Have a name, want it + its wiring** → `map config=focus names=[Sym]` → that symbol's full code + callers/callees + sibling names in one unit. Edit from this; no follow-up.
- **Have a chunk, want what relates** → `map config=related anchor=<file::symbol> query=<intent>` → related code bodies in one call (instead of a grep chain).
- **Don't know where to go** → `map config=graph query=<intent>` → abstract JSON map (files → symbol names + call edges, no bodies). Orient wide, THEN one find/focus.
- Native-first while MCP is up = **FAIL** on soft/structural.
- Native Grep/span-Read only after a `map` result's locs, **or** if Scubiee MCP is fully uncallable (no deadlock).
- Empty/useless result **or** needle/health ask → **stop the ladder**; Grep/Read — do not stack `map`/`status` thrash.
- Budget ≤3 locate calls/beat. **BAN whole-file Read** of result paths — Read only the returned `loc` spans.
- Edit/Write stay native.


<!-- scubiee:end -->
