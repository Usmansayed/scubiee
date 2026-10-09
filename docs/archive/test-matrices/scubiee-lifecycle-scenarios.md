# Scubiee lifecycle scenarios

How to recover from **stop**, **disconnect**, **wipe**, **connect**, and **resume** — and what agents should tell the user.

## Three layers (don't confuse them)

| Layer | What it is | Commands | Survives stop? |
|-------|------------|----------|----------------|
| **Machine** | `~/.scubiee` profile, models, registry | `setup`, `wipe --all` | Yes (until wipe) |
| **Global pause** | User stopped Scubiee everywhere | `stop` / `resume` | Enrollment kept |
| **Repo enrollment** | `<repo>/.scubiee/id.json` + index | `init`, `wipe` (repo) | Yes (until repo wipe) |
| **IDE wiring** | `.cursor/mcp.json`, GATE rules | `connect` / `disconnect` | Yes (until disconnect) |

**Rule of thumb:** `init` = enroll **this repo once**. `resume` = turn Scubiee back on after **`scubiee stop`**. `connect` = wire **IDE MCP** (no re-index).

---

## Decision tree (agent / user)

```
gate() or status().next_action
│
├─ globally_paused (gate = "p")
│   → scubiee resume
│   → Reload MCP in Cursor
│   ✗ Do NOT scubiee init
│
├─ machine_not_setup (~/.scubiee missing accel)
│   → scubiee setup
│   → then connect + init if needed
│
├─ repo_not_enrolled (no id.json)
│   → scubiee init .
│   → scubiee connect --cursor (if MCP missing)
│   ✗ Do NOT resume (nothing to resume)
│
├─ repo_paused (per-repo lifecycle, rare)
│   → scubiee activate .
│
├─ not_connected (enrolled but MCP not pinned)
│   → scubiee connect --cursor
│   → Reload MCP
│
├─ daemon_down
│   → scubiee engine start  OR  first map/focus call
│
└─ ready
    → map / focus / grep / glob
```

---

## Scenario matrix

### A. Global stop / resume (`scubiee stop` / `scubiee resume`)

| # | User did | State after | Agent | User |
|---|----------|-------------|-------|------|
| A1 | `scubiee stop` | **MCP:** `scubiee` key removed from `mcp.json` (other servers kept). **Rules:** Scubiee files deleted; other `.cursor/rules/*` kept. **Repo:** `<repo>/.scubiee/` removed. Registry + index in `~/.scubiee` kept. | Native tools only | `scubiee resume` |
| A2 | `scubiee resume` | MCP + rules + `id.json` restored, engine starts | Use Scubiee normally | Reload MCP in IDE |
| A3 | Action CLI while stopped (`init`, `connect`, `index`, …) | Blocked | — | Message: run `scubiee resume` |
| A4 | Read-only CLI while stopped (`doctor`, `gate`, `version`) | Allowed | — | — |
| A5 | Stale MCP session after stop | Tools return `paused:true` | Do not retry Scubiee | `resume` + reload MCP |

### B. Connect / disconnect

| # | User did | State after | Action |
|---|----------|-------------|--------|
| B1 | Fresh machine, never setup | No `~/.scubiee` | `setup` → `init .` → `connect --cursor` |
| B2 | Enrolled repo, never connected | id.json + index exist, no mcp.json | `connect --cursor` → reload MCP |
| B3 | `disconnect --cursor` | MCP removed; **enrollment kept** | `connect --cursor` only |
| B4 | Connect before init | MCP pinned but gate `0` | `init .` → reload MCP |
| B5 | Connect on unenrolled folder | MCP may pin; tools return not managed | `init .` in that repo |

### C. Wipe / reinstall

| # | User did | State after | Action |
|---|----------|-------------|--------|
| C1 | `wipe --all` | Everything gone | Quit Cursor → wipe → `setup` → `init .` → `connect` → restart Cursor |
| C2 | Delete `.scubiee` manually while Cursor open | Recreated by MCP (bug/ race) | Quit Cursor → wipe → reinstall |
| C3 | `wipe` repo only | id.json gone; registry row may linger | `init .` (may reuse or mint new project_id) |
| C4 | Wipe then `setup` only | Machine ready; repo not enrolled | `init .` + `connect` |
| C5 | Upgrade / reinstall package | Binary updated; state kept | `scubiee upgrade` or reinstall wheel; usually **no init** |

### D. IDE / MCP session

| # | Situation | Action |
|---|-----------|--------|
| D1 | New Cursor chat, same repo | Pass `project_id` + `session_id` from last tool response |
| D2 | gate = `0:r` | Call `gate()` or `status()` once; then init if still `0` |
| D3 | gate = `1:ce_…` but tools fail requires_initialize | `init .` or daemon not bound — `engine start` |
| D4 | Old `project_id` in AGENTS.md after re-init | Reload MCP; rules rewritten on `connect` / `init` |
| D5 | MCP running while globally paused | gate = `p`; agent uses native tools until `resume` |

