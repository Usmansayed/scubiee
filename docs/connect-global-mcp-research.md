# Global MCP + rules research (Scubiee `connect`)

**Goal:** One `scubiee connect` run installs **user-global** MCP + rules only. No project files. No `CTX_REPO` pin. Works in every repo forever; the engine/MCP discovers the open workspace at runtime.

**Researched:** 2026-08-23  
**Sources:** Official product docs (Cursor, Claude Code, Codex, Kiro, OpenCode, Amp, VS Code, Zed, Windsurf, Continue, Pi), plus cross-checks on Cline/Roo storage paths.

---

## Design rules for Scubiee

1. Write **only** global/user config paths listed below.
2. Never set `CTX_REPO` in global MCP env (repo-agnostic).
3. Never write `.cursor/mcp.json`, `.mcp.json`, `.vscode/mcp.json`, `opencode.json`, etc. into a project.
4. Schema must match what each host actually parses (wrong key = silent miss).
5. Windows vs Mac paths differ for VS Code-family and Zed; home-relative `~` paths are usually the same shape under `%USERPROFILE%`.

---

## Per-tool matrix

### Cursor

| | Mac / Linux | Windows |
|---|---|---|
| **MCP (global)** | `~/.cursor/mcp.json` | `%USERPROFILE%\.cursor\mcp.json` |
| **Rules (global file)** | `~/.cursor/rules/*.mdc` | `%USERPROFILE%\.cursor\rules\*.mdc` |

