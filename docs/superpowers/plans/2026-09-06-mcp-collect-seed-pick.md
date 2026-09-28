# MCP-only Scubiee context collect — seed-pick

**Agent:** [MCP collect](4195dc84-ba28-4fda-87dd-70c3b49f81a4)  
**Mode:** Scubiee MCP only (gate→map→pack_context→expand; no CLI)  
**Status:** complete — Native twin done: [Native collect](d67754a9-2a53-465c-9372-2cb21c74c334). Compare: `2026-09-06-compare-mcp-vs-native-seed-pick.md`.

## Work prompt

Improve map→pack seed selection (public packages/ defs; not empty cards / private helpers).

## Efficiency (self-report)

| Metric | MCP this run | Prior CLI Scubiee ([seed collect](8a6501bd-e5f2-4604-acdb-d7de7ce69c5e)) |
|---|---|---|
| tool_calls | 30 | 22 |
| mcp_calls | 4 | 0 (CLI) |
| chars ingested | **~18.5k** | ~78.5k |
| pack_response_chars | **~620** | CLI lean bodies often multi-k–tens of k |
| Host tokens (prior CLI) | TBD (this run) | ~467k |

## Diagnosis (aligned with prior CLI/native)

- `pick_suggested_seed` / `resolve_seed_node` / `cli_map` empty-symbol cards
- MCP map: `suggested_seed` **null** (cards `role=other`, no kind)
- Pack fallback risks first-in-file `_` helpers
- Tests gap in `test_incremental_context_ladder.py`

## Ladder note

Budget mostly held (1 pack); used 1 expand. No CLI. Heatmap-only pack (~620 chars) — main savings lever vs CLI body packs.
