# All-hosts MCP workspace resolution — solution report

**Date:** 2026-08-26  
**Status:** Wave 1 implemented in **0.2.83** (project MCP pins for Cursor/Codex/Continue/OpenCode/Amp/Pi + `WORKSPACE_FOLDER_PATHS`). Windsurf / Roots still deferred.  
**Scope:** Every slug in `pipeline.tool_registry.TOOLS`  
**Why rewrite:** Prior research preferred Cursor **global** `${workspaceFolder}`. Live Mac proof + fresh web research show that is **wrong** for durable Scubiee. This report is the corrected per-tool plan.

**Related:**

- Live Mac failure: [`mac-session-2026-08-26-workspace-token-issue.md`](./mac-session-2026-08-26-workspace-token-issue.md)
- Older matrix (partially outdated on Cursor): [`mcp-workspace-mismatch-all-hosts-research.md`](./mcp-workspace-mismatch-all-hosts-research.md)
- Cursor deep-dive (update Cursor section mentally with this report): [`cursor-mcp-workspace-resolution-research.md`](./cursor-mcp-workspace-resolution-research.md)

---

## 1. Shared problem (not Mac-only)

Repo-aware MCP (Scubiee) must know the **open project root**. Hosts often:

1. Spawn stdio MCP with **wrong cwd** (`$HOME`, `/`, IDE install dir)
2. Leave `${workspaceFolder}` **literal** in env when config is **user-global**
3. Do not inject a stable workspace env

Scubiee resolver order (`mcp_locate`): IDE env → `CTX_PROJECT_ID` → cwd walk for `.context-engine` → live `CTX_REPO` → `Path.cwd()`.

**OS is not the bug.** The same Cursor/VS Code-family spawn rules apply on Mac and Windows. Mac measured the Cursor global-token failure; Windows users report the same wrong-cwd class of bugs in Cursor forums.

---

## 2. Solution patterns (pick per host)

| ID | Pattern | When to use |
|----|---------|-------------|
| **P1** | Host-injected env (`CLAUDE_PROJECT_DIR`, …) | Host documents a stable spawn env |
| **P2** | Config interpolation `${workspaceFolder}` | Host expands it **in that config scope** |
| **P3** | Explicit `cwd` in MCP config | Host supports `cwd` (absolute or expanded) |
| **P4** | **Project MCP file + absolute `CTX_REPO` (+ `CTX_PROJECT_ID`)** | Global cannot bind workspace (special-4 today) |
| **P5** | MCP `roots/list` | Protocol follow-up after P1–P4 |
| **P6** | Read host-injected multi-path env (`WORKSPACE_FOLDER_PATHS`) | Cursor (and similar) inject without config tokens |

**Hard rule:** Never put an **absolute** `CTX_REPO` in a **user-global** MCP file that applies to every workspace (poisons other folders). Absolute pins belong in **project** files only.

---

## 3. Executive matrix (implement this)

