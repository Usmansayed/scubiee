# Research: Cursor MCP workspace resolution (Mac + Windows)

**Date:** 2026-08-26  
**Trigger:** After `scubiee init` + `connect --cursor` on Apple Silicon, agent `status()` reported `repo=/Users/<home>`, `managed=false`, while the real index lived under the project. Windows journeys often looked fine.  
**Question:** Is this a Kiro-like “special-4” bug for Cursor, and what is the durable fix?  
**All hosts:** see [`mcp-workspace-mismatch-all-hosts-research.md`](./mcp-workspace-mismatch-all-hosts-research.md).

---

## 1. Problem statement

Scubiee MCP resolves the active repo via (`packages/pipeline/mcp_locate.py`):

1. IDE env candidates (`CURSOR_PROJECT_DIR`, `CURSOR_WORKSPACE`, `VSCODE_*`, …)
2. `CTX_PROJECT_ID` → registry
3. Walk up from `cwd` for `.context-engine/id.json`
4. Absolute `CTX_REPO` if enrolled / `.git`
5. Else **`Path.cwd()`**

On this Mac Cursor session, the MCP child process had:

| Signal | Observed |
|--------|----------|
| `CTX_REPO` | unset (global connect by design) |
| `CURSOR_PROJECT_DIR` / `CURSOR_WORKSPACE` | unset |
| `CURSOR_WORKSPACE_LABEL` | `hidden-context-engine-` (name only, not a path) |
| `VSCODE_CWD` | `/` (useless) |
| process `cwd` | **`$HOME`** |

So resolution fell through to home → `managed=false` / `stale_ctx_repo`, even though the project was indexed.

This is **not** a Mac path-layout bug (`~/.cursor/mcp.json` is the same shape on Windows). It is a **host spawn/cwd** bug.

---

## 2. How Scubiee classifies hosts today

| Host | Global MCP | Per-repo pin? | Why |
|------|------------|---------------|-----|
| **Kiro, Copilot, Cline, Roo** | yes | **yes** (`WORKSPACE_LOCAL_MCP_SLUGS`) | Host does not pass open folder to global MCP |
| **Cursor** | yes | **no** | Assumed IDE/cwd is enough |
| Claude / Codex / … | yes | no | Different spawn model |

Product docs (`docs/connect-global-mcp-research.md`) intentionally keep Cursor **global-only** and forbid absolute `CTX_REPO` in `~/.cursor/mcp.json` (one pin would poison every workspace). That part is still correct.

What was wrong: we treated “no absolute pin” as “no workspace hint at all.”

---

## 3. External evidence (Cursor + ecosystem)

### Official Cursor docs

- Global: `~/.cursor/mcp.json`
- Project: `.cursor/mcp.json` (merged; **project wins** on same server name)
- Config interpolation in `command` / `args` / `env` / `url` / `headers`:
  - `${workspaceFolder}` — open project root
  - `${userHome}`, `${env:NAME}`, `${workspaceFolderBasename}`, `${/}`
- MCP **Roots** capability is listed as supported (protocol-level alternative; Scubiee does not use it yet)

