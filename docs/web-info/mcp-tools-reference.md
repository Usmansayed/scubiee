# MCP tools reference

Detailed guide to the Scubiee **MCP tools** — what the one `map` tool's configs do, when to use each, and the typical agent workflow.

These tools appear in your IDE after `scubiee connect --cursor` (or another tool) and an MCP reload. They are **not** CLI commands (though `scubiee map --config …` mirrors them for scripts).

MCP server name: **`scubiee`** · worker module: **`pipeline.map_v3_server`** (Map V3)

Setup: [Cursor & MCP](./cursor-mcp.md) · CLI equivalents: [Commands reference](./commands-reference.md)

---

## Before you use tools

1. Machine setup: `scubiee setup --repair`
2. Repo enrolled: `scubiee init .`
3. IDE connected: `scubiee connect --cursor` → reload MCP
4. At chat start: call **`gate()`** once (see below)

If `gate` returns `0` (not managed), run `init` / `connect` in that workspace — do not keep calling Scubiee tools.

If Scubiee is globally stopped (`scubiee stop`), tools are blocked until the user runs **`scubiee resume`**.

---

## The tool surface

Scubiee ships **one locate tool, `map`**, with four configs, plus two health tools. That is the entire surface.

| Tool | One-line purpose |
|------|------------------|
| `gate` | Tiny managed check (~5 tokens) — call once at session start |
| `status` | Engine health one-liner (ok / warm / dense / chunks / version) |
| `map config=find` | "Where is the code for X?" — ranked locations **+ the top result's code inline** |
| `map config=focus` | "Show me this name" — its full body + callers/callees + sibling names, one unit |
| `map config=related` | "Given a chunk I have, what else relates?" — related bodies in one call |
| `map config=graph` | "Orient me" — files → symbol names + call edges, **no bodies** |

Exact literals / filenames / known paths → **host** Grep/Glob/Read (not Scubiee). History → `git`.

There is no surface switching and no `CTX_MCP_SURFACE` / `CTX_MCP_EXPERIMENT` any more — the Map V3 surface is the single shipped surface.

---

## Session binding: `root` and `project_id`

The worker resolves the repo from `CTX_REPO` (set by `scubiee connect`). The health tools echo the managed id:

| Signal | Meaning |
|--------|---------|
| `gate` → `1:ce_…` | Managed repo, bound and resolvable |
| `gate` → `0` | Not managed — run `scubiee init .` |
| `gate` → `p` | Globally paused — run `scubiee resume` |

**Cursor multi-root:** connect from the specific workspace folder so its `.kiro`/`.cursor` `mcp.json` pins `CTX_REPO` to the correct repo.

---

## Recommended agent workflow

```text
gate() once
    ↓ managed (1:ce_…)?
map config=find query="<short code-vocab intent>" keywords=[names you know]
    ↓ top result is the place? EDIT it — the code is already inline, don't re-view
    ↓ have a name and want its wiring?
map config=focus names=[Symbol]          ← full body + callers/callees + siblings, one unit
    ↓ have a chunk and want what relates?
map config=related anchor="file::symbol" query="<intent>"
    ↓ don't know where to start at all?
map config=graph query="<intent>"        ← orient wide, THEN one find/focus
```

Pick **one** config, act on the first good answer, and **stop**. Don't chain configs just to look around. Don't poll `status()` in a loop while warming — retry the `map` call once after a short wait.

---

## Tool reference

### `gate`

**When:** Start of every chat (preferred over full `status` for token cost).

**Returns:** `1:ce_<project_id>` when managed, `0` when unmanaged, `p` when globally paused.

---

### `status`

**When:** You want engine health (is it warm / dense yet?).

**Returns:** one line — `ok=… warm=… dense=… phase=… chunks=… version=…`.

**Not for:** finding code — use `map`.

---

### `map`

One tool, one required field `config`. Each config takes a few arguments.

#### `config=find` — locate by concept

```json
{"config": "find", "query": "where the token savings summary is computed", "keywords": ["tokens_saved", "compare_queries"]}
```

| Argument | Default | Why |
|----------|---------|-----|
| `query` | required | Short code-vocab intent (~25–120 denser tokens: symbols, paths, APIs, verbs). |
| `keywords` | `[]` | Exact names you already know; weighted in ranking. |
| `scope` | `code` | `code` · `tests` · `docs` · `all`. |
| `k` | 8 | Max results. |

Returns ranked locations with line numbers; on a confident top hit, its **enclosing function/class is included inline**. If that's the place, edit it — don't call another config to view it.

#### `config=focus` — a name's code and wiring

```json
{"config": "focus", "names": ["git_dirty_files"]}
```

| Argument | Default | Why |
|----------|---------|-----|
| `names` | required | Identifier(s) to center on. |
| `anchor` | — | Or a `file::symbol` chunk you already have. |
| `scope` | `code` | As `find`. |

Returns the symbol's full body **plus** its callers/callees and the other symbol names in its file — one unit you can edit from without a follow-up call.

#### `config=related` — related code for a chunk you have

```json
{"config": "related", "anchor": "token_meter.py::compare_queries", "query": "where savings get rendered"}
```

| Argument | Default | Why |
|----------|---------|-----|
| `anchor` | required | The chunk you already have (`file::symbol` or `file:line`). |
| `query` | required | What relation you're after. |
| `scope` | `code` | As `find`. |

Returns the code elsewhere that relates to the anchor and matches the query, with bodies — one call instead of a grep-and-read chain.

#### `config=graph` — orient wide

```json
{"config": "graph", "query": "how freshness decides the sync strategy"}
```

| Argument | Default | Why |
|----------|---------|-----|
| `query` | one of these | Concept to orient around. |
| `anchor` | one of these | Or a known `file::symbol` to center the neighborhood. |

Returns an abstract JSON map — files → top-level symbol names plus call edges, **no bodies**. Cheap and wide: use it to decide where to go, then make one `find`/`focus`.

---

## Registering a repo from the agent

`scubiee init .` (CLI) is the normal path. If an MCP host exposes a register action, large repos may return a confirm-required payload — the user then runs `scubiee init . --confirm`.

---

## CLI equivalent

The shipped CLI mirrors the tool exactly (useful for scripts / when MCP is unavailable):

```text
scubiee map --config find  "<intent>" [--k N]
scubiee map --config focus --names Symbol [OtherSymbol]
scubiee map --config related --anchor "file::symbol" "<intent>"
scubiee map --config graph "<intent>"
```

---

## Troubleshooting MCP tools

| Symptom | Fix |
|---------|-----|
| `gate` says `0` (unmanaged) | `scubiee init .` + `scubiee connect --cursor` + reload MCP |
| `status` warm=false forever | `scubiee engine ensure . --wait 45` |
| Tools blocked / `gate` = `p` | User: `scubiee resume` (global) or `scubiee activate .` (per-repo) |
| Stale hits after edits | `scubiee sync .` |
| Wrong repo in multi-root | Connect from that workspace folder so `CTX_REPO` is pinned correctly |

---

## Related

- [Cursor & MCP](./cursor-mcp.md)
- [Indexing & projects](./indexing-and-projects.md)
- [Daily use](./daily-use.md)
- [Troubleshooting](./troubleshooting.md)
- [Commands reference — MCP section](./commands-reference.md#mcp-tools-inside-cursor)
