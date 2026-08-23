# Scubiee Website Content

> **Version:** 0.2.57
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

### 13 AI tools, one command
Connect to Cursor, Claude Code, Codex, Kiro, VS Code/Copilot, Windsurf, Cline, Roo Code, Continue, Zed, OpenCode, Amp, and Pi with `scubiee connect --all`. Disconnect cleanly with `scubiee disconnect --all`.

### GPU-accelerated indexing
Auto-detects your hardware and picks the fastest path. DirectML (Windows), CUDA (Linux), or MLX (Mac) for GPU-accelerated FP16 embedding. CPU-only laptops get INT8 quantized model automatically — 1.5x faster and 4x smaller than FP16, with near-identical retrieval quality. Typical: 400 files indexed in under 3 minutes on GPU, ~7 minutes on CPU.

### Smart CPU throttling
Background indexing uses only 15% of your CPU — invisible during coding. Initial index uses 35% for faster first-time setup. GPU machines offload compute entirely, keeping CPU near zero.

### Live re-indexing
Changed files are automatically re-indexed in the background. Your search results stay current without manual rebuilds.

### Graph-aware retrieval
Understands code structure: imports, function calls, class hierarchies. Returns not just matching text, but structurally related context that helps the AI understand your code.

### Completely local
All data stays on your machine. No cloud uploads, no API keys for search, no telemetry. Your code never leaves your disk.

### Stop and resume
`scubiee stop` makes Scubiee completely invisible — kills processes, disables MCP entries, hides rules. Zero CPU/memory while stopped. `scubiee resume` brings everything back instantly.

### One-command upgrade
`scubiee upgrade` checks PyPI, stops processes, installs the new version, restarts, and runs migrations. Status shows update hints when a newer version is available.

### Self-healing
GPU provider missing after a package update? Scubiee auto-repairs by reinstalling the correct runtime wheel. Daemon killed? Auto-restarts on next tool call. Registry corrupted? Gracefully recovers. Multiple installs fighting? Warns with a clear fix.

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
| Index speed (DML GPU) | ~26-35 chunks/sec, 400 files in ~3 min |
| Index speed (CPU INT8, 2 threads) | ~8 chunks/sec, 400 files in ~7 min |
| Index speed (MLX Apple Silicon) | ~111 texts/sec |
| Embedding model | nomic-ai/CodeRankEmbed (768-dim) |
| Model precision | FP16 (GPU) / INT8 quantized (CPU) |
| Vector compression | 4x (TurboQuant 8-bit) |
| Search latency (warm) | <100ms for top-k=8 |
| Cold-start warming | 3-5s (GPU), 5-10s (CPU) — agent retries automatically |
| Live re-index | Background, debounced, 15% CPU budget |
| Memory (idle daemon) | ~50-100MB RSS |
| MCP tools response | <1s after warmup |

## Supported platforms

| Platform | GPU acceleration | Model | Status |
|----------|-----------------|-------|--------|
| Windows 10/11 | DirectML (AMD, Intel, NVIDIA) | FP16 | Production |
| Linux | CUDA (NVIDIA) | FP16 | Production |
| macOS (Apple Silicon) | MLX (Metal) | FP16 | Production |
| macOS (Intel) | CoreML / CPU | FP16/INT8 | Supported |
| Windows (no discrete GPU) | CPU + INT8 quantized | INT8 | Supported |
| Linux (no GPU) | CPU + INT8 quantized | INT8 | Supported |

**Model selection is automatic:** GPU machines get FP16 (fast, accurate). CPU-only machines get INT8 (1.5x faster than FP16 on CPU, 4x smaller, near-identical quality). FP32 is never used for inference.

## Pricing model (TBD — for website design)

Scubiee is currently free and open source. Future pricing could include:
- Free tier: unlimited local use
- Pro tier: team features, shared indexes, cloud sync
- Enterprise: on-prem deployment, SSO, audit logs

## Installation methods

```bash
# Recommended (isolated tool install)
uv tool install scubiee

# With GPU extras
uv tool install "scubiee[dml]"     # Windows DirectML
uv tool install "scubiee[cuda]"    # Linux NVIDIA
uv tool install "scubiee[macos]"   # Mac (auto-detects MLX on Apple Silicon)

# pip (also works)
pip install scubiee
pip install "scubiee[dml]"

# CPU-only (INT8 model auto-installed during setup)
uv tool install scubiee
# or
pip install scubiee
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
│   ├── --amp
│   ├── --pi
│   └── --all
├── disconnect         # Disconnect from AI tools (same flags)
├── stop               # Make Scubiee invisible (kill, disable MCP, hide rules)
├── resume             # Bring Scubiee back
├── upgrade            # Check + install latest version
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
