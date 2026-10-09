# MCP Legacy Design (pre–token-efficient gating)

This document records the **older Scubiee MCP integration model** (≈ v0.2.98 and earlier) for maintenance logs. It was replaced by connect-time tool gating + project-scoped rules on init.

---

## Summary of the old model

| Concern | Legacy behavior |
|--------|------------------|
| **`scubiee connect`** | Wrote **global MCP** + **global always-on rules** (`~/.cursor/rules/scubiee.mdc`, `~/.codex/AGENTS.md`, etc.) |
| **`scubiee init`** | Wrote `.scubiee/id.json` + index; **removed** per-repo rules via `cleanup_project_gate_rules()` |
| **MCP `instructions`** | Injected **~350 tokens/turn** of surface-specific guidance (`SERVER_INSTRUCTIONS_PHASE`, etc.) on every model turn |
| **MCP `tools/list`** | Always exposed full tool surface (7+ tools) even in **unmanaged** repos |
| **Agent startup** | Rules instructed agents to call `status()` once per chat; some templates banned native search when managed |
| **Gating** | Runtime `_is_repo_managed()` blocked locate tools; agents still **saw** full tool schemas |

---

## Why it was replaced

1. **Token waste in unmanaged repos** — Global rules (~187 tok/turn) + full tool schemas (~1,500–2,000 tok/turn) + verbose MCP instructions applied to **every workspace**, even without `scubiee init`.
2. **Duplicate signaling** — Global Cursor rules, MCP instructions, and per-tool `"g"` fields all repeated the same GATE state.
3. **Agent thrashing** — Conflicting rules (global “use Scubiee only” vs unmanaged GATE 0) caused unnecessary tool calls and native file reads.
4. **Mid-session `list_changed` unreliable** — Cursor and Claude Code do not reliably refresh tool lists mid-session; dynamic tool exposure was not a dependable primary fix.

Standing cost in unmanaged repos under the legacy model: **~2,200 tokens/turn** before any tool was invoked.

---

## Legacy rule templates

### Global connect rule (`templates/scubiee.mdc`, alwaysApply)

- Injected into `~/.cursor/rules/scubiee.mdc` on `scubiee connect`
- Told agents to read MCP `GATE …` prefix and match tool JSON `"g"`
- Applied to **all repos** opened in Cursor, managed or not

### Deprecated worktree / AGENTS.md pattern

Some installs also carried:

```markdown
On first message, call `status()` from the Scubiee MCP.
If status.managed is true: use Scubiee for all code discovery; do not use native search.
```

This lived in repo/worktree `AGENTS.md` files and caused agents to poll MCP on every new chat.

---

## Legacy MCP server instructions

`_server_instructions(surface)` in `packages/pipeline/mcp_locate.py` used to:

1. Prefix every turn with `GATE {line}. Formats: 0=unmanaged, 1:ce_=managed, p=paused.`
2. Append full surface body when managed, e.g. `SERVER_INSTRUCTIONS_PHASE` (~300 tokens) with map/focus/grep/glob workflow, anti-Grep mandates, session_id echo rules.

Verbose mode is retained behind `CTX_MCP_VERBOSE_INSTRUCTIONS=1` for debugging.

---

## Legacy gating layers

Even under the old model, multiple redundant layers existed:

| Layer | Mechanism |
|-------|-----------|
| Global rules | Cursor/Claude/Codex user-level instruction files |
| MCP instructions | Per-turn server instruction string |
| Tool descriptions | `"Scubiee-managed only (GATE 1)"` repeated on each locate tool |
| JSON `"g"` field | Compact gate on every tool response |
| Runtime block | `_is_repo_managed()` → `_err()` on locate tools |

Only the runtime block was strictly necessary; the rest inflated context.

---

## Legacy connect/init split (confusing)

- **`scubiee setup`** — Hardware/runtime (after fix: no MCP)
- **`scubiee connect`** — Global MCP + global rules (overreach)
- **`scubiee init`** — Project enrollment but **stripped** project rules

`write_project_gate_rules()` was deprecated and delegated to cleanup — the opposite of project-scoped gating.

---

## New model (reference)

See implementation in:

- `packages/pipeline/rules_installer.py` — connect MCP-only (global once); init writes project_id binding only
- `packages/pipeline/mcp_locate.py` — unmanaged: minimal instructions + gate-only tools; **managed: full SERVER_INSTRUCTIONS_* trajectory at MCP spawn**
- `tests/test_token_efficient_gating.py` — regression tests

**Architecture (correct split):**

| Step | Scope | What it does |
|------|-------|--------------|
| `scubiee setup` | Machine once | Hardware/runtime |
| `scubiee connect cursor` | **Global once** | Registers MCP in `~/.cursor/mcp.json` — user never connects per folder |
| `scubiee init .` | Per enrolled repo | `.scubiee/id.json` + index + tiny GATE/project_id rule (~65 tok) |
| MCP spawn | Per workspace open | If managed → full locate trajectory in MCP instructions; if not → gate-only |

Locate trajectory (map→focus→grep flow) is **not** duplicated in init rules or global Cursor rules. It is injected via MCP server instructions when the open workspace is managed.

**Target standing cost:**

| State | Legacy | New |
|-------|--------|-----|
| Unmanaged | ~2,200 tok/turn | ~250 tok/turn (gate tool only) |
| Managed | ~2,500 tok/turn | ~1,750 tok/turn (trajectory in MCP instructions at spawn) |

**Mid-session `scubiee init`:** Locate tools appear after MCP reconnect or new chat (not via unreliable `list_changed` on Cursor/Claude Code).

---

## Changelog

| Date | Change |
|------|--------|
| 2026-08-29 | Documented legacy design; shipped token-efficient gating architecture |
