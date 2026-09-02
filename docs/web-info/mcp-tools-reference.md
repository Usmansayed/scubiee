# MCP tools reference

Detailed guide to Scubiee **MCP tools** — what each tool does, when to use it, and typical agent workflow.

These tools appear in your IDE after `scubiee connect --cursor` (or another tool) and an MCP reload. They are **not** CLI commands.

**Docs assume [scubiee 0.3.14](https://pypi.org/project/scubiee/0.3.14/)** · MCP server name: **`scubiee`**

Setup: [Cursor & MCP](./cursor-mcp.md) · CLI equivalents: [Commands reference](./commands-reference.md)

---

## Before you use tools

1. Machine setup: `scubiee setup --repair`
2. Repo enrolled: `scubiee init .`
3. IDE connected: `scubiee connect --cursor` → reload MCP
4. At chat start: call **`gate()`** or **`status()` once** (see below)

If `managed: false`, run `init` / `connect` in that workspace — do not keep calling Scubiee tools.

If Scubiee is globally stopped (`scubiee stop`), MCP tools are blocked until the user runs **`scubiee resume`**.

---

## Default tool surface: `phase`

Cursor and most installs use the **`phase`** surface (default). Tools exposed:

| Tool | One-line purpose |
|------|------------------|
| `gate` | Tiny managed check (~5 tokens) — call once at session start |
| `status` | Full engine health + session (or `detail=gate` for tiny check) |
| `map` | New topic — ranked file/symbol **cards** (no bodies) |
| `focus` | Deepen a hit — outline, span, neighbors, call sites |
| `grep` | Exact literal / regex search in **indexed** files |
| `glob` | Find files by path pattern in the index |
| `workspace` | Session memory — pins, heatmap, focus history |
| `expand` | Re-open a stored span by handle |
| `register_project` | Consent-based enroll + index from MCP |

Advanced installs may set `CTX_MCP_SURFACE` to `nav`, `search`, `grep`, etc. — different tool names apply. This doc covers **`phase`** (product default).

---

## Session binding: `root` and `project_id`

Most tools accept optional:

| Parameter | Purpose |
|-----------|---------|
| `root` | Absolute or workspace path to bind this call to a specific repo |
| `project_id` | `ce_…` id from a prior successful `status()` — avoids repeating full path |
| `session_id` | Isolate parallel chats when MCP process is shared |

**Cursor multi-root:** pass `root` = that chat’s workspace path on the first `gate()` / `status()` so managed checks apply to the correct folder.

---

## Recommended agent workflow

```text
gate() or status() once
    ↓ managed + ok?
map(query)          ← new topic / cold start
    ↓ pick 1–3 cards
focus(target, mode=outline|span|neighbors)
    ↓ need exact string?
grep(pattern, glob=…)
    ↓ mid-task reorient?
workspace(action=show)
    ↓ new topic in same chat?
workspace(action=clear) → map() again
```

**Do not** poll `status()` in a loop when `warming: true` — retry the **locate tool** once after a short wait.

---

## Tool reference

### `gate`

**When:** Start of every chat (preferred over full `status` for token cost).

**Returns:** Short line like `1:ce_<project_id>` when managed and healthy; hints when shared MCP risk.

**Parameters:** `root`, `project_id`, `session_id`

---

### `status`

**When:** You need full health JSON, tool list, warming flags, or lifecycle guidance.

**Not for:** Finding code — use `map` / `grep`.

| Parameter | Values |
|-----------|--------|
| `detail` | `full` (default) — engine + session · `gate` — same tiny line as `gate()` |
| `root`, `project_id`, `session_id` | Session binding |

**Key response fields:**

| Field | Meaning |
|-------|---------|
| `managed` | This workspace is enrolled |
| `ok` | Daemon healthy — safe to use locate tools |
| `warming` | Managed but daemon still starting — retry locate tool once |
| `paused` | Global stop — user must `scubiee resume` |
| `next_action` | CLI hint when not ready |

---

### `map`

**When:** New topic, unfamiliar code, “where is X handled?”

**Returns:** Ranked **cards** (paths, symbols, scores) — **no source bodies**.

| Parameter | Notes |
|-----------|-------|
| `query` | Code vocabulary, 20–60 tokens — full question style |
| `k` | Number of cards (default 8) |
| `response_format` | `json` or `markdown` |

**Next step:** `focus(target=…)` on 1–3 cards. Empty map ≠ symbol absent — try rephrasing or `grep` for a known literal.

---

### `focus`

**When:** You have a map hit (or known path/symbol) and need code context.

| Parameter | Notes |
|-----------|-------|
| `target` | File path, `path:line`, or symbol from a map card |
| `mode` | `outline` · `span` (default) · `neighbors` · `call_sites` |
| `path` | Explicit repo-relative file |
| `budget` | `cap` (~200 lines) · `wide` (~350) · `full` (~1k) |
| `query` | Helps pick span inside `path` |
| `start_line` / `end_line` | Optional line range |

**Modes:**

- **outline** — symbols/structure in a file
- **span** — source text around the target
- **neighbors** — related imports/callers/callees
- **call_sites** — where a function/name is referenced

---

### `grep`

**When:** You need an **exact** string, import line, config key, or regex — not meaning-based search.

| Parameter | Notes |
|-----------|-------|
| `pattern` | Literal or regex |
| `glob` | Default `**/*` — narrow to e.g. `packages/**/*.py` |
| `max_hits` | Default 200 |

**Note:** Searches **indexed** content. `truncated: true` means more matches may exist — raise `max_hits` or narrow `glob`.

Prefer **`map`** for “where / how / who” questions; use **`grep`** for known literals.

---

### `glob`

**When:** You know a filename or path pattern, not file contents.

Finds paths present in the index. Empty result with `truncated: false` usually means no indexed file matched the pattern.

---

### `workspace`

**When:** Mid-session — see what you already focused, pin a file, or reset for a new topic.

| `action` | Behavior |
|----------|----------|
| `show` | Pins, heatmap, recent map queries, focus history |
| `pin` | Pin a repo-relative `path` for this session |
| `clear` | Reset session store — then `map()` for a new topic |

---

### `expand`

**When:** You have a **handle** from a prior `focus` / session and need that span again without re-searching.

Pass the handle string from earlier tool output. If stale, run `map` or `focus` again.

---

### `register_project`

**When:** User consent to enroll a repo from the agent (alternative to CLI `scubiee init`).

| Parameter | Notes |
|-----------|-------|
| `path` | Repo root (default: bound workspace) |
| `always_allow` | Skip future consent prompts |
| `fast` | Fast index mode (`.py` under standard roots) |

Large repos may return a confirm-required payload — user runs CLI `scubiee init . --confirm`.

---

## Other MCP surfaces (advanced)

Set via MCP env `CTX_MCP_SURFACE`:

| Surface | Main tools | Use case |
|---------|------------|----------|
| `phase` | map, focus, grep, glob, workspace, … | **Default** — structured locate trajectory |
| `nav` | search, files, read, recall, expand | Alternate sealed retrieval path |
| `search` | search, status | Minimal semantic locate |
| `grep` | grep only | Literal search host |
| `read` / `rich` / `graph` | varies | Legacy / specialized hosts |

Most users never change this. If your `mcp.json` sets a non-default surface, tool names in the IDE may differ from the table above.

---

## Common response fields

Many tools return JSON with:

| Field | Meaning |
|-------|---------|
| `ok` | Call succeeded |
| `truncated` / `has_more` | Result cap hit — not exhaustive |
| `next` | Suggested next tool call |
| `usage_hint` | Anti-thrash / caching advisory |
| `g` | Compact gate line on tool responses |
| `session_id` | Active session binding |

Optional env **`CTX_MCP_LEAN_ECHO=1`** drops echoed `budget` fields only (opt-in token savings).

---

## Troubleshooting MCP tools

| Symptom | Fix |
|---------|-----|
| All tools say unmanaged | `scubiee init .` + `scubiee connect --cursor` + reload MCP |
| `warming: true` forever | `scubiee engine ensure . --wait 45` |
| Tools blocked / paused | User: `scubiee resume` (global) or `scubiee activate .` (per-repo) |
| Stale hits after edits | `scubiee sync .` |
| Wrong repo in multi-root | Pass `root=` on first `gate()` / `status()` |

---

## Related

- [Cursor & MCP](./cursor-mcp.md)
- [Indexing & projects](./indexing-and-projects.md)
- [Daily use](./daily-use.md)
- [Troubleshooting](./troubleshooting.md)
- [Commands reference — MCP section](./commands-reference.md#mcp-tools-inside-cursor)
