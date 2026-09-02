# Scubiee: Commands, Setup, and Product Guide

> **Documentation baseline:** [Scubiee `0.3.13`](https://pypi.org/project/scubiee/0.3.13/) (published on PyPI)  
> **Audience:** product pages, documentation websites, and developers using Scubiee from a terminal or an AI coding tool.  
> **Product identity:** MCP key **`scubiee`** · home **`~/.scubiee`** · repo **`<repo>/.scubiee`**  
> **Canonical user docs:** [`../docs/web-info/`](../docs/web-info/README.md)  
> **Install / upgrade / debug playbook:** [`../docs/web-info/install-and-debug.md`](../docs/web-info/install-and-debug.md)

Scubiee is a local-first code context engine. It builds a searchable representation of your repository, keeps it fresh as files change, and exposes the result through a CLI, a local daemon, and MCP integrations for AI coding tools.

Implementation detail: [`context-engine-internals.md`](./context-engine-internals.md).

## What Scubiee is

Most coding assistants can read files, but a large repository makes ad-hoc file search noisy and easy to misdirect. Scubiee adds a repository-aware context layer that can:

- index source into symbol- and file-oriented chunks;
- combine lexical, dense-vector, and graph-aware retrieval;
- preserve repository identity across moves and worktrees;
- incrementally re-index changed files;
- serve context locally through a managed daemon and MCP;
- connect to many AI coding tools with one family of commands; and
- fully clean up with an honest wipe audit.

**One sentence:** Scubiee turns a repository into continuously maintained, tool-agnostic context without forcing an AI assistant to guess which files matter.

## Quick start (correct order)

```bash
# 1. Install
uv tool install --force scubiee==0.3.13 --index-url https://pypi.org/simple --refresh

# 2. One-time machine setup
scubiee setup --repair

# 3. Index your repository (does NOT write MCP)
cd your-repo
scubiee init .

# 4. Connect your AI tools (writes MCP + rules)
scubiee connect --cursor
# Kiro / Copilot / Cline / Roo: run connect *inside each project*

# 5. Reload MCP in the IDE
```

## Core commands

### Setup and indexing

| Command | What it does |
|---------|-------------|
| `scubiee setup --repair` | Machine install: detect GPU/CPU/MLX, ORT/FastEmbed, model, calibration |
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
| `scubiee connect --all` | Connect all supported tools |
| `scubiee connect --all --dry-run` | Preview what would be written |
| `scubiee disconnect --<tool>` | Remove MCP config + rules |
| `scubiee disconnect --all` | Disconnect all tools |

**Supported tools:** `--cursor`, `--claude-code`, `--codex`, `--kiro`, `--windsurf`, `--copilot`, `--cline`, `--roo-code`, `--continue`, `--zed`, `--opencode`

**Special-4:** `--kiro`, `--copilot`, `--cline`, `--roo-code` need connect **inside each project** (workspace-local MCP).

### Diagnostics and lifecycle

| Command | What it does |
|---------|-------------|
| `scubiee diagnose --no-tests --desktop` | Shareable diagnose JSON on Desktop |
| `scubiee unlock-tool` | **Windows:** free `%APPDATA%\uv\tools\scubiee` locks (MCP-off → stop → rename). Use before reinstall on Access denied |
| `scubiee upgrade` | Unlock/stop processes, upgrade package, restart, migrate |
| `scubiee stop` / `scubiee resume` | Stop engine / bring back (**not** `wake`) |
| `scubiee pause .` / `scubiee resume .` | Per-repo indexing pause |
| `scubiee doctor <path> [--fix]` | Readiness report |
| `scubiee preflight [path]` | Dependency / capability check |
| `scubiee wipe --all --confirm --package` | Full machine cleanup + uninstall (`--yes` = `--confirm`) |

## Machine setup vs repository enrollment vs connect

| Operation | Scope | When |
|-----------|-------|------|
| `scubiee setup --repair` | Machine-wide: GPU/CPU/MLX, model, calibration | Once per machine (and after upgrade / broken reinstall) |
| `scubiee init <path>` | Per-repository: enroll + index | Each repo you want searchable |
| `scubiee connect --<tool>` | MCP + rules | Each IDE; Special-4 inside each project |

Adding a second repository does **not** repeat machine setup — only `init` (and Special-4 `connect` if needed).

If `init` returns `"error": "machine_not_setup"`, run `scubiee setup --repair` first.

## Provider profiles

Embedding model: **`nomic-ai/CodeRankEmbed`** (FP16).

| Profile | When |
|---------|------|
| `dml` | Windows **discrete** AMD/NVIDIA GPU |
| `cpu` | Windows Intel iGPU / AMD APU / no discrete GPU; any CPU fallback |
| `cuda` | Linux NVIDIA |
| `mlx` | Apple Silicon (default — should not stay on CPU) |
| `coreml` | Intel Mac when viable |

```bash
scubiee setup --profile cpu --repair    # force CPU
scubiee setup --profile dml --repair    # escape hatch for missed discrete AMD
scubiee setup --profile mlx --repair    # Apple Silicon
```

## MCP tools (default `phase` surface)

| Tool | Purpose |
|------|---------|
| `status` | Managed / healthy / warming (once per session) |
| `map` | Ranked relevant areas for a query |
| `focus` | Deep-dive into a span with context |
| `grep` | Exact text/regex search |
| `glob` | Find files by path pattern |
| `workspace` | Session context |
| `register_project` | Explicit consent registration |

### Agent rule behavior

`connect` installs rules that:

1. Call `status()` once at session start  
2. If managed + ok → use Scubiee tools  
3. If warming → use tools; do not poll `status()` every turn  
4. If unmanaged → native tools; retry `status()` only after user runs init/connect  

Paused/stopped → user runs **`scubiee resume`**.

## User-facing issue cheatsheet

| Issue | Fix |
|-------|-----|
| Agent unmanaged | `init` + `connect` + reload MCP |
| Special-4 broken | `connect --tool` inside that repo |
| Access denied on Windows upgrade | **`unlock-tool`** → reinstall → `setup --repair` (not Admin/reboot) |
| `No module named 'pipeline'` | Unlock/PS1 repair → reinstall → `setup --repair` |
| Cursor unmanaged | `connect --cursor` from the project + reload MCP |
| Stale accel after reinstall | `setup --repair` before `init` |
| Said “wake” | Use **`resume`** |
| Warming forever | Ensure daemon: `engine ensure . --wait 45` |

Install/debug playbook: [`../docs/web-info/install-and-debug.md`](../docs/web-info/install-and-debug.md).  
Full guides: [`../docs/web-info/`](../docs/web-info/README.md).
