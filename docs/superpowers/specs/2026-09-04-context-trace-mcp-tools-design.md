# Context Tracing MCP tools — design

**Date:** 2026-09-04  
**Status:** approved to ship (chat)  
**Product:** Guide-only heatmap; agent reads code itself (native Read).

## Tools

### 1. `map_context` (primary)

**In:** `query` (detailed paragraph), `seed` (path + optional `start_line`/`symbol` or raw seed text hint), optional `seed2`, `k` (max hot cards).

**Out (guide only — no bodies):**
```json
{
  "ok": true,
  "tool": "map_context",
  "heatmap": [
    {
      "id": "file::symbol",
      "file": "...",
      "symbol": "...",
      "start_line": 1,
      "end_line": 20,
      "score": 0.95,
      "heat": "hot|warm|cool",
      "why": "...",
      "path": ["seed", "..."]
    }
  ],
  "guide": "Read hot nodes via native Read; call expand_context if map feels thin."
}
```

**Engine:** polytrace (+ AST/LSP; Graphify when available). Persist last heatmap in session for expand.

### 2. `expand_context` (map growth)

**In:** `node` (`file::symbol` or heatmap index), `direction` = `callees|callers|refs|deps|all`, `k`.

**Out:** **delta** cards only (new/raised nodes), plus `heatmap_id` / counts. Still no bodies by default.

### 3. `collect_hot_context` (optional)

**In:** `threshold` (default 0.82), `max_chars`.

**Out:** bodies for session heatmap nodes ≥ threshold (budgeted). Prefer agent native Read; this is escape hatch.

## Routing (server instructions)

```text
Need where to read for a task + seed → map_context
Map thin / need one hop → expand_context
Batch hot code (rare) → collect_hot_context
Soft browse without seed → map (existing)
Open stored span handle → expand (existing)
```

## Non-goals (v1)

- Not replacing native Read
- Not LLM director
- Not recall_belt as default (too noisy)
