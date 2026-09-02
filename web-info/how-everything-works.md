# How everything works

Detailed explanation of Scubiee — what each piece does, how they connect, and why the product behaves the way it does.

**Version:** 0.3.14 · **Audience:** operators, support, technical writers, power users  
**Fix guide:** [complete-fix-guide.md](./complete-fix-guide.md) · **Files on disk:** [data-and-files-reference.md](./data-and-files-reference.md)

---

## Table of contents

1. [Big picture](#big-picture)
2. [The four layers](#the-four-layers)
3. [Machine setup (`setup`)](#machine-setup-setup)
4. [Repository enrollment (`init`)](#repository-enrollment-init)
5. [IDE connection (`connect`)](#ide-connection-connect)
6. [The engine (daemon)](#the-engine-daemon)
7. [What indexing actually does](#what-indexing-actually-does)
8. [Search and retrieval](#search-and-retrieval)
9. [MCP and the agent](#mcp-and-the-agent)
10. [Repository lifecycle](#repository-lifecycle)
11. [Global stop vs per-repo pause](#global-stop-vs-per-repo-pause)
12. [Upgrades and migrations](#upgrades-and-migrations)
13. [Windows-specific behavior](#windows-specific-behavior)

---

## Big picture

Scubiee is **not** an IDE plugin and **not** a cloud service. It is three local programs working together:

```text
┌─────────────┐     ┌─────────────┐     ┌─────────────────────┐
│ scubiee CLI │     │ scubiee-mcp │     │ Scubiee engine      │
│ (you run)   │     │ (IDE runs)  │     │ (background daemon) │
└──────┬──────┘     └──────┬──────┘     └──────────┬──────────┘
       │                   │                        │
       └───────────────────┴────────────────────────┘
                           │
                    ~/.scubiee + <repo>/.scubiee
```

- **CLI** — setup, init, connect, sync, doctor, wipe, upgrade.
- **MCP adapter** — thin process Cursor/Copilot/etc. spawn; forwards tool calls to the engine.
- **Engine** — owns indexes, embeds code, answers search/grep requests.

All three use the **same installed Python package** (`pipeline` module) from uv tool or pip.

---

## The four layers

Think of Scubiee in four layers. Problems usually mean one layer is missing or stale.

| Layer | Question it answers | Key command | On-disk marker |
|-------|---------------------|-------------|----------------|
| **1. Install** | Is the `scubiee` package installed? | `uv tool install scubiee` | `scubiee --version` works |
| **2. Machine setup** | Is GPU/CPU ready + model downloaded? | `scubiee setup --repair` | `~/.scubiee/accel.json` |
| **3. Repo enrollment** | Is *this folder* indexed? | `scubiee init .` | `<repo>/.scubiee/id.json` |
| **4. IDE wiring** | Does the agent know to call MCP? | `scubiee connect --cursor` | `~/.cursor/mcp.json`, rules |

**Why agents say `managed: false`:** Layer 3 or 4 is missing — not a “broken index” by itself.

**Why `init` alone is not enough:** Layer 3 without Layer 4 — index exists but IDE never told to use Scubiee.

---

## Machine setup (`setup`)

### What it does

1. **Detects hardware** — NVIDIA CUDA, Windows DirectML, Apple MLX, or CPU fallback.
2. **Installs runtime wheels** — FastEmbed, ONNX Runtime variant matching profile (may pip-install into uv tool env).
3. **Downloads embedding model** — CodeRankEmbed (~270 MB FP16) via HuggingFace/FastEmbed cache.
4. **Calibrates** — measures embed throughput, writes batch size to `accel.json`.
5. **Optional** — supervisor/autostart hooks on some platforms.

### What it does *not* do

- Does not scan your repository.
- Does not write MCP config.
- Does not start indexing without `init`.

### Why `--repair` exists

Upgrades and broken Windows reinstalls often leave:

- `accel.json` saying “profile dml” while ORT wheels were deleted, or
- missing `fastembed` in the uv tool site-packages.

`setup --repair` re-runs detection and pip installs without requiring a full wipe.

### Profile selection logic (simplified)

| Machine | Typical profile | Why |
|---------|-----------------|-----|
| Windows + discrete AMD/NVIDIA | `dml` | DirectML FP16 embed |
| Windows + Intel iGPU only | `cpu` | DML on iGPU hangs or fails — CPU is reliable |
| Apple Silicon | `mlx` | Metal FP16 path |
| Linux + NVIDIA | `cuda` | CUDA ORT |
| Everything else | `cpu` | Safe default |

---

## Repository enrollment (`init`)

### What it does

1. **Validates path** — refuses silent indexing of `$HOME`, `C:\`, `/` (safety).
2. **Assigns or reads `project_id`** — stable `ce_…` id in `<repo>/.scubiee/id.json`.
3. **Updates registry** — `~/.scubiee/registry.json` lists this path as managed.
4. **Runs index pipeline** — scan → parse (Tree-sitter) → graph → chunk → embed → FAISS.
5. **Starts or attaches daemon** — engine serves this repo’s runtime.

### Project identity

- **One project id** can map to **multiple checkout paths** (e.g. worktrees) in registry.
- **Moving the repo** — if `id.json` moves with it, Scubiee recognizes the project.
- **Deleting `id.json`** — next `init` may create a **new** id → full re-index required.

### Fast mode vs full

- **`--fast`** — only `.py` under standard roots (`packages`, `src`, …) or your `--roots`.
- **Full** — broader walk with skip rules (skips `node_modules`, `.git`, large vendor trees, etc.).

### Confirm gate (>400 files)

Counts **indexable** files (same rules as indexing — not raw file count on disk). Prevents accidental indexing of huge trees without explicit `--confirm`.

---

## IDE connection (`connect`)

### What it writes

| Artifact | Purpose |
|----------|---------|
| User/global MCP config | Tells IDE how to spawn `scubiee-mcp` |
| Project MCP config (Cursor, Special-4) | Absolute `CTX_REPO` pin — **required** because Cursor does not expand `${workspaceFolder}` in global MCP |
| Agent rules (e.g. `.cursor/rules/scubiee.mdc`) | Teaches agent: call `gate`/`status` once, use map/focus when managed |

### Special-4 tools

Kiro, Copilot/VS Code, Cline, Roo Code read **workspace-local** MCP files. Global connect alone is insufficient — run `connect` **inside each project**.

### After every upgrade

Package version changes but MCP env and rules may reference old behavior. **Re-run `connect`** and reload MCP.

---

## The engine (daemon)

### Role

- HTTP server on `127.0.0.1:8765` (default).
- Holds **RuntimeManager** per enrolled repo — index freshness, search, grep.
- **ResourceManager** — pauses embed when free RAM critically low (unless `CTX_RM_DISABLE=1`).
- **Watchdog** — restarts daemon if health check fails (disable: `CTX_WATCHDOG=0`).

### Who talks to it

- MCP adapter (`EngineClient`)
- CLI commands (`search`, `sync`, `engine status`, …)

### Warming

When daemon is starting or repo runtime is cold, MCP may return `warming: true`. **Meaning:** retry the **locate tool** once after a few seconds — do not poll `status()` every agent turn.

### Logs

- `~/.scubiee/engine.log` — daemon stdout/stderr
- `~/.scubiee/watchdog.log` — restart events

---

## What indexing actually does

Pipeline stages (conceptual):

```text
Files on disk
    → Merkle tree (detect changes on sync)
    → Tree-sitter AST parse (multi-language)
    → Graph edges (imports, calls)
    → Chunks (symbol-oriented, optional mix compression)
    → CodeRankEmbed vectors
    → FAISS index + lexical index + manifest
    → Stored under ~/.scubiee/projects/<project_id>/
```

### Incremental sync

`scubiee sync .` recomputes Merkle diff — only changed files re-parsed and re-embedded. Background daemon may also sync enrolled repos.

### Why search misses new code

- File not in index scope (e.g. not `.py` in fast mode).
- Sync not run after edit.
- Searching wrong repo (multi-root Cursor — bind `root` on first MCP call).

---

## Search and retrieval

### CLI

```bash
scubiee search "authentication middleware" .
```

Uses same engine as MCP — hybrid semantic + lexical + graph fusion inside conductor/retrieve layer.

### MCP (`phase` surface)

| Stage | Tool | Returns |
|-------|------|---------|
| Overview | `map(query)` | Ranked cards — paths, symbols, scores — **no bodies** |
| Depth | `focus(target, mode=…)` | Outline, span, neighbors, call_sites |
| Literal | `grep(pattern, glob=…)` | Line matches in **indexed** files |
| Paths | `glob(pattern)` | Indexed file paths matching pattern |
| Session | `workspace(show\|pin\|clear)` | What agent already explored |

**Important:** `grep`/`glob` search the **index**, not necessarily every file on disk if never indexed.

---

## MCP and the agent

### Session start

1. Agent calls **`gate()`** or **`status()`** once.
2. Response includes `managed`, `ok`, `warming`, sometimes `project_id`.
3. If `managed: true` and `ok: true` → use Scubiee for discovery.
4. If `managed: false` → user must `init` + `connect`; agent uses native tools until then.

### Repo binding in multi-root IDEs

One MCP process may serve multiple Cursor workspaces. Pass **`root`** = workspace path on first call so Scubiee checks the correct folder for `.scubiee/id.json`.

### Global stop

When user runs `scubiee stop`, MCP tools return paused/stopped errors until **`scubiee resume`**. Polling `status()` does not unpause — user action required.

---

## Repository lifecycle

| State | Registry | Index on disk | Agent should |
|-------|----------|---------------|--------------|
| Unmanaged | absent / not this path | absent or orphaned | Native tools; run `init` |
| Active | managed | present | Scubiee MCP |
| Paused | managed, paused flag | present | Native tools until `activate` |
| After wipe | removed | deleted | Native tools; re-`init` to return |

**Wipe** (`scubiee wipe . --confirm`) — removes enrollment, project store, VectorDB collections, `.scubiee`, repo MCP/rules. **Does not delete source code.**

Details: [../docs/web-info/repo-lifecycle.md](../docs/web-info/repo-lifecycle.md)

---

## Global stop vs per-repo pause

| | `scubiee stop` / `resume` | `scubiee pause` / `activate` |
|--|---------------------------|------------------------------|
| Scope | Entire machine | One repo |
| Engine | Stopped | May still run |
| MCP globally | Torn down / blocked | Still connected |
| Data | Kept | Kept |
| Use when | Upgrade, uninstall prep | Maintenance on one repo |

Common mistake: user paused one repo but agent says run `resume` — that's **global** stop. Per-repo needs **`activate`**.

---

## Upgrades and migrations

### `scubiee upgrade`

1. Unlocks Windows file locks if needed.
2. Stops processes.
3. Swaps package (PyPI).
4. Runs migration plan (schema, MCP pin format, rules).
5. Restarts daemon.

Always follow with **`setup --repair`** if diagnose shows missing libs, and **`connect`** to refresh MCP/rules.

### Version registry (0.3.14+)

Upgrade releases registered in code declare which components need rewrite/migrate/reinstall when crossing versions. Diff plan shown in upgrade JSON.

---

## Windows-specific behavior

### File locks

Cursor holds `python.exe` under `%APPDATA%\uv\tools\scubiee\Scripts\`. `uv tool install --force` fails with **Access denied (os error 5)** — not ACL.

**Fix path:** `scubiee unlock-tool` → disables MCP stub → kills processes → rename-aside tool dir → reinstall.

### Doctor install identity (0.3.13+)

`scubiee doctor` reports `active_binary` vs `expected_binary`. Duplicate scubiee on PATH (conda + uv) causes version drift — use one install method.

### Terminal UX (0.3.13+)

colorama + UTF-8 for banner/progress in cmd/PowerShell.

---

## Related

- [Complete fix guide](./complete-fix-guide.md)
- [Error codes reference](./error-codes-reference.md)
- [Data & files reference](./data-and-files-reference.md)
- [MCP tools reference](../docs/web-info/mcp-tools-reference.md)
- [Context engine internals](./context-engine-internals.md)
