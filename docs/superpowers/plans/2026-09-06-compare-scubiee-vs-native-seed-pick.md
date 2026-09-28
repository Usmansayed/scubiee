# Compare: Scubiee vs Native — seed-pick context collect

**Work prompt:** Improve map→pack seed selection (public packages/ defs, not empty cards / `_` helpers).

| | [Scubiee](8a6501bd-e5f2-4604-acdb-d7de7ce69c5e) | [Native](d0320302-e9f5-4ec6-a3bd-968da20979bb) |
|---|---|---|
| Method | map→pack→expand + Grep/Read | Grep/Glob/Read only |
| tool_calls | 22 | 41 |
| chars ingested (self-report) | ~78.5k | **~48.5k** |
| Same core diagnosis? | yes | yes |

## Shared (correct) diagnosis

1. `cli_map` fabricates empty-symbol `function` cards (`file:1-1`)
2. `pick_suggested_seed` skips tests/docs only — not `_` / empty symbols
3. `resolve_seed_node` empty symbol → earliest in-file function (`_root`, `_templates_dir`)
4. Tests gap in `test_incremental_context_ladder.py`

## Context quality deltas

| Extra | Who |
|---|---|
| Live ladder repro (bare pack → `::_root`) | Scubiee |
| MCP `search_impl` hit shape (no symbol/kind) | Native |
| `capability._public_symbols` reuse hint | Native |
| Spec `2026-09-05-incremental-context-ladder-design.md` | Native |
| Blind eval JSON evidence | Native |
| Weak public helpers (`is_transient_engine_error`) policy note | both |

**Correctness:** both right on the island. Native slightly richer inventory; Scubiee proved the bug end-to-end via pack.

## Efficiency note

Self-reported chars: Native **lower** (~48k vs ~78k) despite more tool calls — Scubiee paid for map/pack/expand JSON. Fairer metric still: useful spans / facts, not raw chars.
