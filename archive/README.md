# Archive — retired Scubiee implementations & experiments (NOT production)

This directory preserves prior Scubiee work for historical reference. **Nothing
here is on the live import path.** It is intentionally kept OUTSIDE
`packages/` so archived code cannot be imported into the running product.

Do not import from `archive/` in production code. If something here is needed
again, promote a reviewed copy back into `packages/` deliberately.

## Why this exists — the Map V3 migration

Scubiee's MCP map layer was replaced by **Map V3** (one `map` tool with configs
`find | focus | related | graph`, plus `gate` / `status`). The new production
server is `pipeline.map_v3_server` (helpers in `pipeline.map_v3_helpers`), which
is the exact benchmarked implementation that produced the ~2.5–3x token savings
on hard cross-module dev tasks.

The old MCP tool system — a multi-tool surface (`pack_context`, `expand_context`,
`collect_hot_context`, the old `map`, plus lab/classic extras) built on a FastMCP
server (`create_mcp`) — was retired. The underlying Scubiee engine (indexing,
retrieval, storage, graph, search, embedder, freshness/sync) was NOT changed; only
the map/tool layer on top of the engine's HTTP API was replaced.

## Contents

- `old-mcp-map/` — the retired MCP tool server (`mcp_locate.py`) and its
  old-surface scripts (eval/smoke/experiment drivers for pack/expand/old-map).
- `old-mcp-map/tests/` — tests that exercised the retired tool surface
  (`create_mcp`, the pack→expand ladder, old `mcp_ship_check` helpers).
- `experiments/claude_sdk_harness/` — the A/B research harness, benchmarks,
  probes, and prototype Map V3 bridge (the design reference the shipped
  `pipeline.map_v3_server` was promoted from).

See `docs/sessions-learning/` (kept in place) for the research notes, learnings,
and benchmark write-ups that drove these decisions.
