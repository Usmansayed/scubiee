# User Journey Scenarios (backtracking matrix)

Regression tests: `tests/test_user_journey_scenarios.py`  
Global hosts: `tests/test_global_mcp_hosts.py`

Usual user paths and expected behavior at each step. Use when changing connect/init/MCP gating.

## Commands (scope)

| Command | Scope | Purpose |
|---------|-------|---------|
| `scubiee setup` | Machine once | Hardware, models, accel profile |
| `scubiee connect cursor` | **Global once** | Register MCP in `~/.cursor/mcp.json` |
| `scubiee init .` | Per repo | Enroll, index, write GATE **ban** project rule |
| MCP spawn | Per workspace open | Resolve managed/unmanaged → tools + instructions |

**Split (no duplication):**
- **Project rule** (init) = tool bans + `project_id`
- **MCP instructions** (spawn) = locate trajectory OR native-only note (unmanaged)

See [global-mcp-hosts-research.md](./global-mcp-hosts-research.md) for multi-host connect.

---

## Scenario matrix (S1–S20)

| ID | User path | Expected behavior |
|----|-----------|-------------------|
| **S1** | Setup only, never connect | No `~/.cursor/mcp.json`, no global rules |
| **S2** | `connect cursor` once | Global MCP; **no** global rules |
| **S3** | Open repo without `init` | `[gate]` only; MCP says **use native** |
| **S4** | `init .` in current repo | Full tools; MCP trajectory (no bans in MCP) |
| **S5** | Init A, open B | B unmanaged — no cross-repo bleed |
| **S6** | After `init` | Repo `.cursor/rules/scubiee.mdc` with **BAN native** |
| **S7** | Rules on unenrolled repo | Skipped |
| **S8** | `scubiee pause` | Gate line `p` |
| **S9** | Wipe / cleanup | Project rules removed |
| **S10** | `disconnect cursor` | Global MCP removed; project rules remain |
| **S11** | Stale MCP on unmanaged | `map` not in tool list |
| **S12** | `CTX_MCP_BARE_INSTRUCTIONS=1` | Stripped MCP instructions (trials) |
| **S13** | Rules vs instructions | Bans in rule only; trajectory in MCP only |
| **S14** | Sidebar repo B, pin on A | IDE env beats stale `CTX_REPO` |
| **S15** | Init | `AGENTS.md` gets ban section (Codex/etc) |
| **S16** | Paused + managed | Project rule `GATE p` |
| **S17** | Re-run init | Gate rule refreshed on disk |
| **S18** | Global connect (9 hosts) | No workspace MCP pins, no `CTX_REPO` in global |
| **S19** | Literal `${workspaceFolder}` | Ignored; enrolled cwd wins |
| **S20** | Mid-session init | Disk enrolled; **MCP reload** → full tools |

---

## Backtracking trees

Formal enumerator: `packages/pipeline/scenario_tree.py`  
Executable tests: `tests/test_scenario_backtracking.py`

### Decision tree (DFS + branch-and-bound)

```
                    [start]
                       │
           ┌───────────┴───────────┐
      connect=NEVER          connect=GLOBAL
           │                       │
      leaf: NO_MCP          workspace?
      (prune all            ┌──────┼──────┐
       extensions)      UNMANAGED MANAGED WRONG_REPO
                           │       │         │
                    init_timing  (implicit   (implicit
                    NONE |       init)       init on A)
                    MID_SESSION  │           │
                           │     │           │
                    pause OFF|ON (prune      │
                           │     MID on       │
                    mcp FIRST|   managed)     │
                         RESPAWN │           │
                           │     │           │
                    ┌──────┴─────┴───────────┴──────┐
                    │  branch-and-bound prune rules   │
                    │  • NEVER + workspace → cut      │
                    │  • MANAGED + MID_SESSION → cut  │
                    │  • WRONG + RESPAWN → cut        │
                    │  • UNMANAGED + MID + FIRST → cut│
                    │  • UNMANAGED + pause ON → cut   │
                    └─────────────────────────────────┘
                                    │
                           outcome leaves
```

### Outcome signatures (leaves)

| Outcome | Tools | Instructions | Project rule |
|---------|-------|--------------|--------------|
| `NO_MCP` | — | — | — |
| `GATE_ONLY_NATIVE` | `[gate]` | native-only | none |
| `FULL_MANAGED` | all 7 | trajectory | BAN native |
| `WRONG_REPO_GATE` | `[gate]` | native-only | none on B |
| `PAUSED_RULE` | all 7 | trajectory | `GATE p` |
| `MID_INIT_RELOAD` | all 7 (after respawn) | trajectory | BAN native |

Run backtracking tests:

```bash
uv run pytest tests/test_scenario_backtracking.py -v
```

### Happy path (managed)
```
setup → connect (once) → open repo → init .
  → Project rule: BAN native locate, USE Scubiee
  → MCP: trajectory only (map→focus→grep)
  → Agent: Scubiee locate → native Edit/Shell
```

### Safe default (unmanaged)
```
setup → connect (once) → open random clone (no init)
  → MCP: [gate] + "use native only"
  → No project rule (not enrolled)
  → Agent: native Grep/Glob/Read
```

### Wrong-repo protection (S5, S14)
```
init repo-A → open repo-B in sidebar
  → IDE env (CURSOR_PROJECT_DIR) → B
  → Stale CTX_REPO pin to A ignored
  → Unmanaged: gate-only, no index bleed
```

### Rules/instructions split (S13)
```
init .
  → .cursor/rules/scubiee.mdc: "BAN native … USE Scubiee"
  → MCP instructions: "tool bans in project rule" + map/focus/grep how-to
  → Zero duplicate ban text in MCP
```

### Mid-session init (S20)
```
connect → open unmanaged → chat started (gate-only MCP process)
  → terminal: scubiee init .
  → Disk: id.json + gate rule immediately
  → Same MCP process: still gate-only until reload
  → Fix: toggle MCP / new chat → full tools
```

### Special-4 hosts (Kiro, Copilot, Cline, Roo)
```
connect global → still need project MCP OR connect from inside repo
See global-mcp-hosts-research.md — not covered by S18
```

---

## Running tests

```bash
uv run pytest tests/test_user_journey_scenarios.py -v
uv run pytest tests/test_global_mcp_hosts.py -v
uv run pytest tests/test_token_efficient_gating.py -v
uv run pytest tests/test_mcp_repo_resolution.py -v
```

---

## Changelog

| Date | Notes |
|------|-------|
| 2026-08-29 | S1–S12; v0.3.0 gating |
| 2026-08-29 | S13–S20; rules/instructions split, multi-host, resilience |
