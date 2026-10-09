# Global MCP hosts — per-tool research (v0.3.0)

**Scope:** Tools that work with **`scubiee connect` once globally** — no per-repo MCP pin required.

**Excluded (special-4):** Kiro, VS Code/Copilot, Cline, Roo Code — see [mcp-workspace-resolution-issue.md](./mcp-workspace-resolution-issue.md).

**Code:** `packages/pipeline/host_workspace.py`  
**Tests:** `tests/test_global_mcp_hosts.py`

---

## Summary

| Tool | Slug | Global connect | Workspace discovery | Project rules on init |
|------|------|----------------|---------------------|------------------------|
| Cursor | `cursor` | Yes | Host env (`CURSOR_PROJECT_DIR`, …) | `.cursor/rules/scubiee.mdc` |
| Claude Code | `claude-code` | Yes | `CLAUDE_PROJECT_DIR` (official) | `.claude/CLAUDE.md` |
| Codex | `codex` | Yes | `CODEX_WORKSPACE_ROOT` or CLI cwd | `.codex/AGENTS.md` |
| Windsurf | `windsurf` | Yes | Env + Cascade cwd | None (MCP instructions only) |
| Continue | `continue` | Yes | `CONTINUE_*` or VS Code env | `.continue/rules/scubiee.md` |
| Zed | `zed` | Yes | `ZED_*` or project-root cwd | None |
| OpenCode | `opencode` | Yes | `OPENCODE_*` or CLI cwd | `.config/opencode/AGENTS.md` |
| Amp | `amp` | Yes | `AMP_*` or cwd | `.config/amp/AGENTS.md` |
| Pi | `pi` | Yes | `PI_*` or cwd | `.pi/agent/AGENTS.md` |

---

## Special-4 (NOT global-only)

| Tool | Why global MCP is not enough |
|------|------------------------------|
| **Kiro** | Spawns MCP from IDE install dir; no workspace env ([#10486](https://github.com/kirodotdev/Kiro/issues/10486)) |
| **Copilot/VS Code** | User `mcp.json` does not expand `${workspaceFolder}` ([#245905](https://github.com/microsoft/vscode/issues/245905)) |
| **Cline** | VS Code globalStorage spawn cwd unreliable |
| **Roo Code** | Same VS Code-family cwd issue as Cline |

For these: run `scubiee connect --<tool>` **inside each repo**, or use legacy project MCP cleanup on disconnect.

---

## Per-tool details

### Cursor (`cursor`)

- **MCP config:** `~/.cursor/mcp.json` → `mcpServers.scubiee`
- **Workspace env:** `CURSOR_PROJECT_DIR`, `CURSOR_WORKSPACE`, `CURSOR_CWD`, `WORKSPACE_FOLDER_PATHS`
- **Discovery:** Host-injected env (reliable)
- **Rules:** Per-repo `.cursor/rules/scubiee.mdc` on `scubiee init .`
- **Refs:** [cursor.com/help/customization/mcp](https://cursor.com/help/customization/mcp)

### Claude Code (`claude-code`)

- **MCP config:** `~/.claude.json` → top-level `mcpServers`
- **Workspace env:** `CLAUDE_PROJECT_DIR`, `CLAUDE_CODE_PROJECT_DIR`
- **Discovery:** Official — MCP child gets project dir in env; **do not trust process cwd**
- **Rules:** Append to repo `.claude/CLAUDE.md` on init
- **Refs:** [code.claude.com/docs/en/mcp](https://code.claude.com/docs/en/mcp)

### Codex (`codex`)

- **MCP config:** `~/.codex/config.toml` → `[mcp_servers.scubiee]`
- **Workspace env:** `CODEX_WORKSPACE_ROOT`
- **Discovery:** CLI launched from repo → cwd OK; Desktop/IDE → env or project cwd
- **Rules:** Append to repo `.codex/AGENTS.md` on init
- **Refs:** [developers.openai.com/codex/mcp](https://developers.openai.com/codex/mcp)

### Windsurf (`windsurf`)

- **MCP config:** `~/.codeium/windsurf/mcp_config.json`
- **Workspace env:** `CODEIUM_WINDSURF_WORKSPACE`, `WINDSURF_WORKSPACE` (best-effort)
- **Discovery:** Cascade often spawns with project cwd when a folder is open; no project MCP file API
- **Rules:** None — rely on MCP instructions at spawn
- **Refs:** [docs.windsurf.com/windsurf/cascade/mcp](https://docs.windsurf.com/windsurf/cascade/mcp)

### Continue (`continue`)

- **MCP config:** `~/.continue/config.yaml` → `mcpServers` list
- **Workspace env:** `CONTINUE_PROJECT_DIR`, `CONTINUE_WORKSPACE`; VS Code extension may set `VSCODE_WORKSPACE_FOLDER`
- **Discovery:** env_or_cwd
- **Rules:** Repo `.continue/rules/scubiee.md` on init
- **Refs:** [docs.continue.dev/reference](https://docs.continue.dev/reference)

### Zed (`zed`)

- **MCP config:** `~/.config/zed/settings.json` (or `%APPDATA%\Zed\settings.json`) → `context_servers`
- **Workspace env:** `ZED_PROJECT_DIR`, `ZED_WORKSPACE` (best-effort)
- **Discovery:** Project-scoped servers use project root as cwd; global-only may spawn from `$HOME` — resolver falls back to cwd walk + env
- **Rules:** None
- **Refs:** [zed.dev/docs/ai/mcp](https://zed.dev/docs/ai/mcp)

### OpenCode (`opencode`)

- **MCP config:** `~/.config/opencode/opencode.json` → `mcp.scubiee` with `type: local`, `environment` (not `env`)
- **Workspace env:** `OPENCODE_DEFAULT_PROJECT`, `OPENCODE_PROJECT`
- **Discovery:** CLI `--dir` sets cwd; global config without project override
- **Rules:** Append to repo `.config/opencode/AGENTS.md` on init
- **Refs:** [opencode.ai/docs/mcp-servers](https://opencode.ai/docs/mcp-servers)

### Amp (`amp`)

- **MCP config:** `~/.config/amp/settings.json` → literal key `"amp.mcpServers"`
- **Workspace env:** `AMP_PROJECT_DIR`, `AMP_WORKSPACE`
- **Discovery:** env_or_cwd; global MCP skips workspace approval
- **Rules:** Append to repo `.config/amp/AGENTS.md` on init
- **Refs:** [ampcode.com/manual/mcp](https://ampcode.com/manual/mcp)

### Pi (`pi`)

- **MCP config:** `~/.pi/agent/mcp.json` → `mcpServers`
- **Workspace env:** `PI_PROJECT_DIR`, `PI_WORKSPACE`
- **Discovery:** env_or_cwd when agent run from project directory
- **Rules:** Append to repo `.pi/agent/AGENTS.md` on init
- **Refs:** [badlogic/pi-mono coding-agent docs](https://github.com/badlogic/pi-mono)

---

## User workflow (global hosts)

```bash
scubiee setup                    # once per machine
scubiee connect --cursor --claude-code --codex   # once globally (pick your tools)
# open any repo
scubiee init .                   # per repo you want indexed
# restart IDE / reload MCP
```

For **special-4 only**, add: run connect from inside each repo (or accept project MCP pin on init — future option).

---

## Running tests

```bash
uv run pytest tests/test_global_mcp_hosts.py -v
uv run pytest tests/test_connect_formats.py -v
uv run pytest tests/test_mcp_repo_resolution.py -v
```
