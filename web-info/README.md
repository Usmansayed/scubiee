# Scubiee web-info — detailed documentation hub

> **Version:** [0.3.15](https://pypi.org/project/scubiee/0.3.15/)  
> **Purpose:** In-depth documentation with **explanations** — so operators, support, and website writers understand *why* things work and *how* to fix them.  
> **End-user quick guides:** [`../docs/web-info/`](../docs/web-info/README.md) (shorter, task-focused)

Use this folder when you need **detail**, not just commands.

---

## Start here

| I need to… | Read |
|------------|------|
| **Understand the whole product** (concepts, flow, components) | **[How everything works](./how-everything-works.md)** |
| **Fix a problem** (symptom → cause → fix → verify) | **[Complete fix guide](./complete-fix-guide.md)** |
| **Look up an error code or JSON field** | **[Error codes & messages](./error-codes-reference.md)** |
| **Know what every file/path means** | **[Data & files reference](./data-and-files-reference.md)** |
| **Write website / marketing copy** | [Product guide for website](./product-guide-for-website.md) |
| **Short marketing snippets** | [Website content](./website-content.md) |
| **Every CLI command & flag (exhaustive + context)** | **[Complete CLI reference](./complete-cli-reference.md)** — workflows, mental model, troubleshooting, disk effects |
| **Command tables (short)** | [Commands and setup](./commands-and-setup.md) |
| **Engineering architecture** | [Context engine internals](./context-engine-internals.md) |

---

## docs/web-info cross-links (operator docs)

These live in `docs/web-info/` — shorter paths for day-to-day use. They link back here for depth.

| Topic | Operator doc | Detailed depth |
|-------|--------------|----------------|
| Install / upgrade / debug | [install-and-debug.md](../docs/web-info/install-and-debug.md) | [Complete fix guide § Install](./complete-fix-guide.md#install-and-upgrade) |
| Troubleshooting index | [troubleshooting.md](../docs/web-info/troubleshooting.md) | [Complete fix guide](./complete-fix-guide.md) |
| MCP + Cursor | [cursor-mcp.md](../docs/web-info/cursor-mcp.md) | [How everything works § MCP](./how-everything-works.md#mcp-and-the-agent) |
| MCP tools (parameters) | [mcp-tools-reference.md](../docs/web-info/mcp-tools-reference.md) | Same + [How everything works](./how-everything-works.md) |
| Repo wipe / pause / unmanage | [repo-lifecycle.md](../docs/web-info/repo-lifecycle.md) | [How everything works § Lifecycle](./how-everything-works.md#repository-lifecycle) |
| Indexing rules | [indexing-and-projects.md](../docs/web-info/indexing-and-projects.md) | [Data reference § Project store](./data-and-files-reference.md) |
| All CLI commands | [commands-reference.md](../docs/web-info/commands-reference.md) | **[Complete CLI reference](./complete-cli-reference.md)** |

---

## Document map (this folder)

```
web-info/
├── README.md                      ← you are here
├── how-everything-works.md        ← concepts & flows (read first for understanding)
├── complete-fix-guide.md          ← fix anything (symptom → why → fix → verify)
├── error-codes-reference.md       ← JSON errors, exit codes, status fields
├── data-and-files-reference.md    ← ~/.scubiee, .scubiee, MCP paths, logs
├── product-guide-for-website.md   ← marketing / website bible
├── website-content.md             ← short copy snippets
├── complete-cli-reference.md      ← every command, flags, JSON glossaries, FAQ, platforms
├── commands-and-setup.md          ← command tables for docs site
└── context-engine-internals.md    ← engineering architecture
```

---

## First-time learning path

1. **[How everything works](./how-everything-works.md)** — setup, init, connect, daemon, index, MCP (30 min read)
2. **[Data & files reference](./data-and-files-reference.md)** — where things live on disk
3. **[Complete fix guide](./complete-fix-guide.md)** — bookmark for when something breaks
4. **[Error codes reference](./error-codes-reference.md)** — when JSON shows an `error` field

---

## Support bundle (always collect these)

```bash
scubiee --version
scubiee setup --status
scubiee doctor .
scubiee list
scubiee diagnose --no-tests --desktop
```

Attach `Desktop/scubiee-diagnose.json` and (if relevant) tail of `~/.scubiee/engine.log`.

---

## Brand & paths (never confuse in docs)

| Correct | Wrong (legacy) |
|---------|----------------|
| Scubiee | context-engine (product name) |
| MCP key `scubiee` | `context-engine` in mcp.json |
| `~/.scubiee` | `~/.context-engine` |
| `<repo>/.scubiee` | `<repo>/.context-engine` |
| `scubiee resume` | `scubiee wake` |
| `scubiee activate` (per-repo unpause) | `scubiee resume` for per-repo pause |
