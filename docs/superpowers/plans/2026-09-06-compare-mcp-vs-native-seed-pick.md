# Compare: MCP Scubiee vs Native — seed-pick context collect

**Work prompt:** Improve map→pack seed selection (public packages/ defs; not empty cards / `_` helpers).

| | [MCP Scubiee](4195dc84-ba28-4fda-87dd-70c3b49f81a4) | [Native](d67754a9-2a53-465c-9372-2cb21c74c334) |
|---|---|---|
| Method | gate→map→pack_context→expand + span Read | Grep/Glob/Read only |
| tool_calls | 30 | 38 |
| chars ingested (self-report) | **~18.5k** | ~52k |
| pack payload | ~620 heatmap-only | n/a |
| Same core diagnosis? | yes | yes |

## Shared (correct)

- `pick_suggested_seed` / `resolve_seed_node` / empty-symbol & earliest-in-file `_` risk
- CLI `cli_map` fabricates empty-symbol `function` cards
- MCP soft hits lack kind/symbol → `suggested_seed` often null
- Tests gap in `test_incremental_context_ladder.py`

## Context quality deltas

| Extra | Who |
|---|---|
| Live MCP: `suggested_seed=null`, pack ~620 chars | MCP |
| `search_impl` / `_search_hits` / `SearchResult` no-symbol proof | Native |
| `capability._public_symbols` reuse | Native |
| Design spec + corpus private defs | Native |

## vs prior CLI Scubiee on same prompt

| | CLI Scubiee | MCP Scubiee |
|---|---|---|
| chars | ~78.5k | **~18.5k** |
| Host tokens (user) | ~467k | **~448k** this MCP run (vs native **543k**) |

**Takeaway:** MCP heatmap ladder cut tool ingest ~4× vs CLI Scubiee on the same task; diagnosis quality matched native.
