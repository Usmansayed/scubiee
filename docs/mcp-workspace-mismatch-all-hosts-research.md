# Research: MCP workspace / folder mismatch across all Scubiee connect hosts

**Date:** 2026-08-26  
**Scope:** Every tool in `pipeline.tool_registry.TOOLS` — does global MCP get the open project, and what have vendors / other MCP installers already figured out?  
**Companion:** [`cursor-mcp-workspace-resolution-research.md`](./cursor-mcp-workspace-resolution-research.md) (Cursor deep-dive)

---

## 1. The shared problem

Repo-aware MCP servers (Scubiee, Serena, codegraph, Laravel Boost, …) need the **open project root**. Hosts often:

- spawn stdio MCP with **wrong `cwd`** (`$HOME`, `/`, IDE install dir), and/or
- do **not** pass workspace env, and/or
- do **not** expand `${workspaceFolder}` in **user-global** config.

Scubiee today resolves via IDE env → `CTX_PROJECT_ID` → cwd walk → absolute `CTX_REPO` → **`Path.cwd()`**. When spawn cwd is home, agents see `managed=false` even if the repo is indexed.

There is **no single fix for all hosts**. The ecosystem converges on **four patterns**:

| Pattern | Idea | Best when |
|---------|------|-----------|
| **P1 — Host-injected env** | Host sets `CLAUDE_PROJECT_DIR` / similar; server reads it | Host documents a stable env |
| **P2 — Config interpolation** | `"CTX_REPO": "${workspaceFolder}"` in mcp.json | Host expands vars in global config (Cursor) |
| **P3 — Explicit `cwd` in MCP config** | `"cwd": "${workspaceFolder}"` or absolute | Host supports `cwd` and expands it (Cline/Roo/Codex) |
| **P4 — Per-project MCP file + absolute pin** | `.kiro/.../mcp.json` with absolute `CTX_REPO` | Host cannot expand vars / cannot pass cwd from global (Kiro, VS Code user MCP) |

**Protocol-level (P5):** MCP **Roots** (`roots/list`) — Claude Code implements it; Cursor lists Roots as supported. Scubiee does **not** request Roots yet → follow-up after P1–P4.

---

## 2. Per-tool matrix (research verdict)

### Cursor — **P2 (confirmed)**

