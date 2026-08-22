# Scubiee Website Content

> **Version:** 0.2.54
> **Purpose:** Content reference for designing and building the Scubiee product website.

## Tagline options

- "Local code search that actually understands your repository."
- "Give every AI coding tool semantic search. Locally."
- "Index once, search from anywhere. No cloud required."
- "The missing context layer for AI coding assistants."

## One-liner

Scubiee is a local code context engine that gives AI coding tools semantic search, graph-aware retrieval, and live re-indexing — without uploading your code anywhere.

## Key features (for feature grid/cards)

### Semantic code search
Search by meaning, not just text. "authentication middleware" finds auth handlers even if they don't contain those exact words. Powered by CodeRankEmbed embeddings + FAISS vector search.

### 11 AI tools, one command
Connect to Cursor, Claude Code, Codex, Kiro, VS Code/Copilot, Windsurf, Cline, Roo Code, Continue, Zed, and OpenCode with `scubiee connect --all`.

### GPU-accelerated indexing
Auto-detects your GPU and uses DirectML (Windows), CUDA (Linux), or MLX (Mac) for fast embedding. Falls back to CPU when needed. Typical: 377 files indexed in under 3 minutes.

### Live re-indexing
Changed files are automatically re-indexed in the background. Your search results stay current without manual rebuilds.

### Graph-aware retrieval
Understands code structure: imports, function calls, class hierarchies. Returns not just matching text, but structurally related context that helps the AI understand your code.

### Completely local
All data stays on your machine. No cloud uploads, no API keys for search, no telemetry. Your code never leaves your disk.

### Clean uninstall
`scubiee wipe --all --yes --package` removes indexes, models, MCP configs, and tool rules — with an **`audit.remaining`** report if Windows locks files. Nothing hidden.

### Multi-repository
Index as many repos as you want. Each gets its own identity, vector index, and lifecycle. Adding a repo is just `scubiee init <path>`.

## How it works (3-step explanation)

```
1. SETUP               2. INDEX              3. CONNECT
scubiee setup --repair  scubiee init .        scubiee connect --all
     |                  |                    |
     v                  v                    v
Detect GPU        Parse code          Write MCP configs
Download model    Build graph         Install AI rules
Calibrate speed   Embed chunks        Self-gating rule
                  Store vectors       activates per-repo
```

## Architecture (simplified for website)

```
Your AI Tool (Cursor/Kiro/Claude Code/...)
        |
        | MCP protocol (stdio)
        v
+------------------+
| Scubiee MCP      |  6 tools: map, focus, grep, glob, workspace, status
+------------------+
        |
        | HTTP (localhost)
        v
+------------------+
| Scubiee Engine   |  Daemon with live re-indexing
+------------------+
        |
        v
+------------------+
| Your Code Index  |  Vectors + Graph + Chunks (all local)
+------------------+
```

## MCP tools (for docs/API section)

| Tool | What it does | When AI uses it |
|------|-------------|-----------------|
| `map` | Returns ranked code areas for a query | "Where is authentication handled?" |
| `focus` | Deep-dives into a file/span with context | "Show me the login function and its callers" |
| `grep` | Exact text/regex search | "Find all uses of `API_KEY`" |
| `glob` | Find files by pattern | "List all *.test.ts files" |
| `workspace` | Session context management | Tracking what's been explored |
| `status` | Health and management check | First call every session |

## Comparison angles (for landing page)

### vs. just using native file search
- Native search: text matching, no understanding of code structure
- Scubiee: semantic search + graph relationships + keeps up with edits

### vs. cloud-based code search (Sourcegraph, etc.)
- Cloud: requires uploading code, API keys, internet connection
- Scubiee: 100% local, no uploads, works offline, no subscription

### vs. embedding your own RAG pipeline
- DIY RAG: weeks of engineering, custom chunking, manual updates
- Scubiee: `pip install scubiee && scubiee setup && scubiee init .` — done in 5 minutes

## Performance benchmarks (from real testing)

| Metric | Value |
|--------|-------|
| Index speed (DML GPU) | ~26 chunks/sec, 377 files in 184s |
| Index speed (calibrated) | ~36 texts/sec at batch=20 |
| Embedding model | nomic-ai/CodeRankEmbed (768-dim) |
| Vector compression | 4x (TurboQuant 8-bit) |
| Search latency (warm) | <100ms for top-k=5 |
| Live re-index | Background, debounced, sub-second for small changes |
| Memory (idle daemon) | ~50-100MB RSS |

## Supported platforms

| Platform | GPU acceleration | Status |
|----------|-----------------|--------|
| Windows 10/11 | DirectML (AMD, Intel, NVIDIA) | Production |
| Linux | CUDA (NVIDIA) | Production |
| macOS (Apple Silicon) | MLX (Metal) | Production |
| macOS (Intel) | CoreML / CPU | Supported |
| Any | CPU fallback | Supported |

## Pricing model (TBD — for website design)

Scubiee is currently free and open source. Future pricing could include:
- Free tier: unlimited local use
- Pro tier: team features, shared indexes, cloud sync
- Enterprise: on-prem deployment, SSO, audit logs

## Installation methods

```bash
# PyPI (recommended)
pip install -U scubiee

# From source (development)
pip install -e ".[dml]"  # or [cuda], [mlx], [cpu]

# npm wrapper (for Node.js toolchains)
npx scubiee setup
```

## CLI command tree (complete)

```
scubiee
├── setup              # One-time machine setup
├── init <path>        # Enroll + index a repository
├── connect            # Connect to AI tools
│   ├── --cursor
│   ├── --claude-code
│   ├── --codex
│   ├── --kiro
│   ├── --windsurf
│   ├── --copilot
│   ├── --cline
│   ├── --roo-code
│   ├── --continue
│   ├── --zed
│   ├── --opencode
│   └── --all
├── disconnect         # Disconnect from AI tools (same flags)
├── search "query"     # CLI search
├── status <path>      # Health check
├── sync <path>        # Incremental re-index
├── sync-now <path>    # Force immediate sync
├── rebuild <path>     # Full rebuild
├── pause <path>       # Pause background work
├── resume <path>      # Resume background work
├── remove <path>      # Remove from management
├── list               # List managed repos
├── engine             # Daemon control
│   ├── start
│   ├── stop
│   ├── status
│   ├── ensure <path>
│   └── run <path>
├── wipe               # Cleanup
│   ├── --all --yes
│   ├── --all --yes --package
│   ├── --all --yes --keep-models
│   └── --all --yes --keep-package
├── serve <path>       # Foreground daemon
├── dashboard          # Operator UI
├── preflight          # Dependency check
├── doctor             # Diagnostics + repair
├── diagnose           # Shareable report
├── resources          # Hardware inspection
├── certify            # Release gate
├── test <tier>        # Verification suites
├── migrate            # Data migrations
└── settings           # Preferences
```

## SEO keywords

scubiee, local code search, semantic code search, AI coding tools, MCP server, code context engine, repository indexing, vector search code, cursor mcp, kiro mcp, claude code mcp, code embeddings, directml code search, local ai code assistant, code graph search

## Social proof / use cases (for testimonials section)

- "Indexed 377 files in 3 minutes on my Windows laptop with an AMD GPU"
- "One command connected it to all 5 tools I use daily"
- "The AI actually finds the right code now instead of grepping randomly"
- "Completely local — our security team approved it in a day"
- "The wipe --all command is a trust signal — nothing hidden"
