# Scubiee Website Content

> **Version:** [0.2.87](https://pypi.org/project/scubiee/0.2.87/) (published on PyPI)  
> **Purpose:** Content reference for designing and building the Scubiee product website and public docs.  
> **Product identity:** MCP key **`scubiee`** · data **`~/.scubiee`** / **`<repo>/.scubiee`** (no legacy `context-engine` paths)  
> **Full operator docs:** [`../docs/web-info/`](../docs/web-info/README.md)  
> **Install / debug playbook:** [`../docs/web-info/install-and-debug.md`](../docs/web-info/install-and-debug.md)

## Tagline options

- "Local code search that actually understands your repository."
- "Give every AI coding tool semantic search. Locally."
- "Index once, search from anywhere. No cloud required."
- "The missing context layer for AI coding assistants."

## One-liner

Scubiee is a local code context engine that gives AI coding tools semantic search, graph-aware retrieval, and live re-indexing — without uploading your code anywhere.

## Key features (for feature grid/cards)

### Semantic code search
Search by meaning, not just text. "authentication middleware" finds auth handlers even if they don't contain those exact words. Powered by CodeRankEmbed + FAISS.

### Many AI tools, one connect family
Connect Cursor, Claude Code, Codex, Kiro, Copilot/VS Code, Windsurf, Cline, Roo Code, Continue, Zed, OpenCode, and more with `scubiee connect`. Disconnect cleanly with `scubiee disconnect`.

### GPU-aware indexing (auto profile)
- **Windows discrete AMD/NVIDIA** → DirectML (`dml`)
- **Windows Intel iGPU / AMD APU / no discrete GPU** → CPU (`cpu`) — no DML hang
- **Apple Silicon** → MLX Metal (`mlx`) — must not stay on CPU
- **Linux NVIDIA** → CUDA (`cuda`)

### Live re-indexing
Changed files re-index in the background so search stays current.

### Graph-aware retrieval
Imports, calls, and structure — not only matching text.

### Completely local
No cloud uploads for search. Model download only during setup. MCP server key: **`scubiee`**. Indexes live under `~/.scubiee`.

### Stop and resume
`scubiee stop` frees processes and file locks. `scubiee resume` brings Scubiee back. There is no `wake`.

### One-command upgrade
`scubiee upgrade` unlocks/stops Scubiee processes first (critical on Windows Access denied), upgrades, restarts, migrates. Then re-run `connect` so rules stay current. If the CLI is broken, use `scubiee unlock-tool` or `scripts/repair-uv-scubiee.ps1`.

### Self-healing setup
`scubiee setup --repair` restores missing FastEmbed/ORT extras and refreshes `accel.json` after broken reinstalls.

### Multi-repository
`scubiee init <path>` per repo. Special-4 hosts (Kiro/Copilot/Cline/Roo) need `connect` inside each project.

## How it works (3-step explanation)

```
1. SETUP                 2. INDEX               3. CONNECT
scubiee setup --repair    scubiee init .         scubiee connect --cursor
     |                    |                      |
     v                    v                      v
Detect GPU/CPU/MLX   Parse + embed code     Write MCP + agent rules
Download model       Store vectors/graph    Reload IDE MCP
Calibrate speed      Start daemon           Agent status() → managed
```

**Remember for docs copy:** `init` does **not** wire the IDE. `connect` does.

## Architecture (simplified for website)

```
Your AI Tool (Cursor / Kiro / Claude Code / …)
        |
        | MCP protocol (stdio)
        v
+------------------+
| Scubiee MCP      |  status, map, focus, grep, glob, workspace
+------------------+
        |
        | HTTP (localhost)
        v
+------------------+
| Scubiee Engine   |  Daemon + live re-indexing
+------------------+
        |
        v
+------------------+
| Your Code Index  |  Vectors + Graph + Chunks (all local)
+------------------+
```

## MCP tools (docs/API section)

| Tool | What it does | When AI uses it |
|------|-------------|-----------------|
| `status` | Managed / healthy / warming | Once at session start (not every turn) |
| `map` | Ranked code areas for a query | "Where is authentication handled?" |
| `focus` | Deep-dive into a span + neighbors | "Show login and its callers" |
| `grep` | Exact text/regex | "Find all uses of `API_KEY`" |
| `glob` | Files by pattern | "List all `*.test.ts`" |
| `workspace` | Session context | Tracking what was explored |

**Warming:** If `warming: true`, retry the tool once after a few seconds — do not spam `status()`.

## Comparison angles

### vs native file search
Native: text matching. Scubiee: semantic + structure + live updates.

### vs cloud code search
Cloud: uploads + keys + network. Scubiee: local, offline after setup.

### vs DIY RAG
DIY: weeks of plumbing. Scubiee: setup → init → connect in minutes.

## Supported platforms

| Platform | Acceleration | Status |
|----------|--------------|--------|
| Windows + discrete AMD/NVIDIA | DirectML FP16 | Production |
| Windows CPU-only / iGPU-only | CPU | Production (validated on Intel UHD laptops) |
| Linux + NVIDIA | CUDA | Production |
| macOS Apple Silicon | MLX Metal | Production (verify on device) |
| macOS Intel | CoreML / CPU | Supported |
| Linux no GPU | CPU | Supported |

## Installation (website copy)

```bash
# Recommended
uv tool install --force scubiee==0.2.87 --index-url https://pypi.org/simple --refresh

# Windows Access denied? → scubiee unlock-tool  (then retry install)

scubiee setup --repair
cd your-repo
scubiee init .
scubiee connect --cursor          # Special-4: inside each project
# Reload MCP in the IDE
```

Share diagnostics: `scubiee diagnose --no-tests --desktop` → Desktop JSON.

## User-facing issues (docs FAQ / support page)

| Problem | What to tell users |
|---------|-------------------|
| “MCP doesn’t work” | Did you **connect** after **init**? Reload MCP. |
| Kiro/Copilot/Cline/Roo empty | Run `connect --tool` **inside that repo**. |
| Access denied on Windows upgrade | **`scubiee unlock-tool`**, then reinstall + `setup --repair`. File locks, not ACLs — Admin/reboot is not the fix. |
| `No module named 'pipeline'` | Half-deleted uv tool dir — `unlock-tool` or `scripts/repair-uv-scubiee.ps1`, then reinstall. |
| Cursor `managed: false` | Run `connect --cursor` **from the project** (project `.cursor/mcp.json` pin). |
| Diagnose looks fine, init fails | Stale accel — `setup --repair` then init. |
| Agent says `wake` | Run **`scubiee resume`**. |
| Agent polls status forever | Re-run `connect` (rules are event-driven). |
| Intel laptop stuck on DML hang | Current builds use **cpu** for iGPU — upgrade + `setup --repair`. |

Full install/debug playbook: [`../docs/web-info/install-and-debug.md`](../docs/web-info/install-and-debug.md).

## CLI command tree (website)

```
scubiee
├── setup [--repair] [--status] [--profile …]
├── init <path>
├── connect / disconnect [--cursor|--kiro|…|--all]
├── stop / resume
├── unlock-tool          # Windows: free uv tool locks before reinstall
├── upgrade
├── search / sync / status / rebuild
├── pause / resume <path>
├── diagnose [--desktop]
├── doctor / preflight / resources
├── engine / dashboard / wipe
└── settings / migrate / list / remove
```

## SEO keywords

scubiee, local code search, semantic code search, AI coding tools, MCP server, code context engine, repository indexing, vector search code, cursor mcp, kiro mcp, claude code mcp, code embeddings, directml, mlx, local ai code assistant

## Social proof / use cases

- "CPU-only Windows laptop finished setup without hanging on DirectML"
- "One connect wired Cursor; Kiro needed connect inside the project"
- "The AI finds the right code instead of grepping randomly"
- "Completely local — security approved it"
- "wipe --all with an honest leftover audit"
