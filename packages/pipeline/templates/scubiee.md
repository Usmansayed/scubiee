# Scubiee GATE - when to use

Policy only; tool how-to is in Scubiee MCP server instructions.

- **GATE 0** - Not managed (no `scubiee init`). BAN Scubiee MCP locate tools (`map`, `pack_context`, `expand_context`, `collect_hot_context`, `workspace`, and classic/lab extras). USE native Grep/Glob/Read/codebase-search only. Run `scubiee init .` to enroll.
- **GATE 1:ce_*** (managed): **MUST Use Scubiee** when available — STRICT, NO ESCAPE (~30–80 denser code-vocab query — not keyword-salad; map→pack lean→expand if thin; refine with suggested_seed/hot cards after map; warming ≠ skip pack). CLI Prefer `scubiee map`/`pack`; else MCP `map`/`pack_context`. literals/names/paths Prefer host Grep/Glob/Read first (Forbid-first map/pack). Health/warm_state → status+Grep not soft map. After pack: locs only — BAN whole-file Read of heatmap paths; re-Grep of packed ground = FAIL. Native OK only if Scubiee fully uncallable — do not deadlock. Edit/Write stay native. How-to → `scubiee map|pack|expand --help` / MCP instructions.
- **GATE p** - Scubiee STOPPED (`scubiee stop`). BAN all Scubiee MCP tools (map, pack_context, expand_context, collect_hot_context, workspace, expand, status loops, and classic/lab extras: focus, grep, glob, pinpoint, plate, search, read, files, recall, neighbors, graph, outline). USE native Read/Grep/Glob/codebase-search only. Run `scubiee resume` (NOT `init`).
