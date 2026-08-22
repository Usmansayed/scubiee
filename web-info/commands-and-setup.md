# Scubiee: Commands, Setup, and Product Guide

> **Documentation baseline:** Scubiee `0.2.32`
> **Audience:** product pages, documentation websites, and developers using Scubiee from a terminal or an AI coding tool.

Scubiee is a local-first code context engine. It builds a searchable representation of your repository, keeps it fresh as files change, and exposes the result through a CLI, a local daemon, and MCP integrations for AI coding tools.

This guide is the user-facing source for what Scubiee does, when to use each command, and how to install and operate it. The implementation and architecture details are in [`context-engine-internals.md`](./context-engine-internals.md).

## What Scubiee is

Most coding assistants can read files, but a large repository makes ad-hoc file search noisy, slow, and easy to misdirect. Scubiee adds a repository-aware context layer that can:

- index source files into symbol- and file-oriented chunks;
- combine lexical, dense-vector, and graph-aware retrieval;
- preserve repository identity across Git repositories, linked worktrees, and moves;
- incrementally re-index changed files instead of rebuilding for every edit;
- serve context locally through a managed daemon and MCP;
- connect to 11 AI coding tools with one command; and
- fully clean up after itself when you're done.

### Product value in one sentence

**Scubiee turns a repository into continuously maintained, tool-agnostic context without forcing an AI assistant to guess which files matter.**

## Who should use it

- **Individual developers** — make any repository searchable by meaning and structure, entirely local.
- **Teams building AI coding workflows** — give Cursor, Claude Code, Codex, Kiro, Copilot, and others a common MCP backend.
- **Large or active repositories** — keep context current through incremental and live re-indexing.
- **Operators and release engineers** — inspect readiness, provider capabilities, daemon state, and data health from one CLI.

## Quick start

```bash
# 1. Install
pip install -U scubiee

# 2. One-time machine setup (detects GPU, downloads model, calibrates)
scubiee setup

# 3. Index your repository
scubiee init .

# 4. Connect to your AI tools
scubiee connect --kiro --cursor --claude-code

# Done. Your AI tools now have semantic code search.
```

## Core commands

### Setup and indexing

| Command | What it does |
|---------|-------------|
| `scubiee setup` | One-time machine install: detect GPU, download embedding model, calibrate speed, register supervisor |
| `scubiee init <path>` | Enroll a repository, index it, start serving it |
| `scubiee status <path>` | Show index health, freshness, and daemon state |
| `scubiee search "query" <path>` | Search your code from the CLI |

### Connecting and disconnecting AI tools

| Command | What it does |
|---------|-------------|
| `scubiee connect --<tool>` | Install MCP config + AI rules for a tool |
| `scubiee connect --all` | Connect all 11 supported tools at once |
| `scubiee connect --all --dry-run` | Preview what would be written |
| `scubiee disconnect --<tool>` | Remove MCP config + rules for a tool |
| `scubiee disconnect --all` | Disconnect all tools |

**Supported tools:** `--cursor`, `--claude-code`, `--codex`, `--kiro`, `--windsurf`, `--copilot`, `--cline`, `--roo-code`, `--continue`, `--zed`, `--opencode`

Both commands accept `--repo <path>` for workspace-aware integrations (Kiro writes both user-level and workspace-level configs).

### Cleanup and removal

| Command | What it does |
|---------|-------------|
| `scubiee wipe --confirm` | Remove engine data (indexes, logs, accel profile) |
| `scubiee wipe --confirm --all` | Nuclear option: engine + models + tool configs + repo markers |
| `scubiee wipe --confirm --models` | Engine data + cached embedding model weights |
| `scubiee wipe --confirm --tools` | Engine data + disconnect all AI tools |
| `scubiee wipe --confirm --repos` | Engine data + per-repo .context-engine/ directories |
| `scubiee wipe --dry-run --all` | Preview what would be deleted |

After `--all`, only the Python package remains. Remove it with: `pip uninstall scubiee`

### Repository lifecycle

| Command | What it does |
|---------|-------------|
| `scubiee sync <path>` | Incremental re-index changed files |
| `scubiee sync-now <path>` | Force immediate freshness reconciliation |
| `scubiee rebuild <path>` | Full rebuild of the index |
| `scubiee pause <path>` | Pause background indexing |
| `scubiee resume <path>` | Resume background indexing |
| `scubiee remove <path>` | Remove repository from management |
| `scubiee list` | List all managed repositories |

### Daemon and engine control

| Command | What it does |
|---------|-------------|
| `scubiee engine status` | Check if daemon is running |
| `scubiee engine start` | Start the daemon |
| `scubiee engine stop` | Stop the daemon |
| `scubiee engine ensure <path>` | Ensure daemon is serving a specific repo |
| `scubiee serve <path>` | Run daemon in foreground (useful for debugging) |
| `scubiee dashboard` | Open the operator dashboard |

### Diagnostics and repair

| Command | What it does |
|---------|-------------|
| `scubiee preflight <path>` | Check dependencies and capabilities |
| `scubiee doctor <path> --all` | Readiness diagnostics |
| `scubiee doctor <path> --fix` | Auto-repair known issues |
| `scubiee diagnose` | Generate a shareable diagnostic report |
| `scubiee setup --repair` | Repair machine-level setup |
| `scubiee resources --refresh` | Inspect hardware and resource pressure |

