# Agent context tools (post-RAG)

**Date:** 2026-08-06  
**Status:** shipped (MCP + HTTP)

## Aim

After `search_code` (blind arrow), the agent gathers **minimum complete context** via span tools — not full-file dumps, not architecture bake-offs.

```text
search_code  →  entry spans
     ↓
read_span | follow_imports | graph_neighbors | grep_ident
     ↓
reopen_anchors  (related turns)
```

## MCP tools

| Tool | Role |
|------|------|
| `search_code` | Hybrid RAG arrow (pointers + preview) |
| `read_span` | Open one chunk-sized span; records anchor |
| `follow_imports` | AST import → resolve module → spans |
| `graph_neighbors` | Budgeted graph neighbors → spans |
| `grep_ident` | `class\|def Ident` → spans |
| `reopen_anchors` | Session memory reopen |
| `session_anchors` | List known files/symbols |

HTTP: `/v1/read_span`, `/v1/follow_imports`, `/v1/graph_neighbors`, `/v1/grep_ident`, `/v1/reopen_anchors`, `/v1/session_anchors`.

Logic: `packages/pipeline/context_nav.py`.
