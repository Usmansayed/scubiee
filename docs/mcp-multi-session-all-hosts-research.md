# Multi-session MCP isolation — all-hosts research

**Date:** 2026-08-28  
**Scope:** Every slug in `pipeline.tool_registry.TOOLS`  
**Question:** Can Scubiee isolate recall/pins/handles per **parallel chat** when the same MCP server process serves multiple conversations?

**Related:** [`connect-global-mcp-research.md`](./connect-global-mcp-research.md), [`mcp-workspace-all-hosts-solution-report-2026-08-26.md`](./mcp-workspace-all-hosts-solution-report-2026-08-26.md)

---

## Executive summary (evidence-based)

| Claim | Verdict |
|-------|---------|
| Hosts spawn **one stdio MCP process per server config**, shared across chats | **True** for most (Cursor, Copilot, Claude Code, Kiro, Cline, Roo, …) |
| Hosts pass **conversation/chat id** in MCP subprocess env | **Only Claude Code** documents `CLAUDE_CODE_SESSION_ID` ([env-vars](https://code.claude.com/docs/en/env-vars)) |
| MCP `_meta` carries a standard chat/session id | **No** — 2026-07-28 spec removed protocol sessions; `_meta` has `clientInfo`, not conversation id ([changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)) |
| FastMCP `ctx.client_id` isolates parallel chats | **Unknown** — host-dependent; must be live-tested per host |
| `{host}@proc-{pid}` isolates parallel chats in one MCP process | **No** — same process ⇒ same fallback session |
| Explicit tool `session_id` or `CTX_MCP_SESSION_ID` in MCP env | **Yes** — always works when caller sets it |
| **Pi** spawns fresh MCP per Pi session | **Yes** ([pi-mcp-adapter](https://github.com/nicobailon/pi-mcp-adapter)) — process boundary, not per chat |

**Bottom line:** Multi-chat isolation inside **one shared MCP process** is **not guaranteed** on Cursor, Copilot, Codex, etc. Scubiee’s honest guarantees are:

1. **Separate MCP processes** → separate stores (`{host}@proc-{pid}` or connection id).
2. **Claude Code** → `CLAUDE_CODE_SESSION_ID` at spawn (with resume/caveats below).
3. **Any host** → user sets `CTX_MCP_SESSION_ID` in MCP `env`, or agent passes `session_id` on tools.
4. **Parallel chats, one MCP process, no session signal** → **shared session state** (better than one global file, but not per-chat).

---

## Scubiee resolution order (implementation)

`packages/pipeline/session_isolation.py`:

1. Tool arg `session_id`
2. Request ContextVar (bound per call)
3. FastMCP transport (`client_id` or `conn-{id}`) when inside a live MCP request
4. Host env: `CTX_MCP_SESSION_ID`, then **`CLAUDE_CODE_SESSION_ID`**
5. Best-effort env (`CONVERSATION_ID`, `CHAT_ID`, …) — **unverified** on listed hosts
6. Fallback: `{host}@proc-{pid}` when `CTX_MCP_SESSION_ISOLATE=1`

Connect writes `CTX_MCP_CLIENT=<slug>` and `CTX_MCP_SESSION_ISOLATE=1` for every tool.

---

## Per-tool matrix

Legend: **Process** = one MCP stdio child per server entry. **Session env** = chat id in subprocess environment. **Multi-chat** = parallel chats in same MCP process get distinct session ids without user action.

| Tool | Slug | Process model | Documented session env | Multi-chat without `session_id` | Workspace (separate concern) |
|------|------|---------------|------------------------|----------------------------------|------------------------------|
| Cursor | `cursor` | Shared per server | None | **No** | Project `.cursor/mcp.json` pin ([report §4.1](./mcp-workspace-all-hosts-solution-report-2026-08-26.md)) |
| Claude Code | `claude-code` | Shared; long-lived stdio | **`CLAUDE_CODE_SESSION_ID`** | **Per Claude session** at spawn; not per tool call inside session | **`CLAUDE_PROJECT_DIR`** ([MCP docs](https://code.claude.com/docs/en/mcp)) |
| Codex | `codex` | Shared | None | **No** | Project `.codex/config.toml` + `cwd` ([Codex MCP](https://developers.openai.com/codex/mcp)) |
| Copilot / VS Code | `copilot` | Shared per window | None (OTel `conversation.id` is telemetry only) | **No** | Project `.vscode/mcp.json` (special-4) |
| Kiro | `kiro` | Shared at startup | None | **No** | Project `.kiro/settings/mcp.json` |
| Windsurf | `windsurf` | Global shared | None | **No** | Global only; no project MCP |
| Cline | `cline` | Shared | None | **No** | Project `.cline/mcp.json` |
| Roo Code | `roo-code` | Shared (`McpHub`) | None | **No** | Project `.roo/mcp.json` |
| Continue | `continue` | Likely shared | None | **No** | Project `.continue/mcpServers/*.yaml` |
| Zed | `zed` | Shared | None | **No** | cwd ≈ project root ([#35354](https://github.com/zed-industries/zed/issues/35354)) |
| OpenCode | `opencode` | Unknown | None | **No** | Project `opencode.json` |
| Amp | `amp` | Unknown | None | **No** | Project `.amp/settings.json` |
| Pi | `pi` | **New process per Pi session** | None | **Between Pi sessions yes**; parallel chats in one Pi session **No** | Project `.mcp.json` |

---

## Per-tool notes

### Cursor

- **Evidence:** [cursor.com/docs/mcp](https://cursor.com/docs/mcp); live Mac session in [`cursor-mcp-workspace-resolution-research.md`](./cursor-mcp-workspace-resolution-research.md); forum reports of orphan MCP processes per server config.
- **Session:** No documented chat env. Cursor may inject `WORKSPACE_FOLDER_PATHS` (forum/staff mention) — workspace only, not session.
- **Multi-chat:** Multiple Composer tabs typically share one `scubiee-mcp` process → **shared Scubiee session** unless user sets `CTX_MCP_SESSION_ID` per chat (manual) or FastMCP `client_id` differs (unverified).

### Claude Code

- **Evidence:** [env-vars — `CLAUDE_CODE_SESSION_ID`](https://code.claude.com/docs/en/env-vars); MCP subprocess is long-lived ([`CLAUDE_CODE_CHILD_SESSION`](https://code.claude.com/docs/en/env-vars) not set for stdio MCP).
- **Caveats:**
  - MCP retains **spawn-time** id; `/clear` updates hooks/Bash but not necessarily MCP env ([#64412](https://github.com/anthropics/claude-code/issues/64412)).
  - Plugin-bundled MCP may lack session id ([#61752](https://github.com/anthropics/claude-code/issues/61752)).
  - `--continue` / resume without explicit id: edge cases documented in env-vars.
- **Multi-chat:** Separate `claude` invocations → separate MCP processes + different `CLAUDE_CODE_SESSION_ID`. **One** interactive session → one MCP server → **one** Scubiee session store.

### Codex

- **Evidence:** [developers.openai.com/codex/mcp](https://developers.openai.com/codex/mcp); Desktop cwd bugs ([#14449](https://github.com/openai/codex/issues/14449)).
- **Session:** No documented chat env. `CODEX_WORKSPACE_ROOT` is tool-call-time, not spawn.
- **Multi-chat:** **No** automatic per-chat isolation.

### VS Code / Copilot

- **Evidence:** [MCP configuration](https://code.visualstudio.com/docs/copilot/reference/mcp-configuration); user `mcp.json` does not expand `${workspaceFolder}` ([#245905](https://github.com/microsoft/vscode/issues/245905)).
- **Session:** Monitoring docs mention `gen_ai.conversation.id` in OTel — **not** passed to MCP child env.
- **Multi-chat:** Multiple Copilot chats in one window share MCP → **shared session**.

### Kiro, Cline, Roo Code

- **Evidence:** Repo special-4 docs; Kiro [#10486](https://github.com/kirodotdev/Kiro/issues/10486); Cline cwd [#9950](https://github.com/cline/cline/issues/9950); Roo [MCP docs](https://docs.roocode.dev/features/mcp/using-mcp-in-roo/).
- **Session:** None documented.
- **Multi-chat:** **No**.

### Windsurf

- **Evidence:** Global `~/.codeium/windsurf/mcp_config.json` only ([connect research](./connect-global-mcp-research.md)).
- **Session:** None.
- **Multi-chat:** **No**; also weak multi-repo without reconnect.

### Continue, OpenCode, Amp, Zed

- **Evidence:** Continue [MCP deep-dive](https://docs.continue.dev/customize/deep-dives/mcp); OpenCode [MCP servers](https://opencode.ai/docs/mcp-servers); Amp [manual](https://ampcode.com/manual/mcp.md); Zed [MCP](https://zed.dev/docs/ai/mcp).
- **Session:** None documented.
- **Multi-chat:** **No** (assumed shared stdio per server config).

### Pi

- **Evidence:** [pi-mcp-adapter README](https://github.com/nicobailon/pi-mcp-adapter) — MCP processes are **not** shared across Pi sessions.
- **Session:** Extension events `session_start` / `session_shutdown`; not MCP env.
- **Multi-chat:** New Pi session ⇒ new MCP process ⇒ natural `{pi}@proc-{pid}` isolation. Parallel chats **within** one Pi session: **shared**.

---

## What Scubiee should tell users

**Works today (verified):**

- Different repos + project MCP pins → correct workspace + per-process session dirs.
- Claude Code interactive session → stable store keyed by `CLAUDE_CODE_SESSION_ID` for that MCP spawn.
- Agent passes `session_id="…"` on map/focus/read/workspace/recall/expand → isolated store on **any** host.
- User adds to host MCP env: `CTX_MCP_SESSION_ID=my-chat-1` → isolated on **any** host.

**Does not work (without workarounds):**

- “Every Cursor chat gets its own recall/handles automatically” — **not proven**; likely **shared** one MCP process.
- Relying on `CONVERSATION_ID` / `CHAT_ID` env — **no host documents these** for MCP children.
- MCP protocol session headers — **removed** in 2026-07-28 spec.

**Recommended workarounds for parallel chats (Cursor/Copilot/etc.):**

1. Set **`CTX_MCP_SESSION_ID`** in project MCP env to a value the host can vary (if host supports per-chat env — **rare**).
2. Teach agent rules: pass **`session_id`** on first Scubiee tool call per chat (host would need to inject chat id into rules — product-specific).
3. Accept **process-level** isolation only until hosts expose chat ids or spawn MCP per chat.

---

## Reliability features (no live testing required)

Scubiee maximizes isolation without per-host QA:

1. **Verified env:** `CLAUDE_CODE_SESSION_ID` (official Claude Code).
2. **Dynamic env scan:** re-reads `CURSOR_*`, `VSCODE_*`, etc. session-like vars every tool call.
3. **Transport binding:** FastMCP `client_id` or connection id when inside a live MCP request.
4. **Process fallback:** `{host}@proc-{pid}` when isolate is on — safe for one-chat-per-process.
5. **Session echo:** every tool JSON includes `session_id`, `session_source`, and `session_hint`; agents pass `session_id` back for recall/expand continuity.
6. **Explicit override:** tool arg `session_id` or MCP env `CTX_MCP_SESSION_ID` — works on **any** host.
7. **Honest warnings:** `session_shared_risk: true` when on process fallback for Cursor/Copilot/etc.

**Agent protocol (works without host chat ids):** use `session_id="auth-refactor"` vs `session_id="billing-bug"` for parallel tasks in the same repo.

---

## Follow-up engineering

| Priority | Item |
|----------|------|
| P0 | ✅ Use official `CLAUDE_CODE_SESSION_ID` (not `CLAUDE_SESSION_ID`) |
| P1 | Live-test FastMCP `ctx.client_id` on Cursor + Copilot with two parallel chats |
| P2 | MCP `roots/list` client (workspace, not session) per Claude Code docs |
| P3 | Document in AGENTS.md / connect output: multi-chat limits per host |
| P4 | Optional: host-specific connect snippet suggesting `CTX_MCP_SESSION_ID=${env:CHAT_ID}` if a host adds one |

---

## Test coverage

- `tests/test_session_isolation.py` — store isolation, proc fallback, `CLAUDE_CODE_SESSION_ID`, host detection.
- Does **not** substitute for live dual-chat tests on each IDE.