## Machine setup vs repository enrollment

These are intentionally separate:

| Operation | Scope | When |
|-----------|-------|------|
| `scubiee setup` | Machine-wide: GPU detection, model download, calibration | Once per machine |
| `scubiee init <path>` | Per-repository: enroll, index, serve | For each repo you want searchable |
| `scubiee connect --<tool>` | Per-tool: MCP config + rules | For each AI tool you use |

Adding a second repository does NOT repeat machine setup. Just run `scubiee init <path>`.

## Provider profiles

The embedding model is **`nomic-ai/CodeRankEmbed`**. The runtime depends on your hardware:

| Profile | Platform | Command |
|---------|----------|---------|
| `dml` | Windows GPU (AMD/Intel/NVIDIA) | `scubiee setup --profile dml` |
| `cuda` | Linux NVIDIA GPU | `scubiee setup --profile cuda` |
| `mlx` | Apple Silicon (M1/M2/M3/M4) | `scubiee setup --profile mlx` |
| `coreml` | macOS CoreML | `scubiee setup --profile coreml` |
| `cpu` | Any machine (fallback) | `scubiee setup --profile cpu` |

Without `--profile`, setup auto-detects the best option.

## MCP tools exposed to AI coding tools

The default MCP surface (`phase`) exposes 6 tools:

| Tool | Purpose |
|------|---------|
| `map` | Find the most relevant areas of the codebase for a query |
| `focus` | Deep-dive into a specific file/span with surrounding context |
| `grep` | Exact text/regex search across the repository |
| `glob` | Find files by path pattern |
| `workspace` | Inspect or manage session context |
| `status` | Check if the repo is managed and healthy |

### How the global rule works

When you run `scubiee connect`, it installs a self-gating rule:

1. AI tool calls `status()` once at session start
2. If `managed=true` and `ok=true` → use Scubiee tools for discovery
3. If unmanaged or unhealthy → ignore Scubiee, use native tools

This means the rule never breaks unmanaged folders. It only activates when the repo is enrolled and healthy.

## Supported tool integrations

| Tool | MCP config path | Rule file |
|------|----------------|-----------|
| Cursor | `~/.cursor/mcp.json` | `~/.cursor/rules/context-engine.mdc` |
| Claude Code | `~/.claude.json` | `~/.claude/CLAUDE.md` (appended section) |
| Codex | `~/.codex/config.toml` | `~/.codex/instructions.md` (appended) |
| Kiro | `~/.kiro/settings/mcp.json` + workspace | `~/.kiro/steering/context-engine.md` |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` | MCP description only |
| VS Code / Copilot | `~/.vscode/mcp.json` | `~/.github/copilot-instructions.md` (appended) |
| Cline | `~/.cline/mcp.json` | `~/.cline/rules/context-engine.md` |
| Roo Code | `~/.cline/mcp.json` | `~/.cline/rules/context-engine.md` |
| Continue | `~/.continue/config.yaml` | `~/.continue/rules/context-engine.md` |
| Zed | `~/.config/zed/settings.json` | MCP description only |
| OpenCode | `~/.config/opencode/config.json` | `~/.config/opencode/instructions.md` (appended) |

## Data locations

| Location | What's stored |
|----------|--------------|
| `~/.context-engine/` | Engine home: indexes, registry, accel profile, logs |
| `~/.context-engine/vectordb/` | FAISS vector database |
| `~/.context-engine/projects/<id>/` | Per-repo index artifacts |
| `<repo>/.context-engine/id.json` | Repository identity marker |
| `~/.cache/fastembed/` | Cached ONNX embedding model |
| `~/.cache/huggingface/hub/` | HuggingFace model downloads |

## Environment variables

Most users don't need these. They're for MCP entries and advanced automation:

| Variable | Purpose |
|----------|---------|
| `CTX_REPO` | Explicit repository path for MCP processes |
| `CTX_ENGINE_URL` | Daemon URL (default: `http://127.0.0.1:8765`) |
| `CTX_MCP_SURFACE` | Tool surface selection (default: `phase`) |
| `CTX_TOKEN_MODE` | Token budget mode (default: `savings`) |
| `CTX_BACKGROUND_SYNC` | Enable/disable background sync |
| `CTX_AUTO_INDEX` | Enable/disable auto-indexing |

## Common workflows

### Fresh install on a new machine

```bash
pip install -U scubiee
scubiee setup
scubiee connect --all
scubiee init ~/projects/my-app
```

### Add another repository (no repeat setup)

```bash
scubiee init ~/projects/another-repo
```

### Refresh a stale index

```bash
scubiee status .
scubiee sync-now .
# or full rebuild:
scubiee rebuild .
```

### Complete uninstall

```bash
scubiee wipe --confirm --all
pip uninstall scubiee -y
```

### Troubleshoot: AI tool not using Scubiee

```bash
scubiee status <repo>              # Is it managed and healthy?
scubiee engine status              # Is the daemon running?
scubiee connect --<tool> --dry-run # Is the config pointing to the right places?
```

## Versioning

- Current release: **0.2.32**
- Package name: `scubiee`
- CLI command: `scubiee`
- PyPI: https://pypi.org/project/scubiee/
- GitHub: https://github.com/Usmansayed/new-context-engine