| Tool | Slug | Today | Verdict | Primary fix | Secondary |
|------|------|-------|---------|-------------|-----------|
| Cursor | `cursor` | Global + `${workspaceFolder}` tokens | **Broken** (live Mac; docs imply project scope) | **P4** project `.cursor/mcp.json` absolute pin | P6 `WORKSPACE_FOLDER_PATHS`; optional P2 **only** in project file |
| Claude Code | `claude-code` | Global `~/.claude.json` | **OK if resolver reads env** | **P1** keep/trust `CLAUDE_PROJECT_DIR` | P5 Roots later |
| Codex | `codex` | Global TOML + token cwd | **Risky** (Desktop cwd `/`) | **P4** project `.codex/config.toml` absolute `cwd` + env | Read `CODEX_WORKSPACE_ROOT` |
| Kiro | `kiro` | Special-4 | **Correct** | Keep **P4** | No `${workspaceFolder}` (unsupported) |
| Windsurf | `windsurf` | Global only | **Hard** (no project MCP) | Absolute pin **only if** single-active-repo UX **or** wrapper script | Smoke `${workspaceFolder}`; document reconnect |
| Copilot / VS Code | `copilot` | Special-4 | **Correct** | Keep **P4** | User MCP never expands vars ([vscode#245905](https://github.com/microsoft/vscode/issues/245905)) |
| Cline | `cline` | Special-4 | **Correct** | Keep **P4** | Optional `cwd: ${workspaceFolder}` on newer Cline |
| Roo Code | `roo-code` | Special-4 | **Correct** | Keep **P4** | Host defaults cwd→workspace; still keep project pin |
| Continue | `continue` | Global YAML | **Improve** | **P4/P2** write `.continue/mcpServers/context-engine.yaml` with `${workspaceFolder}` or absolute | Continue PR adds interpolation |
| Zed | `zed` | Global settings | **Usually OK** | Trust project-root cwd; optional env pin | Remote SSH edge cases |
| OpenCode | `opencode` | Global `opencode.json` | **Improve** | **P4** project `opencode.json` with `environment.CTX_REPO` + optional `cwd` | Official `cwd` resolves from workspace |
| Amp | `amp` | Global settings | **Improve** | **P4** `.amp/settings.json` absolute pin (needs `amp mcp approve`) | Global alone insufficient |
| Pi | `pi` | Global `~/.pi/agent/mcp.json` | **Improve** | **P4** project `.mcp.json` or `.pi/mcp.json` absolute pin | Prefer shared `.mcp.json` |

---

## 4. Per-tool research + recommended Scubiee connect behavior

### 4.1 Cursor (`cursor`) — **change required**

**Evidence**

- Live Mac (2026-08-26): global `CTX_REPO=${workspaceFolder}` left **literal**; MCP cwd `$HOME`; `status.managed=false`.
- Official docs: `${workspaceFolder}` = *“project root (the folder that contains `.cursor/mcp.json`”* → implies **project** config, not `~/.cursor/mcp.json`.
- VS Code user MCP: variables do not resolve in user-level config ([#245905](https://github.com/microsoft/vscode/issues/245905)).
- Ecosystem: [Gortex #19](https://github.com/zzet/gortex/issues/19) — global MCP cwd=`~/`; **project** `.cursor/mcp.json` works; global often wins unless disabled.
- Forum: wrong MCP cwd; staff mention **`WORKSPACE_FOLDER_PATHS`** ([forum](https://forum.cursor.com/t/workspace-level-mcp-json-execution-context/98599)).

**Not Mac-only:** same Cursor model on Windows; wrong-cwd reports exist on Windows too.

**Scubiee solution**

1. On `connect --cursor` **inside a repo**: write **project** `.cursor/mcp.json` with absolute `CTX_REPO` + `CTX_PROJECT_ID` (same idea as special-4). Project wins over global on same server name.
2. Global `~/.cursor/mcp.json`: keep command/args/rules; **omit** absolute pin; optionally omit broken tokens or leave tokens only as non-authoritative hints.
3. Resolver: add **`WORKSPACE_FOLDER_PATHS`** (first path if comma-separated) to `_IDE_WORKSPACE_ENV_KEYS`.
4. Loud UX: “run `connect --cursor` in each repo you use” (or document that project MCP is required).
5. Do **not** rely on global `${workspaceFolder}` alone.

**Acceptance:** After connect in repo A, agent `status().repo` == A on Mac and Windows; open repo B after connect-in-B works without poisoning A.

---

### 4.2 Claude Code (`claude-code`) — **mostly done**

**Evidence**

- Official: Claude Code sets **`CLAUDE_PROJECT_DIR`** on the MCP child to project root; do not trust process cwd ([docs](https://code.claude.com/docs/en/mcp)).
- Also implements MCP **`roots/list`** (+ `list_changed` in recent versions).

**Scubiee solution**

1. Keep reading `CLAUDE_PROJECT_DIR` (already in resolver).
2. Keep global `~/.claude.json` without absolute `CTX_REPO`.
3. Follow-up: implement Roots client (P5) for multi-dir sessions.
4. No special-4 unless field reports P1 failure.

---

### 4.3 Codex (`codex`) — **change required for IDE/Desktop**

**Evidence**

- Official: `[mcp_servers.*].cwd` is first-class; project `.codex/config.toml` for trusted projects ([docs](https://developers.openai.com/codex/mcp)).
- Desktop: MCP may show cwd `/` until **project** config sets explicit absolute `cwd` ([#14449](https://github.com/openai/codex/issues/14449)).
- CLI often OK when launched from repo.

**Scubiee solution**

1. On `connect --codex` in a repo: write **project** `.codex/config.toml` with absolute `cwd` + `env.CTX_REPO` / `CTX_PROJECT_ID`.
2. Global TOML: no absolute pin; do not depend on `${workspaceFolder}` in global (IDE-only / unreliable).
3. Resolver already lists `CODEX_WORKSPACE_ROOT` — keep.
4. UX: trust project for Desktop; CLI may work from cwd.

---

### 4.4 Kiro (`kiro`) — **keep special-4**

**Evidence**

- Workspace `.kiro/settings/mcp.json` + user `~/.kiro/settings/mcp.json`; workspace wins ([docs](https://kiro.dev/docs/mcp/configuration/)).
- **No** `${workspaceFolder}` substitution ([#5659](https://github.com/kirodotdev/Kiro/issues/5659)); relative paths resolve from **install dir** ([#6525](https://github.com/kirodotdev/Kiro/issues/6525)).
- Spawn cwd often install dir, not workspace.

**Scubiee solution**

1. Keep absolute `CTX_REPO` in project `.kiro/settings/mcp.json`.
2. Never rely on tokens in Kiro MCP JSON.
3. Loud “connect inside each repo.”

---

### 4.5 Windsurf (`windsurf`) — **hardest; no project MCP**

**Evidence**

- Only global `~/.codeium/windsurf/mcp_config.json` ([guides](https://connector.zone/guides/adding-mcp-servers-in-windsurf/)).
- Explicit: **no project-scoped MCP file**.
- Supports `${env:VAR}` in some guides; **`${workspaceFolder}` expansion not confirmed** for Windsurf.

**Scubiee solution (pick one product stance)**

| Option | Pros | Cons |
|--------|------|------|
| **A.** Absolute `CTX_REPO` in global on connect | Works for that repo now | Poisons other folders until reconnect |
| **B.** Launcher script that discovers “active” Windsurf project | Multi-repo safer | Fragile / host-private |
| **C.** Document “one Scubiee-active repo; re-run connect when switching” | Honest | UX friction |

**Recommendation:** **C + A** — on `connect --windsurf` pin absolute `CTX_REPO` in global **and** print a clear warning that Windsurf is global-only; re-run connect when switching projects. Optional smoke for `${workspaceFolder}` later; do not ship tokens as primary.

---

### 4.6 VS Code / Copilot (`copilot`) — **keep special-4**

**Evidence**

- User MCP does **not** expand `${workspaceFolder}` ([vscode#245905](https://github.com/microsoft/vscode/issues/245905)).
- Project `.vscode/mcp.json` / `.mcp.json` is the portable fix.

**Scubiee solution**

1. Keep current special-4 project pins.
2. Keep Copilot CLI global file without absolute pin (or pin only via project `.mcp.json`).

---

### 4.7 Cline (`cline`) — **keep special-4**

**Evidence**

- Host added `cwd` + `${workspaceFolder}` expansion in newer builds ([#2937](https://github.com/cline/cline/pull/2937), [#2990](https://github.com/cline/cline/pull/2990)).
- Still reports of bad global spawn cwd ([#9950](https://github.com/cline/cline/issues/9950)).

**Scubiee solution**

1. Keep project `.cline/mcp.json` absolute pin.
2. Optionally add `"cwd": "${workspaceFolder}"` where schema allows (belt).

---

### 4.8 Roo Code (`roo-code`) — **keep special-4**

**Evidence**

- `cwd` supported; defaults toward workspace ([Roo PR #2171](https://github.com/RooVetGit/Roo-Code/pull/2171)).
- Project `.roo/mcp.json` exists.

**Scubiee solution**

1. Keep project absolute pin (globalStorage alone still risky).
2. Optional `cwd` token on newer Roo.

---

### 4.9 Continue (`continue`) — **add project MCP block**

**Evidence**

- Prefer `.continue/mcpServers/*.yaml` in the workspace ([docs](https://docs.continue.dev/customize/deep-dives/mcp)).
- Interpolation PR: `${workspaceFolder}` in command/args/cwd/env ([#13036](https://github.com/continuedev/continue/pull/13036)).
- Global `~/.continue/config.yaml` alone is weaker for repo pins.

**Scubiee solution**

1. On `connect --continue` in a repo: write `.continue/mcpServers/context-engine.yaml` with `cwd` / `env.CTX_REPO` = `${workspaceFolder}` **or** absolute pin.
2. Keep global rules; avoid absolute pin in global YAML.
3. Consider adding Continue to an expanded “project MCP” set (not only special-4).

---

### 4.10 Zed (`zed`) — **low urgency**

**Evidence**

- Context servers default **cwd = project root** ([#35354](https://github.com/zed-industries/zed/issues/35354) — request for override; maintainers note default is project root).
- Remote SSH has separate spawn bugs (local process + remote path).

**Scubiee solution**

1. Keep global settings entry without absolute pin.
2. Rely on project-root cwd + id walk; optional `CTX_REPO` only if field fails.
3. Document remote-SSH limitation.

---

### 4.11 OpenCode (`opencode`) — **add project config**

**Evidence**

- Global `~/.config/opencode/opencode.json` + **project** `opencode.json` (project wins) ([docs](https://opencode.ai/docs/config/)).
- Local MCP supports **`cwd`** (relative resolves from workspace) and `environment` ([docs](https://opencode.ai/docs/mcp-servers)).

**Scubiee solution**

1. On `connect --opencode` in a repo: merge into **project** `opencode.json` with `environment.CTX_REPO` / `CTX_PROJECT_ID` absolute, and `cwd` = project root (or `.`).
2. Global file: command only, no absolute pin.
3. Resolver already has `OPENCODE_DEFAULT_PROJECT` — keep for any host-injected hint.

---

### 4.12 Amp (`amp`) — **add workspace settings**

**Evidence**

- User `~/.config/amp/settings.json` + workspace `.amp/settings.json` under key `amp.mcpServers` ([manual](https://ampcode.com/manual/mcp.md)).
- Workspace MCP requires **`amp mcp approve`**.
- Precedence: workspace > user.

**Scubiee solution**

1. On `connect --amp` in a repo: write `.amp/settings.json` with absolute `CTX_REPO` + `CTX_PROJECT_ID`.
2. Print next step: `amp mcp approve context-engine`.
3. Global: no absolute pin (tools available everywhere but unbound).

---

### 4.13 Pi (`pi`) — **add project `.mcp.json` / `.pi/mcp.json`**

**Evidence**

- Layered configs; prefer project `.mcp.json` or `.pi/mcp.json` over only `~/.pi/agent/mcp.json` ([pi-mcp-adapter](https://github.com/nicobailon/pi-mcp-adapter)).

**Scubiee solution**

1. On `connect --pi` in a repo: write project `.mcp.json` (or `.pi/mcp.json`) with absolute pin.
2. Keep global Pi mcp.json for discovery without absolute pin.
3. Document preference for shared `.mcp.json`.

---

## 5. Resolver upgrades (all hosts benefit)

Add / keep env keys (skip unexpanded `${…}`):

| Env | Host |
|-----|------|
| `CLAUDE_PROJECT_DIR` | Claude Code (have) |
| `CODEX_WORKSPACE_ROOT` | Codex (have) |
| `CURSOR_*` / `WORKSPACE_FOLDER` | Cursor hints (have) |
| **`WORKSPACE_FOLDER_PATHS`** | Cursor (staff-mentioned; **missing today**) |
| `OPENCODE_DEFAULT_PROJECT` | OpenCode (have) |
| `COPILOT_*` / `VSCODE_*` | Copilot (have) |

Follow-up wave: MCP **Roots** client for Claude Code + Cursor (both claim Roots).

---

## 6. Recommended implementation waves

### Wave 1 — unblock Mac Cursor + align non–special-4 that have project files

1. Cursor → project `.cursor/mcp.json` absolute pin (promote toward special-4 behavior for MCP only).
2. Resolver: `WORKSPACE_FOLDER_PATHS`.
3. Codex → project `.codex/config.toml` absolute `cwd` + env.
4. Continue → `.continue/mcpServers/context-engine.yaml`.
5. OpenCode → project `opencode.json` env + cwd.
6. Amp → `.amp/settings.json` + approve hint.
7. Pi → project `.mcp.json`.

### Wave 2 — Windsurf policy + polish

1. Windsurf global absolute pin + loud “reconnect on switch” warning (or wrapper spike).
2. Cline/Roo optional `cwd` tokens.
3. Docs: connect matrix in web-info.

### Wave 3 — protocol

1. MCP Roots consumption.
2. Live smoke matrix Mac+Win for every slug.

---

## 7. What **not** to do

- Absolute `CTX_REPO` in Cursor/Claude **user-global** as the default multi-repo strategy.
- Treat global `${workspaceFolder}` as fixed for Cursor after the Mac measurement.
- Assume Windsurf has a project MCP file (it does not).
- Assume Kiro will expand `${workspaceFolder}` (it does not today).
- Assume Admin/reboot fixes IDE spawn bugs (unrelated; see Windows uv lock deferred doc).

---

## 8. Live verification checklist (when implementing)

For each slug after `disconnect` → `connect --<slug>` from an enrolled repo:

| Check | Pass |
|-------|------|
| Config file location matches table above | yes |
| MCP process env: `CTX_REPO` is real path (not `${…}`) **or** host env (Claude) is set | yes |
| Agent/tool `status().managed` | true |
| `status().repo` | equals open folder |
| Second repo (where project MCP exists) | connect there; no cross-pin |

Windsurf: document expected “must reconnect” if using global absolute pin.

---

## 9. Sources (web + field)

| Source | Used for |
|--------|----------|
| [cursor.com/docs/mcp](https://cursor.com/docs/mcp) | `${workspaceFolder}` defined via folder containing `.cursor/mcp.json` |
| [vscode#245905](https://github.com/microsoft/vscode/issues/245905) | User-level MCP vars don’t resolve |
| [Gortex#19](https://github.com/zzet/gortex/issues/19) | Global Cursor MCP cwd = home; project MCP works |
| [Cursor forum MCP cwd](https://forum.cursor.com/t/workspace-level-mcp-json-execution-context/98599) | `WORKSPACE_FOLDER_PATHS` |
| [Claude Code MCP docs](https://code.claude.com/docs/en/mcp) | `CLAUDE_PROJECT_DIR`, Roots |
| [OpenAI Codex MCP](https://developers.openai.com/codex/mcp) + [#14449](https://github.com/openai/codex/issues/14449) | `cwd`, project config |
| [Kiro MCP config](https://kiro.dev/docs/mcp/configuration/) + [#5659](https://github.com/kirodotdev/Kiro/issues/5659) | No var sub; absolute paths |
| Windsurf guides (ConnectorZone / StackMCP) | Global-only mcp_config.json |
| [Continue MCP docs](https://docs.continue.dev/customize/deep-dives/mcp) + [#13036](https://github.com/continuedev/continue/pull/13036) | Project mcpServers + interpolation |
| [Zed #35354](https://github.com/zed-industries/zed/issues/35354) | Default cwd = project root |
| [OpenCode MCP docs](https://opencode.ai/docs/mcp-servers) | Project config + `cwd` |
| [Amp MCP manual](https://ampcode.com/manual/mcp.md) | `.amp/settings.json` + approve |
| [pi-mcp-adapter README](https://github.com/nicobailon/pi-mcp-adapter) | `.mcp.json` / `.pi/mcp.json` layers |
| Mac live session notes | Cursor global token failure |

---

## 10. Bottom line

- **Not a MacBook-only bug** — host MCP spawn/config scope.
- **Special-4 (Kiro, Copilot, Cline, Roo) already have the right shape** — keep.
- **Cursor’s real fix matches special-4 MCP (project file + absolute pin)**, not global tokens.
- **Claude Code** is the good citizen (host env) — resolver-first.
- **Windsurf** cannot do true multi-repo project MCP; product must warn + reconnect.
- Extend project-MCP writes to **Cursor, Codex, Continue, OpenCode, Amp, Pi** in Wave 1.
