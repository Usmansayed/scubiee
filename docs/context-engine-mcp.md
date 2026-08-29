# Context Engine MCP — Architecture & Tool Reference

A local, stdio MCP server (`context-engine`) that gives coding agents **fast,
token-cheap code understanding**: semantic search, the right span, file
structure, and the call graph. It deliberately covers only what native
Grep/Read/Glob *can't* do — see [Design rationale](#design-rationale).

- Module: `pipeline.mcp_locate` (Python / FastMCP)
- Transport: **stdio** (single client, local; logs go to stderr, never stdout)
- Read-only: every tool is `readOnlyHint: true`, `idempotentHint: true`,
  `openWorldHint: false` (operates only on the indexed local repo)
- Config: `CTX_REPO`, `CTX_MCP_SURFACE`, `CTX_ENGINE_URL`, `CTX_TOKEN_MODE`,
  `CTX_RETRIEVE` (see [Configuration](#configuration))

---

## Architecture

```text
        Coding agent (Cursor / Claude / SDK)
                     │  stdio (JSON-RPC)
                     ▼
        pipeline.mcp_locate  (FastMCP server)
          phase: map · focus · grep · glob · workspace · expand · status
                     │  HTTP (CTX_ENGINE_URL)
                     ▼
        Engine daemon  (per-repo, warmed once)
     ┌───────────────┼────────────────────────┐
     ▼               ▼                         ▼
  Embeddings       BM25 lexical            Graphify graph
  (FAISS +         (identifier /           (defs, calls,
   turboquant)      token match)            imports, 1-hop)
     └───────────────┴────────────────────────┘
                     │  fused ranking
                     ▼
        D_channel_best  (embeddings + BM25 + graph)
                     │
                     ▼
        Session store  (content-hash span dedupe)
```

**Retrieval channel (`D_channel_best`).** Every `search` and symbol-resolving
`read` runs one fused ranker: dense embeddings for meaning, BM25 for exact
identifiers/tokens, and the Graphify graph for structure (definitions, callers,
callees, imports). Fusion beats any single signal on vague ("where do we X") and
precise ("`getUserConfig`") queries alike.

**Engine daemon.** A per-repo background process holds the vector index, lexical
index, and graph in memory so tool calls are warm. It is addressed over
`CTX_ENGINE_URL` (default `http://127.0.0.1:8765`) and started/pointed at the
repo on first use. `status()` reports health and which repo is served.

**Session store.** `read` is deduplicated by content hash: re-reading the same
span returns a lightweight `unchanged` stub carrying the span's `handle`, so the
agent never pays twice for the same bytes in a session. Span `handle`s can be
re-materialized later with `read(handle=…)`.

**Surfaces.** The registered tool set is chosen by `CTX_MCP_SURFACE`. The
production soft-insert surface is `rich` / `read`. `nav` is the sealed
retrieval environment for A/B trials:

| `CTX_MCP_SURFACE` | Tools | Purpose |
|---|---|---|
| **`phase` (managed default)** | `gate`, `map`, `focus`, `grep`, `glob`, `workspace`, `expand`, `status` | Token-efficient locate trajectory — map for meaning, focus to deepen, grep/glob for literals/paths |
| `rich` (legacy prod) | `search`, `read`, `outline`, `status` | Value-add only |
| `read` | `search`, `read`, `status` | Minimal locate+read |
| `nav` | `search`, `files`, `read`, `recall`, `expand`, `status` | Sealed locate (soft+exact+files+session) |
| `search` | `search`, `status` | Single semantic tool |
| `graph` | `search`, `neighbors`, `graph`, `status` | Graph-tool A/B |
| `grep` | `grep`, `status` | Exact-only (paired w/ external graph) |

### Phase surface (`CTX_MCP_SURFACE=phase`)

Production default for managed repos after `scubiee init`. Agents should use:

| Tool | When |
|---|---|
| `map(query)` | Cold / new topic — ranked cards, no bodies |
| `focus(target, mode=outline\|span\|neighbors)` | Deepen a map hit — symbols, code span, import neighbors |
| `grep(pattern, glob=…)` | Exact literals only |
| `glob(pattern=…)` | File paths by name (`glob=` alias accepted; prefer `pattern=`) |
| `expand(handle)` | Re-materialize a stored span after dedup |
| `workspace(show)` | Mid-session heatmap / reorientation |
| `status()` | Health; check top-level `agent_ready`: `yes` \| `warming` \| `stale` |

**Phase behaviors (2026-08):**

- Duplicate `map(query)` returns **cached** cards (`cached: true`) without re-querying the daemon.
- Nonsense/vague maps may return `confidence: low` with at most 3 cards and `weak_match: true`.
- `glob(pattern="packages/*")` lists immediate child directories under `packages/`.
- Transient daemon drops auto-retry once; errors include `should_retry: true`.
- Managed `gate()` echoes `sid:…` when session isolation is shared across chats.

Recommended flow: `map` → `focus(outline)` → `focus(span)` → edit → `grep` for literals.

---

## Tools

All tools accept `response_format="json"` (default, machine-readable) or
`"markdown"` (human-readable). All are read-only and idempotent.

### `search(query, k=8, mode=soft, fetch=false, max_chars=1200)`

**When:** the default first reach for any new / vague / "where does X happen" /
"how does Y work" question. Finds code by **meaning** (embeddings + BM25 + graph
fused) — not just string match. On the `nav` surface, `mode=exact` runs
literal/regex grep through the same tool (sealed exact locate).

**Params:** `query` (NL or symbol; soft asks welcome) · `k` how many hits
(r5=5 tight, r10=10 wide, max 25) · `mode` `soft` (default) or `exact` ·
`fetch=true` inlines each hit's code body (soft only) · `max_chars` per-hit body budget.

**Returns (soft):** `results[{rank, file, start_line, end_line, score, why, code?}]`.  
**Returns (exact):** `hits[{file, line, text}]`.

**Examples**
```jsonc
search(query="where is a search query tokenised before retrieval")
search(query="getUserConfig", k=5, fetch=true)   // inline bodies
search(query="perception_code_graph", mode="exact")  // sealed literal
```

### `read(target|path, query, handle, start_line, end_line, detail=body, neighbors=false, max_neighbors=4, max_chars=2000)`

**When:** open one specific thing before editing — a symbol, a search hit, a
known file, or an exact line range. Session-deduped: a repeat read returns an
`unchanged` stub with the span's `handle`. On `nav`, `detail=outline` folds the
old outline tool; `detail=neighbors` is the same as `neighbors=true`.

**Params (pick one locator):** `target` symbol / phrase / `"path"` / `"path:line"`
· `path` explicit repo-relative file (skips search) · `query` picks the best span
within `path` · `handle` re-materializes a span seen earlier · `start_line`/
`end_line` exact range with `path` · `neighbors=true` attaches the span's 1-hop
**callers** (who breaks) and **callees** (what it depends on) from the graph ·
`max_neighbors` caps that payload (1..10) · `max_chars` span body budget.

**Returns:** `{ok, file, start_line, end_line, code, handle, mode}` and, when
`neighbors=true`, `neighbors[{file, start_line, end_line, relation, code?}]` +
`neighbors_count`. Skipped automatically when nothing resolves, so it costs
nothing when off.

**Examples**
```jsonc
read(target="ResolverIntelligenceService")           // by symbol
read(path="src/navigation/mcp/tools.py", query="tool registration")
read(target="handle_detect_framework", neighbors=true) // + call graph before editing
read(path="src/foo.py", start_line=40, end_line=88)    // exact range
```

### `outline(path, keep=60)`

**When:** understand a file's shape fast — its classes/functions and their line
ranges — without reading the whole file.

**Returns:** `symbols[{name, kind, start_line, end_line}]` (capped at `keep`).

**Example**
```jsonc
outline(path="src/navigation/mcp/handlers.py")
```

### `status()`

**When:** health check, or to see session size / which tools are registered.
**Returns:** engine reachability, served `repo`, active surface + tool list,
session span count, token mode.

---

## Design rationale

The surface is **intentionally lean — only tools that beat native**, and the
always-on guidance is a **tiny Need→do card** (MCP server instructions + Cursor
rule), not a long doc the agent must open. Goal: Grep-like muscle memory —
soft locate → `search`, open span → `read`, exact string → native Grep — with
defaults that prevent stacking CE on top of Grep/Read thrash.

- `search` (meaning), `read` (right span + call graph), `outline` (structure)
  do things native Grep/Read/Glob cannot.
- `grep` and `files`/glob were **removed** from the production surface. Wrapping
  native grep/glob added no capability, only tool-schema/context overhead. An
  A/B on the `frontend-mcp` codebase confirmed it: forcing every grep/read
  through the MCP pushed MCP-share to ~100% but *raised* total tokens vs. a
  version where `search` simply deflected reads. Token savings come from
  `search` replacing reads — not from re-routing native-equivalent ops.

So: **use the MCP for meaning, structure, and the graph; use native Grep/Glob
for an exact string or a known filename.** Fewer tools + short instructions =
smaller prompt and a sharper decision for the agent.

Backed by ~200 TraceLab sessions: locate + read are ~46% of agent tool calls,
which is exactly what `search` + `read` target.

---

## Configuration

Set via the MCP server's `env` (stdio):

| Var | Default | Meaning |
|---|---|---|
| `CTX_REPO` | cwd | Repo the engine indexes/serves |
| `CTX_MCP_SURFACE` | `read` | Tool surface (`nav` sealed; `rich` soft prod) |
| `CTX_ENGINE_URL` | `http://127.0.0.1:8765` | Engine daemon address |
| `CTX_RETRIEVE` | `D_channel_best` | Fused ranking channel |
| `CTX_TOKEN_MODE` | `savings` | Trim payloads to save tokens |

Example (Cursor `mcp.json`):
```jsonc
"context-engine": {
  "command": "<repo>/.venv/Scripts/python.exe",
  "args": ["-u", "-m", "pipeline.mcp_locate"],
  "env": {
    "PYTHONPATH": "<repo>/packages",
    "CTX_REPO": "<workspace>",
    "CTX_MCP_SURFACE": "rich",
    "CTX_TOKEN_MODE": "savings",
    "CTX_ENGINE_URL": "http://127.0.0.1:8765"
  }
}
```

---

## Error handling

Errors are returned **inside** the result object (not as protocol errors), shaped
`{ok:false, tool, error, hint}` where `hint` suggests a next step, e.g.:

- `search` validation → `"query required; k in 1..25."`
- `search` engine cold → `"Check status()/CTX_REPO; ensure index is warm."`
- `read` no locator → prompts for `target` / `path` / `handle`.

Agents should read `hint`/`next` and adjust (sharpen the query, raise `k`, warm
the engine, or fall back to native Grep for an exact string).

---

## Testing

- Unit: 	ests/test_mcp_locate.py (surface composition including 
av,
  search(mode=exact), 
ead(detail=…), dedupe, neighbors, line ranges).
- Live/preflight: scripts/experiments/_run_trial_unrestricted.py --preflight warms the
  engine and probes search, 
ead(neighbors=true), and outline against a
  real workspace before any paid agent run.
- Sealed A/B: sdk_mcp_dev_trial.py --arms ce_nav,raw --surface nav --seal-locate