Source: [cursor.com/docs/mcp](https://cursor.com/docs/mcp)

### Industry pattern (same failure, known fix)

**codegraph** Cursor installer (public rationale):

> Cursor launches MCP subprocesses with a working directory that **isn’t** the workspace root and does **not** pass `rootUri` / `workspaceFolders` in initialize.  
> Fix: inject workspace into args — local install uses absolute path; **global install uses `${workspaceFolder}`** so one global config stays per-workspace.

**context-mode** (Cursor issue #521): MCP often sees `/` or wrong cwd; recommended override:

```json
"env": { "CURSOR_CWD": "${workspaceFolder}" }
```

### Contrast: VS Code / Copilot

VS Code **user** `mcp.json` does **not** expand `${workspaceFolder}` ([vscode#245905](https://github.com/microsoft/vscode/issues/245905)). That is why Copilot stays special-4 with **absolute** `CTX_REPO` in **project** `.vscode/mcp.json`.

**Cursor does expand `${workspaceFolder}`** (including when used from global config, per docs + ecosystem practice). Copying Kiro’s absolute-pin model onto Cursor is the wrong fix.

### Multi-root caveat

Cursor forum: project `.cursor/mcp.json` from **non-primary** folders in a multi-root window may not load. Global + `${workspaceFolder}` still follows the **primary** open folder — acceptable; document the multi-root limit.

---

## 4. Options evaluated

| Option | Multi-repo safe? | Matches Cursor? | Matches Scubiee connect UX? | Verdict |
|--------|------------------|-----------------|-----------------------------|---------|
| **A. Absolute `CTX_REPO` in `~/.cursor/mcp.json`** | **No** (pins one repo forever) | Works once | Accidental | **Reject** (what we did as emergency unblock) |
| **B. Add Cursor to special-4** (project `.cursor/mcp.json` + absolute `CTX_REPO`, connect per repo) | Yes | Works | Forces per-repo connect like Kiro | **Backup only** — worse UX than Cursor allows |
| **C. Global Cursor entry with `CTX_REPO=${workspaceFolder}`** | **Yes** (IDE expands per open folder) | Official interpolation | Keeps `connect --cursor` global-only | **Preferred** |
| **D. Project `.cursor/mcp.json` with `${workspaceFolder}` + drop conflicting user entry** | Yes | Works | Optional team-committed file | **Optional belt** |
| **E. MCP Roots client request** | Yes (if Cursor fills roots) | Protocol-correct | Needs runtime proof | **Follow-up** after C |
| **F. Rely on cwd / hope Windows spawn differs** | Fragile | Observed Mac fail | Status quo | **Reject** |

---

## 5. Recommended solution (perfect fit)

### Primary (ship this)

In **`scubiee connect --cursor`** (and setup’s Cursor MCP writer), write global `~/.cursor/mcp.json` **without** an absolute path, but **with**:

```json
"env": {
  "CTX_REPO": "${workspaceFolder}",
  "CURSOR_PROJECT_DIR": "${workspaceFolder}"
}
```

(Keep existing engine URL / surface / etc.)

Why this is the right design:

1. Cursor expands `${workspaceFolder}` at spawn → MCP sees the **open** repo on Mac and Windows.
2. Still one global connect — no Kiro-style “run connect inside every project.”
3. Avoids absolute global pin (the poison we already document in `__main__.py` / tests).
4. Aligns with how other serious Cursor MCP tools already work (codegraph / context-mode).
5. Distinct from Copilot/Kiro, which cannot rely on user-global `${workspaceFolder}`.

### Resolver hardening (small)

In `mcp_locate._ide_workspace_candidates` / `_default_repo`:

- Treat literal unexpanded `${workspaceFolder}` as missing (defensive).
- Prefer expanded `CTX_REPO` / `CURSOR_PROJECT_DIR` over home `cwd`.
- Do **not** treat `$HOME` as managed even if someone inits there by mistake (already partially gated).

### Optional secondary

When `connect --cursor` runs **inside** an enrolled repo, also write project `.cursor/mcp.json` with the same `${workspaceFolder}` (or absolute + `CTX_PROJECT_ID` for offline tooling). If project CE exists, keep using `_drop_user_context_engine_when_project_configured` only when the **user** entry is the broken absolute/empty form — do **not** drop a healthy user entry that already uses `${workspaceFolder}`.

### Explicitly do **not**

- Put Cursor into `WORKSPACE_LOCAL_MCP_SLUGS` with absolute pins as the default.
- Leave emergency absolute `CTX_REPO` in user mcp.json on developer machines (replace with `${workspaceFolder}`).

---

## 6. Why Windows looked fine

Not because Windows Cursor is a different product. Likely one of:

- MCP/agent spawn `cwd` was already the open repo on that machine/session
- Project `.cursor/mcp.json` existed from an older setup path
- Validation was CLI `status` from inside the repo, not agent MCP `status()`

Mac made the cwd=`$HOME` failure obvious. The fix above is **cross-platform**.

---

## 7. Validation plan (before calling it done)

1. Unit: `format_server_entry(cursor, pin_repo=False)` includes `CTX_REPO=${workspaceFolder}` and **no** absolute path.
2. Unit: assert global connect still fails the “CTX_REPO leaked absolute path” guard.
3. Mac manual: wipe absolute pin → `connect --cursor` → reload MCP → `status().repo` == open project, `managed=true`.
4. Switch to a second enrolled repo window → `status().repo` follows the new folder (proves interpolation, not sticky absolute).
5. Windows smoke: same as (3)–(4).
6. Regression: Kiro/Copilot still get **absolute** per-repo pins (unchanged).

---

## 8. Decision

| Item | Choice |
|------|--------|
| Root cause | Cursor MCP spawn cwd ≠ workspace; no workspace env unless we inject it |
| Same class as Kiro? | **Yes (spawn/cwd)** |
| Same fix as Kiro? | **No** — Cursor supports `${workspaceFolder}` in global config; Kiro/VS Code user MCP do not |
| Perfect solution | Global Cursor MCP: `CTX_REPO` / `CURSOR_PROJECT_DIR` = `${workspaceFolder}` |
| Emergency absolute pin | Temporary only; replace |

**Next engineering step:** implement option C in `rules_installer.format_server_entry` / Cursor connect path + tests; update `docs/connect-global-mcp-research.md` Cursor section; remove absolute pins from local Mac mcp.json during verify.
