# MCP Workspace Resolution Issue

## The Problem

When Scubiee's MCP server starts, it needs to know **which repository** to serve. But the MCP process is spawned by the IDE — not by the user — and it doesn't always receive the correct workspace path.

### What happens:

1. User runs `scubiee setup` -> writes global MCP config (no `CTX_REPO`)
2. User runs `scubiee init .` -> indexes the repo
3. IDE (Kiro/Copilot) spawns the MCP process using the global config
4. MCP process starts but has **no way to know which repo** it should serve
5. It falls back to its own `cwd` -> which is the IDE install directory (e.g., `C:\Users\usman\AppData\Local\Programs\Kiro`)
6. Reports `managed: false` -> MCP tools don't work

### Why this only affects Kiro and VS Code/Copilot:

| Tool | Why it works without project-level config |
|------|------------------------------------------|
| Cursor | Sets `CURSOR_PROJECT_DIR` env var when spawning MCP. Also reads project `.cursor/mcp.json`. |
| Claude Code | Launched FROM the project dir, so `cwd` is correct. Also has `.mcp.json` at root. |
| Windsurf/Codex/Zed | Global-only, single project, `CTX_REPO` in global config is fine. |
| **Kiro** | Spawns from user-level config. Does NOT set workspace env var. `cwd` = Kiro install dir. **Broken.** |
| **VS Code/Copilot** | May spawn from user settings. May not pass workspace. **Potentially broken.** |

## Current Workaround

Write a **project-level** MCP config:
- `<repo>/.kiro/settings/mcp.json` with `CTX_REPO` pointing to the repo
- `<repo>/.vscode/mcp.json` with `CTX_REPO` pointing to the repo

Requires `scubiee connect --kiro` or `--copilot` from each repo separately.

## The Core Question

How do we make the MCP server automatically discover the correct workspace without requiring per-repo config for every project?

## Options to Research

### Option A: `init` auto-writes project-level configs
- `scubiee init .` writes `.kiro/settings/mcp.json` and `.vscode/mcp.json` automatically
- Pros: Zero extra steps, works immediately after init
- Cons: Adds dotfiles to repo (may confuse users, needs gitignore)

### Option B: MCP auto-registration from registry
- Global config has `CTX_REGISTRATION_MODE=automatic`
- When MCP starts without knowing the repo, it checks `~/.context-engine/registry.json` for managed projects
- If only ONE project managed -> use it
- If multiple -> pick the one whose path is a parent of any open file
- Pros: Zero per-repo config
- Cons: Unreliable in multi-project setups

### Option C: IDE provides workspace (ideal)
- Kiro/Copilot sets an env var like `KIRO_WORKSPACE_FOLDER` when spawning
- We just read it in `_default_repo()`
- Pros: Cleanest, no files needed
- Cons: Not in our control (requires IDE changes)

### Option D: Hybrid (init writes + registry fallback)
- `init` writes project-level for Kiro/VS Code
- `_default_repo()` also checks registry as fallback for moved folders
- Pros: Covers all scenarios
- Cons: More code

## What We've Already Fixed (v0.2.72)

1. `_default_repo()` checks IDE env vars first for enrolled projects
2. Validates `CTX_REPO` before trusting it (must be enrolled or have .git)
3. Walks up from `cwd` for enrolled projects
4. Falls back gracefully

## What's Still Missing

- Kiro doesn't set ANY workspace env var -> our check finds nothing
- MCP process cwd is Kiro install dir -> walk-up finds nothing
- Only fix: project-level `.kiro/settings/mcp.json` with explicit `CTX_REPO`

## Research Questions

1. Does Kiro pass any workspace info to spawned MCP processes? (env var, stdin args, init params?)
2. Does the MCP protocol `initialize` message include workspace/rootUri from the client?
3. What does VS Code/Copilot actually pass? Do they set `VSCODE_WORKSPACE_FOLDER`?
4. Can we detect workspace from the parent process or open files?
5. Should we accept project-level config is required and just make `init` write it?
