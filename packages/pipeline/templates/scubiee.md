# Scubiee GATE - when to use

Policy only; tool how-to is in Scubiee MCP server instructions.

- **GATE 0** - Not managed (no `scubiee init`). BAN the Scubiee MCP `map` tool (all configs: find/focus/related/graph). USE native Grep/Glob/Read/codebase-search only. Run `scubiee init .` to enroll.
- **GATE 1:ce_*** (managed): **MUST Use Scubiee MCP** when available — ONE tool `map`, config=find|focus|related|graph (+ gate|status for health). Enrich ~25–120 denser code-vocab tokens (target ≥40 — not keyword-salad). Pick ONE config, act on the first good answer, STOP: find = where is X (+ top code inline); focus = a name's code + callers/callees + siblings; related = related bodies for a chunk you have; graph = files→symbols + edges (orient, then one find/focus). literals/names/paths Prefer host Grep/Glob/Read first (Forbid-first map). Health/warm_state → gate/status+Grep not soft map. After a map result: Read returned locs only — BAN whole-file Read; re-Grep of ground map returned = FAIL. Native OK only if Scubiee fully uncallable — do not deadlock. Edit/Write stay native. How-to → Scubiee MCP server instructions every turn.
- **GATE p** - Scubiee STOPPED (`scubiee stop`). BAN all Scubiee MCP tools (`map` with every config, and `gate`/`status` loops). USE native Read/Grep/Glob/codebase-search only. Run `scubiee resume` (NOT `init`).
