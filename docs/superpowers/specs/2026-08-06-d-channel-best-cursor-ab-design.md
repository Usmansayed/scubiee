# D_channel_best + Cursor-only A/B

**Date:** 2026-08-06  
**Status:** approved (Cursor-only evaluation; no OpenCode harness)

## Aim

1. Seed with **best-of-3 channels** (Graphify, BM25, dense) then D path/lexical rerank.
2. Agent traverse with **grep + graph** (dedicated easy `query_graph`) + small spans.
3. Measure token efficiency / rubric on **Cursor Task agents**, not OpenCode.

## Retrieval — `D_channel_best`

```text
query
  → Graphify top-N files ∥ BM25 top-N files ∥ dense top-N files  (N=4)
  → union + channels_hit tags
  → D lexical/path score → top-K
```

- Env: `CTX_RETRIEVE=D_channel_best` (classic `D` unchanged).
- Hit `source`: `D_channel_best:graph+bm25` (etc.) so agents see why a seed landed.

## MCP surface (lean)

| Tool | Role |
|------|------|
| `search_code` | Blind arrow via current `CTX_RETRIEVE` |
| `query_graph` | NL graph query (easy graph-only path) |
| `grep_code` / `grep_ident` | Lexical traverse |
| `read_span` / `graph_neighbors` | Small spans / path neighbors |
| `status` | Health |

Workflow hint: search → query_graph/grep → read_span. Prefer spans over full files.

## Cursor-only A/B

Two Cursor Task agents, same mission (`testdata/frontend-mcp`, T1–T3 from opencode mission):

| Arm | Tools |
|-----|--------|
| `graphify` | Graphify CLI / `query_graph` + `get_neighbors` only |
| `d_channel_best` | CE MCP: `search_code` + `query_graph` + grep + spans |

**Primary:** rubric pass (must_touch) then estimated tool/context tokens.  
**Invalid run:** zero tool calls.

## Non-goals

- OpenCode harness for this slice.
- Replacing production default until Cursor A/B shows a win.
