# Kiro ↔ Scubiee MCP reliability (Phase A)

**Date:** 2026-09-05  
**Status:** MCP layer **PASS** · Kiro agent chat **blocked on login**

## Verified working

| Check | Result |
|-------|--------|
| Engine | `index_usable=true`, `warm=ready`, v0.3.15 |
| `scubiee connect --kiro` | project `.kiro/settings/mcp.json` + steering |
| User MCP | `~/.kiro/settings/mcp.json` **without** `CTX_REPO` (correct) |
| Project MCP | `CTX_REPO` pinned + `CTX_TRACE_ENGINE=composite_v1` |
| `kiro-cli mcp` | `scubiee` on `kiro_default` |
| Stdio probe (Kiro env) | **all green** — see JSON below |

### Probe (`scripts/kiro_mcp_reliability_probe.py`)

Launches the **same bridge + env Kiro uses**, then:

- `initialize` → scubiee
- `tools/list` → 11 tools including gate/map/pack/expand
- `gate` → `1:ce_d9cb766c3820091ed9ffbc64ef33063c` (`CTX_MCP_CLIENT=kiro`)
- `map` → cards (top: `context_trace.py`)
- `pack_context(lean)` → **`engine=composite_v1`**, `next_actions` present
- `expand_context(callees, with_bodies)` → ok

Report: `docs/superpowers/plans/2026-09-05-kiro-mcp-reliability.json`

Re-run anytime:

```powershell
cd C:\Users\usman\Downloads\context-engine
scubiee engine start
& "$env:APPDATA\uv\tools\scubiee\Scripts\python.exe" scripts\kiro_mcp_reliability_probe.py
```

## Blocker for A/B agent tests

```
Not logged in. Set KIRO_API_KEY or run `kiro-cli login` first.
```

Until you log in, headless `kiro-cli chat --require-mcp-startup` cannot run. MCP itself is already proven without the LLM.

### What you should do

```powershell
kiro-cli login --license free
# or: set KIRO_API_KEY=...
```

Then (optional smoke):

```powershell
cd C:\Users\usman\Downloads\context-engine
kiro-cli chat --no-interactive --require-mcp-startup --trust-all-tools "Call scubiee gate, reply with only the gate line."
```

## Do not start A/B harness until

1. `kiro-cli login` (or API key) succeeds  
2. Optional: the chat smoke above returns `1:ce_…`  
3. Probe still exits 0

Then we build the with/without-MCP task simulation.
