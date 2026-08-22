# Scubiee: Commands, Setup, and Product Guide

> **Documentation baseline:** Scubiee `0.2.54`
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
- fully clean up after itself when you're done (with an honest wipe audit).

### Product value in one sentence

**Scubiee turns a repository into continuously maintained, tool-agnostic context without forcing an AI assistant to guess which files matter.**

## Quick start

```bash
# 1. Install (recommended: uv tool)
uv tool install --force scubiee==0.2.54 --index-url https://pypi.org/simple --refresh

# 2. One-time machine setup (detects GPU, downloads model, calibrates)
scubiee setup --repair

# 3. Connect your AI tools
scubiee connect --cursor --claude-code

# 4. Index your repository
cd your-repo
scubiee init . --fast

# Done. Reload MCP in Cursor (Settings → MCP → refresh).
```

## Core commands

### Setup and indexing

| Command | What it does |
|---------|-------------|
| `scubiee setup --repair` | Machine install: detect GPU, ORT/FastEmbed, model, calibration, supervisor |
| `scubiee setup --status` | Print saved accel profile (read-only) |
| `scubiee init <path>` | Enroll a repository and index it (requires setup first) |
| `scubiee init . --fast --roots packages` | Fast index scoped to code roots |
| `scubiee init . --confirm` | Allow indexing when >400 files would be touched |
| `scubiee status <path>` | Show index health, freshness, and daemon state |
| `scubiee search "query" <path>` | Search your code from the CLI |
| `scubiee sync <path> [--confirm]` | Incremental re-index of changed files |

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

### Diagnostics and migrations

| Command | What it does |
|---------|-------------|
| `scubiee diagnose [--no-tests]` | Installation diagnostics + shareable log file |
| `scubiee migrate --check-all` | Check schema migrations after upgrade |
| `scubiee migrate --apply-all` | Apply migrations for all managed projects |
| `scubiee doctor <path> [--fix]` | Readiness report and safe repairs |
| `scubiee preflight [path]` | Dependency / capability check |

### Cleanup and removal

| Command | What it does |
|---------|-------------|
| `scubiee wipe <path>` | Remove one repo's CE enrollment + index |
| `scubiee wipe --all` | **Safety pause** (exit 2) until confirmed |
| `scubiee wipe --all --yes` | Remove all CE state: homes, MCP, rules, models, enrolled repos |
| `scubiee wipe --all --yes --package` | Full wipe + uninstall scubiee uv tool |
| `scubiee wipe --all --yes --keep-models` | Wipe but keep embedding model caches |
| `scubiee stop` | Stop engine, watchdog, MCP-related processes (run before wipe on Windows) |

After `--all --yes`, inspect JSON **`audit.remaining`** for paths still on disk (usually MCP locks). Quit Cursor and re-run if needed.

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
| `scubiee engine ensure <path>` | Ensure daemon is serving a repo |
| `scubiee stop` | Stop daemon + watchdog + related processes |
| `scubiee serve <path>` | Run daemon in foreground (debug) |
| `scubiee dashboard --no-open` | Start operator dashboard |

## Machine setup vs repository enrollment

These are intentionally separate:

| Operation | Scope | When |
|-----------|-------|------|
| `scubiee setup --repair` | Machine-wide: GPU, model, calibration | Once per machine (and after upgrade) |
| `scubiee init <path>` | Per-repository: enroll, index, serve | For each repo you want searchable |
| `scubiee connect --<tool>` | Per-tool: MCP config + rules | For each AI tool you use |

Adding a second repository does **not** repeat machine setup. Run `scubiee init <path>` only.

If `init` returns `"error": "machine_not_setup"`, run `scubiee setup --repair` first.

## Provider profiles

The embedding model is **`nomic-ai/CodeRankEmbed`**. The runtime depends on your hardware:

| Profile | Platform | Command |
|---------|----------|---------|
| `dml` | Windows GPU (AMD/Intel/NVIDIA) | `scubiee setup --profile dml --repair` |
| `cuda` | Linux NVIDIA GPU | `scubiee setup --profile cuda --repair` |
| `mlx` | Apple Silicon (M1/M2/M3/M4) | `scubiee setup --profile mlx --repair` |
| `coreml` | macOS CoreML | `scubiee setup --profile coreml --repair` |
| `cpu` | Any machine (fallback) | `scubiee setup --profile cpu --repair` |

Without `--profile`, setup auto-detects the best option. ONNX Runtime is pinned to `<1.25` for compatibility.

## MCP tools exposed to AI coding tools

The default MCP surface (`phase`) exposes **7 tools**:

| Tool | Purpose |
|------|---------|
| `status` | Check if the repo is managed and healthy (call once per session) |
| `map` | Find the most relevant areas of the codebase for a query |
| `focus` | Deep-dive into a specific file/span with surrounding context |
| `grep` | Exact text/regex search across the repository |
| `glob` | Find files by path pattern |
| `workspace` | Inspect or manage session context |
| `register_project` | Register repo with explicit user consent |

### How the global rule works

When you run `scubiee connect --cursor`, it installs **`~/.cursor/rules/context-agent.mdc`**:

1. AI tool calls `status()` once at session start
2. If `managed=true` and `ok=true` → use Scubiee tools for discovery
3. If unmanaged or unhealthy → ignore Scubiee, use native tools

This means the rule never breaks unmanaged folders. It only activates when the repo is enrolled and healthy.

## Supported tool integrations

| Tool | MCP config path | Rule file |
|------|----------------|-----------|
| Cursor | `~/.cursor/mcp.json` | `~/.cursor/rules/context-agent.mdc` |
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
| `~/.context-engine/projects/<id>/` | Per-repo index artifacts |
| `<repo>/.context-engine/id.json` | Repository identity marker |
| `~/.cursor/mcp.json` | Cursor MCP server entry |
| `~/.cursor/rules/context-agent.mdc` | Cursor agent rule (canonical) |
| FastEmbed / HuggingFace caches | CodeRank ONNX model weights |

## Common workflows

### Fresh install on a new machine

```bash
uv tool install --force scubiee==0.2.54 --index-url https://pypi.org/simple --refresh
scubiee setup --repair
scubiee connect --all
cd ~/projects/my-app && scubiee init . --fast
```

### Add another repository (no repeat setup)

```bash
scubiee init ~/projects/another-repo --fast
```

### Complete uninstall

```bash
scubiee stop
scubiee wipe --all --yes --package
# quit Cursor if audit.remaining is non-empty, then re-run wipe
```

### Troubleshoot: AI tool not using Scubiee

```bash
scubiee status <repo>
scubiee engine status
scubiee connect --cursor --dry-run
scubiee diagnose --no-tests
```

## Versioning

- Current release: **0.2.54**
- Package name: `scubiee`
- CLI command: `scubiee`
- PyPI: https://pypi.org/project/scubiee/0.2.54/
- GitHub: https://github.com/Usmansayed/new-context-engine

For detailed operator docs see [`../docs/web-info/`](../docs/web-info/README.md).
