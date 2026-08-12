# Agent Tools and MCP

This document covers how AI agents interact with Context Engine — what tools they see, what parameters exist, and how the system guides their behavior.

## MCP server

**File:** `packages/pipeline/mcp_locate.py`

Context Engine exposes tools to agents via MCP (Model Context Protocol) over stdio. The server uses the `mcp` library's `FastMCP` class. One process, one MCP connection, typically spawned by the IDE (Cursor, Kiro, OpenCode) as a subprocess.

## Surfaces — configurable tool sets

The `CTX_MCP_SURFACE` environment variable controls which tools are exposed. Each surface is designed for a different agent interaction pattern:

| Surface | Tools | Use case |
|---------|-------|----------|
| **read** (default) | search, read, status | Standard: search then read a span |
| **nav** | search, files, read, recall, expand, status | Sealed retrieval for A/B trials |
| **graph** | search, neighbors, graph, status | Graph-focused structural queries |
| **rich** | search, read, outline, status | Value-add tools native grep can't do |
| **search** | search, status | Single semantic tool only |
| **grep** | grep, status | Literal text search only |

The production surface is **read**: just search + read + status. Simple, minimal overhead, handles 90%+ of agent needs.

## Tool: search

The primary discovery tool. Agents ask questions in natural language.

**Parameters:**
- `query` (required): Natural language or symbol query, 1-2000 chars
- `k` (default 8): Number of results, 1-25
- `include` (default "hits"): What to return
  - `hits` — file + lines + score + why (compact pointers)
  - `span` — also include code body for top 1-3 hits
  - `graph` — also include 1-hop neighbor files for top hit
- `mode` (default "soft"): `soft` for semantic, `exact` for literal regex
- `max_chars` (default 1200): Per-hit body budget when include=span

**Returns:** List of results with `{rank, file, start_line, end_line, score, why}` and a `next` hint telling the agent what to do next.

**Anti-thrash:** The nav/search surfaces enforce budgets — max 4-6 soft searches per session, max 3 exact searches. Duplicate queries are blocked. This prevents agents from endlessly re-searching without editing.

## Tool: read

Open the right span before editing. Handles multiple resolution strategies.

**Parameters:**
- `target`: Symbol name, phrase, or path (resolved via search if needed)
- `path`: Explicit repo-relative file (skips search)
- `query`: When path is set, find the span matching this within the file
- `handle`: Re-materialize a previously stored span
- `start_line` / `end_line`: Explicit line range
- `detail`: `body` (default), `outline` (just defs), or `neighbors` (attach callers/callees)
- `neighbors` (bool): Attach 1-hop graph neighbors
- `max_chars` (default 2000): Body budget

**Session dedup:** Results are stored in the session store by content hash. If the same span is requested again, the tool returns `already_in_session` instead of re-sending the body — saving tokens.

## Tool: files

Find files by name or glob pattern.

- `pattern='.'` returns shallow repo shape (top-level dirs + files)
- `pattern='*.md'` or `pattern='query_*'` does glob/name matching

## Tool: recall

List what the current session already fetched — handles only, no file bodies. Lets the agent check what it knows before searching again.

## Tool: expand

Re-materialize a stored span by its handle. Used when the agent needs the full body of something it previously received as a compact pointer.

## Tool: neighbors

1-hop graph callers/callees of a symbol or file. Shows what depends on the target and what it depends on.

## Tool: graph

Natural language structural/relationship query — "how does A connect to B?" Uses graph affinity scoring rather than pure text similarity.

## Tool: outline

File structure — lists all classes, functions, methods with their line numbers. Useful for orientation before reading specific spans.

## Tool: grep

Exact/literal text search. Bypasses the embedding system entirely. Used for configuration keys, error messages, import paths — things where exact string matching is better than semantic similarity.

## Tool: status

Health check. Returns engine health, surface name, available tools, session state.

## Session store

**File:** `packages/pipeline/session_store.py`

The session store (`<repo>/.context-engine/session_store.json`) tracks what the agent has seen:

- **Spans:** Full text stored server-side, keyed by content hash. Agents get compact handles.
- **Handles:** Short IDs (`sp_001`, `sp_002`, ...) that reference stored spans.
- **Ledger:** Tracks served handles and approximate prompt tokens.
- **Dedup:** If the same content is requested twice (same file + same lines + same content hash), the tool returns `already_in_session` with no body — just a hint to `expand(handle)` if needed.

This is the core token-saving mechanism: agents never receive the same code body twice per session.

## Agent instructions (per surface)

Each surface has a short instruction string injected into the agent context. These are designed to be like "muscle memory" — quick rules for when to use which tool.

Example (read surface):
```
Context Engine (CE) = your default code locate. Tools: search | read | status.
Use CE instead of Grep for almost all discovery. Grep is rare.

Need → do this:
- Soft / unfamiliar / "where|how|who" → search(query) — NEVER Grep first
- After search hits → ALWAYS read(target) before edit
- Exact literal ONLY after two thin searches → Grep once (≤2 Greps/task)

Flow: search → read → edit → test.
```

The instructions are kept very short to minimize per-turn token cost. They establish one key behavioral rule: **search first, read second, edit third**.

## The .cursor/rules/context-agent.mdc file

For Cursor IDE specifically, a rule file reinforces the same pattern:
- Prefer CE search over native grep for all discovery
- Use CE read before editing (not native full-file Read)
- Grep is rare — only for exact literals after two thin searches
- Flow: search → read → edit → test

## Token mode

The `CTX_TOKEN_MODE` environment variable controls how aggressively the system saves tokens:

- **savings** (default): Compact responses, tiny excerpts, handles instead of bodies, session dedup active.
- **rich**: Larger excerpts, more graph context, less compression — for debugging or when token budget is generous.

## Previous MCP surface experiments

The codebase shows evidence of extensive experimentation with different tool configurations:

1. **read** — settled as default (search + read + status)
2. **nav** — sealed retrieval for A/B trials (search + files + read + recall + expand + status)
3. **graph** — tried exposing graph tools directly to agents (neighbors + graph)
4. **rich** — "value-add only" tools that native grep/glob can't do
5. **search** — single search tool, maximum simplicity
6. **grep** — literal-only surface for baselines

The convergence toward `read` (3 tools) reflects the finding that simpler tool sets reduce agent confusion and produce better results with fewer total tool calls.

## hybrid_cbm — CE + Codebase Memory facade

**File:** `packages/hybrid_cbm/`

An experimental MCP facade combining CE semantic search with stock CBM (Codebase Memory) structural tools:
- `search` → CE soft semantic search
- `search_graph` → CBM structural graph query
- `trace_path` → CBM caller/callee tracing
- `get_code_snippet` → CBM snippet by qualified name
- `status` → health check for both

This exists for A/B testing CE's semantic search against CBM's graph-only approach while keeping the same MCP interface.