- **Schema:** `{ "mcpServers": { "name": { "command", "args", "env" } } }`
- **Notes:** Official help confirms machine-local user rule files under `~/.cursor/rules` (do not sync). Account “User Rules” in Customize UI are separate. Project `.cursor/rules` is **not** used by `connect` (global-only).
- **Refs:** [cursor.com/help/customization/mcp](https://cursor.com/help/customization/mcp), [cursor.com/help/customization/rules](https://cursor.com/help/customization/rules)

### Claude Code

| | Mac / Linux | Windows |
|---|---|---|
| **MCP (user scope)** | `~/.claude.json` → top-level `mcpServers` | `%USERPROFILE%\.claude.json` |
| **Rules (global)** | `~/.claude/CLAUDE.md` | `%USERPROFILE%\.claude\CLAUDE.md` |

- **Schema:** Claude Desktop–style `mcpServers` / `command` / `args` / `env` (no `type` required for stdio).
- **Notes:** `--scope user` is the forever-global scope. Do **not** write project `.mcp.json`. Do **not** put servers under a per-project key inside `~/.claude.json` (that is “local” scope, tied to one folder).
- **Refs:** [code.claude.com/docs/en/mcp](https://code.claude.com/docs/en/mcp)

### Codex (OpenAI)

| | Mac / Linux | Windows |
|---|---|---|
| **MCP** | `~/.codex/config.toml` | `%USERPROFILE%\.codex\config.toml` |
| **Rules** | `~/.codex/AGENTS.md` | `%USERPROFILE%\.codex\AGENTS.md` |

- **Schema (TOML):**
  ```toml
  [mcp_servers.context-engine]
  command = "..."
  args = ["-u", "-m", "pipeline.mcp_locate"]
  env = { KEY = "value" }
  ```
- **Notes:** Override home with `CODEX_HOME`. Prefer `AGENTS.md` over legacy `instructions.md`.
- **Refs:** [developers.openai.com/codex/mcp](https://developers.openai.com/codex/mcp), [developers.openai.com/codex/guides/agents-md](https://developers.openai.com/codex/guides/agents-md)

### Kiro

| | Mac / Linux | Windows |
|---|---|---|
| **MCP (global)** | `~/.kiro/settings/mcp.json` | `%USERPROFILE%\.kiro\settings\mcp.json` |
| **Rules (steering)** | `~/.kiro/steering/context-engine.md` | `%USERPROFILE%\.kiro\steering\context-engine.md` |

- **Schema:** `{ "mcpServers": { ... } }` (Claude-style).
- **Notes:** Workspace `.kiro/...` exists but is **out of scope** for global connect. Global MCP must not pin `CTX_REPO`.
- **Refs:** [kiro.dev/docs/mcp/configuration](https://kiro.dev/docs/mcp/configuration/), [kiro.dev/docs/configuration](https://kiro.dev/docs/configuration/)

### Windsurf (Cascade)

| | Mac / Linux | Windows |
|---|---|---|
| **MCP** | `~/.codeium/windsurf/mcp_config.json` | `%USERPROFILE%\.codeium\windsurf\mcp_config.json` |
| **Rules** | _(no stable file API)_ | same |

- **Schema:** `mcpServers` + command/args/env.
- **Refs:** [docs.windsurf.com/windsurf/cascade/mcp](https://docs.windsurf.com/windsurf/cascade/mcp)

### VS Code / GitHub Copilot

| | Mac | Windows | Linux |
|---|---|---|---|
| **MCP (VS Code user)** | `~/Library/Application Support/Code/User/mcp.json` | `%APPDATA%\Code\User\mcp.json` | `~/.config/Code/User/mcp.json` |
| **MCP (Copilot CLI)** | `~/.copilot/mcp-config.json` | `%USERPROFILE%\.copilot\mcp-config.json` | same under home |
| **Rules (user)** | `~/.copilot/copilot-instructions.md` | same | same |
| **Rules (modular)** | `~/.copilot/instructions/*.instructions.md` | same | same |

- **VS Code schema:** `{ "servers": { "name": { "type": "stdio", "command", "args", "env" } } }`
- **CLI schema:** `{ "mcpServers": { "name": { "type": "local", "command", "args", "env", "tools": ["*"] } } }`
- **Notes:** `scubiee connect --copilot` writes **both** MCP files plus global instructions. Command Palette → **MCP: Open User Configuration** for the VS Code file. Project `.vscode/mcp.json` is unused (global-only).
- **Refs:** [VS Code MCP](https://code.visualstudio.com/docs/copilot/customization/mcp-servers), [Copilot CLI MCP](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers), [custom instructions](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions)

### Cline

| | Mac | Windows | Linux |
|---|---|---|---|
| **MCP (VS Code ext)** | `~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json` | `%APPDATA%\Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json` | `~/.config/Code/User/globalStorage/.../cline_mcp_settings.json` |
| **MCP (Cline CLI / shared)** | `~/.cline/data/settings/cline_mcp_settings.json` | `%USERPROFILE%\.cline\data\settings\cline_mcp_settings.json` | same under home |
| **Rules (global)** | `~/.cline/rules/context-engine.md` | `%USERPROFILE%\.cline\rules\context-engine.md` | same |

- **Schema:** `mcpServers` (Claude-style).
- **Notes:** Scubiee writes **both** VS Code extension + CLI MCP paths when possible so IDE and CLI stay in sync.
- **Refs:** [docs.cline.bot/getting-started/config](https://docs.cline.bot/getting-started/config)

### Roo Code

| | Mac | Windows | Linux |
|---|---|---|---|
| **MCP** | `~/Library/Application Support/Code/User/globalStorage/rooveterinaryinc.roo-cline/settings/mcp_settings.json` | `%APPDATA%\Code\User\globalStorage\rooveterinaryinc.roo-cline\settings\mcp_settings.json` | `~/.config/Code/User/globalStorage/.../mcp_settings.json` |
| **Rules** | _(project `.roo/rules` only — skip for global connect)_ | | |

- **Schema:** `mcpServers` (Claude-style). Distinct from Cline extension id/filename.

### Continue

| | Mac / Linux | Windows |
|---|---|---|
| **MCP** | `~/.continue/config.yaml` (`mcpServers` **list**) | `%USERPROFILE%\.continue\config.yaml` |
| **Rules** | `~/.continue/rules/context-engine.md` | `%USERPROFILE%\.continue\rules\context-engine.md` |

- **Schema:** YAML list items with `name`, `command`, `args`, `env`.
- **Refs:** [docs.continue.dev/reference](https://docs.continue.dev/reference)

### Zed

| | Mac / Linux | Windows |
|---|---|---|
| **MCP** | `~/.config/zed/settings.json` → `context_servers` | `%APPDATA%\Zed\settings.json` → `context_servers` |
| **Rules** | _(no CE file rules)_ | |

- **Schema:**
  ```json
  "context_servers": {
    "context-engine": { "command": "...", "args": [], "env": {} }
  }
  ```
- **Refs:** [zed.dev/docs/ai/mcp](https://zed.dev/docs/ai/mcp), [zed configuring docs](https://github.com/zed-industries/zed/blob/main/docs/src/configuring-zed.md)

### OpenCode

| | Mac / Linux | Windows |
|---|---|---|
| **MCP** | `~/.config/opencode/opencode.json` | `%USERPROFILE%\.config\opencode\opencode.json` |
| **Rules** | `~/.config/opencode/AGENTS.md` (append) | same under home |

- **Schema (v1-style, still widely used):**
  ```json
  {
    "$schema": "https://opencode.ai/config.json",
    "mcp": {
      "context-engine": {
        "type": "local",
        "command": ["python", "-u", "-m", "pipeline.mcp_locate"],
        "enabled": true,
        "environment": { }
      }
    }
  }
  ```
- **Critical:** Key is `environment` (not `env`). `command` is a **single array**. Global file name is **`opencode.json`**, not `config.json`.
- **Caveat:** Some OpenCode versions shallow-replace `mcp` when a project `opencode.json` defines `mcp` — avoid project MCP files if you rely on global servers.
- **Refs:** [opencode.ai/docs/config](https://opencode.ai/docs/config/), [opencode.ai/docs/mcp-servers](https://opencode.ai/docs/mcp-servers/)

### Amp

| | Mac / Linux | Windows |
|---|---|---|
| **MCP** | `~/.config/amp/settings.json` | `%USERPROFILE%\.config\amp\settings.json` (also seen: `%APPDATA%\amp\settings.json` in older guides — prefer `~/.config/amp`) |
| **Rules** | `~/.config/amp/AGENTS.md` | same |

- **Schema:** Literal dotted key **`"amp.mcpServers"`** (not nested `amp: { mcpServers }`).
- **Notes:** Global Amp MCP does **not** require workspace approval (workspace `.amp/settings.json` does).
- **Refs:** [ampcode.com/manual/mcp.md](https://ampcode.com/manual/mcp.md)

### Pi

| | Mac / Linux | Windows |
|---|---|---|
| **MCP** | `~/.pi/agent/mcp.json` (needs `pi-mcp-adapter`) | `%USERPROFILE%\.pi\agent\mcp.json` |
| **Rules** | `~/.pi/agent/AGENTS.md` | same |

- **Schema:** `{ "mcpServers": { ... } }` (plus optional adapter `settings`).
- **Refs:** [badlogic/pi-mono coding-agent docs](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/usage.md)

---

## Scubiee server entry (all hosts)

Base shape from `pipeline.mcp_install.server_entry(repo=None)`:

- `command`: interpreter that can `import pipeline`
- `args`: `["-u", "-m", "pipeline.mcp_locate"]`
- `env`: engine URL, surfaces, sync flags — **no `CTX_REPO`**

Adapters transform this into OpenCode / VS Code / Codex / Amp / Continue / Zed shapes.

---

## User command (target UX)

```bash
scubiee connect --all
# or pick tools:
scubiee connect --cursor --claude-code --codex --kiro --opencode --amp --pi
```

After that: open any repo → restart/reload the IDE or agent → Scubiee MCP + rules are already there.

`scubiee disconnect --all` removes only the Scubiee entries/sections from those same global files.

---

## Explicit non-goals

- Project MCP/rules for team sharing (use docs / manual commit if needed later).
- Pinning one repository in global MCP.
- Amp `%APPDATA%\amp` alternate path unless users report misses on Windows.
