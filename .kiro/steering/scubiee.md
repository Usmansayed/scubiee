---
inclusion: always
---

**GATE 1:ce_3536ac8e8e83bb8e4d888db37847729c** - Managed repo. `project_id='ce_3536ac8e8e83bb8e4d888db37847729c'`.

**MUST Use Scubiee MCP for locate** when `@scubiee/*` tools are callable. ONE tool `map`, config = `find` | `focus` | `related` | `graph` (plus `gate`/`status`). How-to steps → Scubiee MCP server instructions every turn.

**Prefer host first (Forbid-first map):**
- Literals / imports / error strings / named-symbol under known path → Grep.
- Filenames → Glob; known path → Read.
- Health / `warm_state` / provider-dep → `gate`/`status` + Grep — **not** soft `map`.
- After a `map` result → Read the returned `loc` spans only (guided); **re-Grep of ground map already returned = FAIL**.

**WHEN SCUBIEE MCP IS AVAILABLE — pick ONE config, act, STOP:**
- **Enrich first:** ~30–80 denser tokens (symbols/paths/APIs/outcome verbs — **not** keyword-salad; one sentence; BAN essays). Vague one-liner **or** synonym dump = **FAIL**.
- **find** (don't know where): `map config=find query=<intent> keywords=[names]` → ranked locations + top result's code inline. If it's the place, EDIT — don't re-view.
- **focus** (have a name): `map config=focus names=[Sym]` → the symbol's full code + callers/callees + sibling names, one unit. Edit from this.
- **related** (have a chunk): `map config=related anchor=<file::symbol> query=<intent>` → related bodies in one call.
- **graph** (orient wide): `map config=graph query=<intent>` → files → symbols + call edges, no bodies. THEN one find/focus.
- Native-first while MCP is up = **FAIL**.
- Native Grep/span-Read only after a `map` result's locs, **or** if MCP fully uncallable (no deadlock).
- Empty result **or** needle/health ask → stop ladder; Grep/Read — no `map`/`status` thrash.
- Budget ≤3 MCP locate calls/beat. **BAN whole-file Read** — Read only returned `loc` spans. Edit/Write stay native.