### E. Per-repo pause (advanced)

| # | Command | vs global stop |
|---|---------|----------------|
| E1 | `scubiee pause .` | Pauses **indexing** for one repo; MCP may still work |
| E2 | `scubiee activate .` | Resumes that repo — **not** the same as `scubiee resume` |

---

## What stop touches (and what it does not)

| Target | On `scubiee stop` | On `scubiee resume` |
|--------|-------------------|---------------------|
| **All 13 tools** (Cursor, Claude Code, Codex, Kiro, Copilot, Cline, Roo, Continue, Zed, OpenCode, Amp, Pi, Devin) | Scubiee MCP + rules removed on **every** tool path (connected or not) | Re-added for tools in `connected_tools.json` |
| `.cursor/mcp.json` (and each tool's MCP file) | Remove **only** the `scubiee` entry | Re-add `scubiee` entry (merge) |
| Other MCP servers in same file | **Untouched** | **Untouched** |
| `.continue/mcpServers/scubiee.yaml` | **Deleted** (Scubiee-only file) | Re-written |
| `~/.continue/config.yaml` | Scubiee `# scubiee` block stripped; other servers kept | Re-merged |
| `.cursor/rules/scubiee.mdc` | **Deleted** | Re-written |
| Other rule files | **Untouched** | **Untouched** |
| `AGENTS.md` / `CLAUDE.md` / etc. | Marked Scubiee section stripped only | Re-written on connect |
| `<repo>/.scubiee/` | **Deleted** | `id.json` restored from registry |
| `~/.scubiee/` (index, registry) | **Kept** | Used to restore |

**OS paths:** VS Code / Zed / Devin use `%APPDATA%` on Windows, `~/Library/...` on macOS, `~/.config/...` on Linux — same surgical remove logic everywhere.

---

## Quick reference

See **[scubiee-action-matrix.md](scubiee-action-matrix.md)** for all command combinations (engine stop vs global stop, sequences, guardrails).

---

1. Call `gate()` or `status(detail=gate)` at chat start.
2. If `gate` is **`p`** or response says **STOPPED**:
   - **Do not call any Scubiee MCP tool** (map, focus, grep, glob, workspace, etc.).
   - Use **native Read/Grep/Glob** only until user resumes.
   - Tell user: **`scubiee resume`** (not init) + reload MCP.
3. If `gate` is **`0`** → check `status().lifecycle.next_action`:
   - `scubiee init .` — repo not enrolled
   - `scubiee setup` — machine not ready
   - `scubiee connect --cursor` — not wired to IDE
4. If `gate` is **`1:ce_…`** → use that `project_id` on all locate calls.
5. After user runs **`stop`** → only **`resume`** + MCP reload.
6. After user runs **`disconnect`** → only **`connect`** (+ reload).
7. After **`wipe`** → full chain: setup → init → connect → restart IDE.

`status()` includes `lifecycle`, `next_action`, and `lifecycle_hint` when not ready.

---

## Code hooks (0.3.5+)

| Component | Behavior |
|-----------|----------|
| `lifecycle_guidance.next_actions()` | Computes state + ordered steps |
| `status()` | Adds `lifecycle`, `next_action` when not ready |
| `gate()` / `_gate_line()` | Returns `p` when globally paused |
| `connect` | Auto-`resume()` if globally paused |
| `setup --repair` | Full `resume()` if paused (not flag-only) |
| MCP instructions | Lifecycle section in `SERVER_INSTRUCTIONS_PHASE` |

---

## Common mistakes

| Mistake | Why it's wrong | Correct |
|---------|----------------|---------|
| `init` after every stop | Stop doesn't unenroll | `resume` |
| `resume` after wipe | No enrollment left | `setup` + `init` |
| `connect` without setup | connect requires machine profile | `setup` first |
| Re-init to fix MCP | Index already exists | `connect` + reload |
| Manual delete `.scubiee` with Cursor open | MCP recreates state | Quit IDE, then wipe |
| Poll `status()` in a loop while warming | Wastes tokens | Retry locate once after 5s |

---

## Recommended user flows

**Temporary off:** `scubiee stop` → … → `scubiee resume` → reload MCP

**Switch IDE off/on:** Cursor disable MCP → enable OR `disconnect` → `connect`

**Clean slate:** Quit Cursor → `scubiee wipe --all --confirm` → `setup` → `init .` → `connect --cursor` → restart Cursor

**New laptop:** Install scubiee → `setup` → clone repo → `init .` → `connect --cursor`