| Item | Finding |
|------|---------|
| Failure mode | Global MCP spawn cwd ≠ workspace; no `CURSOR_PROJECT_DIR` |
| Official fix surface | `${workspaceFolder}` in `command`/`args`/`env` ([docs](https://cursor.com/docs/mcp)) |
| Ecosystem | codegraph: global `${workspaceFolder}`; context-mode: `CURSOR_CWD=${workspaceFolder}` |
| Scubiee today | Global, **no** workspace hint → Mac fail observed |
| **Recommended** | Global: `CTX_REPO` + `CURSOR_PROJECT_DIR` = `${workspaceFolder}` |
| Not | Absolute global pin; not full Kiro special-4 by default |

---

### Claude Code — **P1 (best — host already injects)**

| Item | Finding |
|------|---------|
| Official | Claude Code sets **`CLAUDE_PROJECT_DIR`** on the MCP child to the project root ([docs](https://code.claude.com/docs/en/mcp)) |
| Also | Answers MCP **`roots/list`** (launch dir + `--add-dir`) |
| Caveat | User-scope helper cwd may be `~/.claude`; **do not trust process cwd** — trust `CLAUDE_PROJECT_DIR` |
| Caveat | Some reports that `--scope user` storage is path-keyed under `projects[...]` ([#16728](https://github.com/anthropics/claude-code/issues/16728)); Scubiee writes top-level `mcpServers` in `~/.claude.json` (correct for true user-wide) |
| Scubiee today | **Does not read `CLAUDE_PROJECT_DIR`** in `_IDE_WORKSPACE_ENV_KEYS` |
| **Recommended** | Add `CLAUDE_PROJECT_DIR` to resolver (no connect UX change). Optional later: Roots client |
| Not | Special-4 / absolute pin unless P1 fails in the field |

---

### Codex (OpenAI) — **P3 + read `CODEX_WORKSPACE_ROOT`**

| Item | Finding |
|------|---------|
| Official | `cwd` is a first-class `[mcp_servers.*]` field in `config.toml` ([docs](https://developers.openai.com/codex/mcp)) |
| Also | Project `.codex/config.toml` (trusted projects) for per-repo MCP |
| Known bugs | VS Code Codex extension often spawns MCP with **wrong cwd** (install dir / HOME) ([#4222](https://github.com/openai/codex/issues/4222), [#9989](https://github.com/openai/codex/issues/9989)) |
| Workaround from issues | Set `cwd` in config; at tool-call time Codex may inject **`CODEX_WORKSPACE_ROOT`** |
| Scubiee today | Global TOML, no `cwd`, no `CODEX_WORKSPACE_ROOT` in resolver |
| **Recommended** | (1) Read `CODEX_WORKSPACE_ROOT` in resolver. (2) If Codex expands it, set `cwd = "${workspaceFolder}"` or document project `.codex/config.toml` for IDE. (3) CLI often OK via process cwd when user launches from repo |
| Risk | `${workspaceFolder}` may be IDE-only; verify CLI vs extension before shipping TOML `cwd` |

---

### Kiro — **P4 (already Scubiee special-4)**

| Item | Finding |
|------|---------|
| Failure mode | Global MCP cannot bind open workspace ([#10486](https://github.com/kirodotdev/Kiro/issues/10486) cited in our connect research) |
| Official | Workspace MCP at `.kiro/settings/mcp.json` + user `~/.kiro/settings/mcp.json` |
| Ecosystem | Absolute paths preferred; relative `.kiro/` can resolve to home by mistake ([#5653](https://github.com/kirodotdev/Kiro/issues/5653)) |
| Scubiee today | Global + **workspace-local absolute `CTX_REPO`** when connect runs in project ✅ |
| **Recommended** | Keep P4. Do not rely on `${workspaceFolder}` in global Kiro config |
| UX | Loud notice: run `connect --kiro` **inside each repo** |

---

### VS Code / GitHub Copilot — **P4 (already special-4)**

| Item | Finding |
|------|---------|
| Failure mode | **User** `mcp.json` does **not** expand `${workspaceFolder}` ([vscode#245905](https://github.com/microsoft/vscode/issues/245905)) |
| Official | Project `.vscode/mcp.json` can use workspace; Copilot CLI has separate `~/.copilot/mcp-config.json` |
| Scubiee today | Global VS Code + Copilot CLI + **project** `.vscode/mcp.json` + `.mcp.json` with absolute `CTX_REPO` ✅ |
| **Recommended** | Keep P4. Optional: also set project `cwd` / `WORKSPACE_FOLDER` where schema allows (already partially done for vscode schema when `pin_repo`) |
| Not | Expect global `${workspaceFolder}` to work (that’s Cursor, not VS Code) |

---

### Cline — **P3 improving + keep P4 belt**

| Item | Finding |
|------|---------|
| Host work | PRs: `cwd` option ([#2937](https://github.com/cline/cline/pull/2937)); expand `${workspaceFolder}` in cwd/env ([#2990](https://github.com/cline/cline/pull/2990)); default cwd → workspace |
| Still broken reports | Global spawn with `cwd=/` ([#9950](https://github.com/cline/cline/issues/9950), 2026) |
| Scubiee today | Global (VS Code storage + CLI) + **project** `.cline/mcp.json` with absolute pin ✅ |
| **Recommended** | Keep P4. Additionally write `"cwd": "${workspaceFolder}"` on Cline entries where the host expands it (newer Cline). Resolver: keep `WORKSPACE_FOLDER` |
| Why keep project pin | Older Cline / globalStorage path still flaky |

---

### Roo Code — **P3 + keep P4**

| Item | Finding |
|------|---------|
| Official / PRs | `cwd` supported; **defaults to workspace folder** ([Roo PR #2171](https://github.com/RooVetGit/Roo-Code/pull/2171)); project `.roo/mcp.json` |
| Scubiee today | Global globalStorage + **project** `.roo/mcp.json` absolute pin ✅ |
| **Recommended** | Keep P4. Prefer project file; optional `"cwd": "${workspaceFolder}"` on global if version expands it |
| Note | Better host defaults than Kiro, but globalStorage-only still risky → keep special-4 |

---

### Windsurf (Cascade) — **P2 if expanded, else wrapper / P4-like**

| Item | Finding |
|------|---------|
| Config | **Global only** `~/.codeium/windsurf/mcp_config.json` — **no** project MCP ([community](https://www.rapidevelopers.com/mcp-tutorial/how-to-connect-mcp-to-windsurf)) |
| Failure mode | MCP often **not** started in project root (Laravel Boost [#47](https://github.com/laravel/boost/issues/47)) |
| Ecosystem fixes | Some use `${workspaceFolder}` in args; others use **launcher scripts** that discover Windsurf’s active project; or absolute per-project server names |
| Scubiee today | Global only, no workspace hint |
| **Recommended** | (1) Try `CTX_REPO=${workspaceFolder}` in Windsurf global (verify expansion). (2) If not expanded: document launcher or accept “one active project” limitation. (3) Do **not** invent fake project mcp.json Windsurf ignores |
| Risk | Highest ambiguity after Cursor; needs Mac+Win smoke |

---

### Continue — **project YAML preferred**

| Item | Finding |
|------|---------|
| Official | Workspace `.continue/mcpServers/*.yaml` (array schema) + user `~/.continue/config.yaml` |
| Scubiee today | User YAML only |
| **Recommended** | Prefer writing **project** `.continue/mcpServers/context-engine.yaml` with absolute `CTX_REPO` or `${workspaceFolder}` if Continue expands it; keep global as fallback |
| Class | Closer to P4 than pure global |

---

### Zed — **cwd careful; remote is special**

| Item | Finding |
|------|---------|
| Config | `context_servers` in user `settings.json` |
| Issues | Remote SSH: local MCP got **remote** cwd ([#47671](https://github.com/zed-industries/zed/issues/47671)); fixes for wrong-dir spawn ([#39243](https://github.com/zed-industries/zed/pull/39243)); optional `"remote": true` for remote MCP |
| Scubiee today | Global only |
| **Recommended** | Local: rely on Zed workspace cwd when healthy; add env pin only if field-validated. Document remote SSH as unsupported or require remote MCP |
| Not | Blind `${workspaceFolder}` without Zed docs confirmation |

---

### OpenCode — **global `environment`; project mcp may shadow**

| Item | Finding |
|------|---------|
| Schema | Global `opencode.json` → `mcp.*.environment` (not `env`) |
| Caveat | Project `opencode.json` with `mcp` can **shallow-replace** global servers (our connect research) |
| Ecosystem | Some servers use `OPENCODE_DEFAULT_PROJECT` env |
| Scubiee today | Global, no project pin (intentional) |
| **Recommended** | Keep global-only; add resolver support for `OPENCODE_DEFAULT_PROJECT` if we set it. Avoid project mcp for Scubiee. Trust CLI cwd when user runs from repo |
| Optional | Document setting `CTX_REPO` only in a **wrapper** if OpenCode expands nothing |

---

### Amp — **global OK for availability; cwd TBD**

| Item | Finding |
|------|---------|
| Official | Global `amp.mcpServers` without workspace approval friction |
| Scubiee today | Global only |
| **Recommended** | Resolver: cwd when launched from project. No special-4 unless reports appear. Low priority smoke |

---

### Pi — **adapter-dependent**

| Item | Finding |
|------|---------|
| Config | `~/.pi/agent/mcp.json` + `pi-mcp-adapter` |
| Scubiee today | Global only |
| **Recommended** | Same as Amp until evidence; read any adapter-documented project env if found |

---

## 3. Cross-cutting ecosystem solutions (what “MCP people” do)

1. **Never trust `getcwd()` alone** — every serious repo MCP reads a host env or config pin first (Claude’s `CLAUDE_PROJECT_DIR`, Cursor’s `${workspaceFolder}`, Codex’s `CODEX_WORKSPACE_ROOT` / `cwd`).
2. **Prefer host-native interpolation over absolute global pins** when the host expands vars (Cursor ≠ VS Code).
3. **Per-project MCP file** when the host cannot expand / cannot pass workspace from user config (Kiro, VS Code user MCP, Cline/Roo belt).
4. **Launcher wrappers** when the host is global-only and does not expand vars (Windsurf community pattern).
5. **MCP Roots** as the long-term protocol answer (Claude Code already; Cursor claims support) — Scubiee should implement `roots/list` consumption as a second wave.
6. **codegraph / context-mode / qdrant-rag** all independently rediscovered the same Cursor/Windsurf cwd bug and fixed with **env injection**, not “reinstall on each OS.”

---

## 4. Scubiee implementation plan (priority)

### Wave A — resolver (safe, all hosts)

Extend `_IDE_WORKSPACE_ENV_KEYS` / pin readers to include:

- `CLAUDE_PROJECT_DIR` (**Claude Code — official**)
- `CODEX_WORKSPACE_ROOT` (Codex IDE workaround)
- `CURSOR_PROJECT_DIR` / `CURSOR_WORKSPACE` / `CURSOR_CWD` (after connect writes them)
- `OPENCODE_DEFAULT_PROJECT` (if we set it)
- Keep: `WORKSPACE_FOLDER`, `VSCODE_*`, `COPILOT_*`, `INIT_CWD`

Treat literal unexpanded `${workspaceFolder}` as empty.

### Wave B — connect writers (host-specific)

| Tool | Change |
|------|--------|
| **Cursor** | Global env: `CTX_REPO=${workspaceFolder}`, `CURSOR_PROJECT_DIR=${workspaceFolder}` |
| **Claude Code** | No pin required; rely on Wave A |
| **Codex** | Add `cwd` if verified; else document project `.codex/config.toml`; read `CODEX_WORKSPACE_ROOT` |
| **Kiro / Copilot / Cline / Roo** | Keep special-4 absolute project pins; add `cwd: ${workspaceFolder}` where schema allows |
| **Windsurf** | Try `${workspaceFolder}` in `CTX_REPO`; smoke; fallback doc/launcher |
| **Continue** | Prefer project `.continue/mcpServers/…` with pin |
| **Zed / OpenCode / Amp / Pi** | Wave A first; escalate only if field bugs |

### Wave C — protocol

- Implement MCP Roots client in `mcp_locate` when the host advertises roots.
- Prefer Roots over cwd when both exist.

### Explicit non-goals

- One absolute `CTX_REPO` in every global mcp.json (breaks multi-repo).
- Treating Cursor like Kiro (absolute per-repo) as the **default** (Cursor has a better native tool: `${workspaceFolder}`).
- Assuming Windows spawn always works — same writers on both OSes.

---

## 5. Validation matrix (must-run before calling production)

| Host | Test |
|------|------|
| Cursor Mac/Win | `status().repo` == open folder after connect; second repo window switches |
| Claude Code | `CLAUDE_PROJECT_DIR` seen by MCP; `managed=true` without absolute pin |
| Codex CLI vs IDE | CLI from repo OK; IDE with/without `cwd` documented |
| Kiro | Global alone → wrong/unmanaged; project connect → managed |
| Copilot | User MCP alone insufficient; project `.vscode/mcp.json` required |
| Cline / Roo | Project file present; optional cwd expansion on new builds |
| Windsurf | Confirm whether `${workspaceFolder}` expands; record result |

---

## 6. Decision summary

| Host | Mismatch risk | Perfect fix class | Scubiee action |
|------|---------------|-------------------|----------------|
| Cursor | **High** (observed) | **P2** interpolation | Write `${workspaceFolder}` in global |
| Claude Code | Medium (cwd wrong, env OK) | **P1** host env | **Read `CLAUDE_PROJECT_DIR`** |
| Codex | High in IDE | **P3** cwd + env | Read `CODEX_WORKSPACE_ROOT`; set `cwd` if safe |
| Kiro | **High** | **P4** project pin | Keep special-4 |
| Copilot / VS Code | **High** | **P4** | Keep special-4 |
| Cline / Roo | High → Medium | **P4 + P3** | Keep project pin; add cwd |
| Windsurf | High | **P2 or wrapper** | Smoke `${workspaceFolder}` |
| Continue | Medium | Project YAML | Prefer project mcpServers |
| Zed | Medium (remote High) | cwd / remote flag | Document; Wave A |
| OpenCode / Amp / Pi | Low–Med | Wave A | Resolver first |

**Bottom line:** The industry did figure this out — but **per host**, not one magic flag. Scubiee’s special-4 is still right for Kiro/Copilot/Cline/Roo. Cursor and Claude Code should **not** be forced into that model; they already expose better native signals (`${workspaceFolder}`, `CLAUDE_PROJECT_DIR`) that we currently underuse.
