# Map-only MCP collect — seed-pick (awaiting map+heatmap twin)

**Agent:** [Map-only](e7589f89-7b9b-43b4-b1a1-80997285b5d7)  
**Mode:** gate + `map` only — **no** pack/heatmap  
**Status:** complete — map+heatmap twin not started

## Work prompt

Improve map→pack seed selection (public packages/ defs; not empty cards / private helpers).

## Efficiency (self-report)

- mcp_calls: 2 (gate, map) — pack_calls: **0**
- map_response_chars: ~2.8k
- total_chars_ingested: ~28k
- spans_read: 10

## Outcome

- `suggested_seed`: **null**
- Top cards still pointed at `context_trace.pick_suggested_seed` / `cli_map` via `why`
- Diagnosis matched prior runs; noted gaps without heatmap (no live `resolve_seed_node` pick proof)

## Next

**Done:** map+heatmap twin [Map+heatmap](77b947a9-d901-4dbf-a8ba-dc4a85504028) — see `2026-09-06-compare-map-only-vs-map-heatmap.md`.
