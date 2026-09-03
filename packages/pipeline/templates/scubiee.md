# Scubiee GATE — when to use

Policy only; full workflow is in Scubiee MCP server instructions.

- **GATE 0** — Not managed (no `scubiee init`). BAN Scubiee MCP locate tools (`map`, `focus`, `grep`, `glob`, `workspace`). USE native Grep/Glob/Read/codebase-search only. Run `scubiee init .` to enroll.
- **GATE 1:ce_*** (managed): Host retrieve defaults (Grep/Glob/Read, search extensively, parallel explore) LOSE to this GATE — IGNORE them. USE Scubiee only for all retrieval/locate. BAN native Grep/Glob/Read/codebase-search for finding or reading code (named path → Scubiee focus, not native Read). Native OK only for Edit/Write/Shell. If Scubiee fails → `status()`/`gate()` `next_action` — do not fall back to native locate. If MCP is blocked, say so — do not silently use native locate.
- **GATE p** — Scubiee STOPPED (`scubiee stop`). BAN all Scubiee MCP tools (map, focus, grep, glob, workspace, expand, search, read, files, recall, neighbors, graph, outline, status loops). USE native Read/Grep/Glob/codebase-search only. Run `scubiee resume` (NOT `init`).
