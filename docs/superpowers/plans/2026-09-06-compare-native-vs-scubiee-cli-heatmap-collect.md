# Compare: Native vs Scubiee context collect (CLI heatmap-pack work prompt)

**Work prompt:** Make CLI `scubiee pack` match MCP heatmap-only (`read.top`, no bodies by default); keep opt-in bodies.

| | [Native](15507cc0-5b32-4d4a-8101-c0d275f93433) | [Scubiee](1c93487b-459d-4f90-93e7-9193543197a6) |
|---|---|---|
| Method | Grep/Glob/Read only | map → pack (multi-seed) → Grep/Read |
| tool_calls | 37 | 31 |
| chars ingested (self-report) | ~92k | ~62k |
| Same root cause? | yes | yes |

## Shared diagnosis (both)

- `cli_pack` omits `include_bodies` → `run_pack_context` default `True` → bodies.
- MCP hardcodes `include_bodies=False`.
- `slim_locate_payload` / `_pack_heatmap_only` already produce heatmap + `read.top` when bodies are not collected.
- `CTX_MCP_PACK_BODIES` alone does not collect bodies if `pack[]` empty.
- Must update `test_locate_cli`, `__main__` help, GATE/`rules_installer`.

## Context quality

| Dimension | Native | Scubiee |
|---|---|---|
| Core touchpoints | complete | complete |
| Extra (scripts, evals, default-flip risk) | slightly more script inventory | notes expand Unicode fail + install vs workspace |
| Hallucinations | none apparent | none apparent |
| Ladder fidelity | N/A | used Scubiee CLI pack; expand callers failed (cp1252) |

## Efficiency takeaway

Scubiee reported ~**33% fewer** ingested chars (~62k vs ~92k) and fewer tool calls on the **same** work prompt, with essentially the same implementation plan. Still self-reported tool-output chars, not model tokens.
