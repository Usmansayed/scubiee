# Scubiee action combination matrix

Guardrails for every reasonable user command sequence. Two **different** stop commands — never mix them up.

| Command | Scope | MCP / rules | Engine | Recovery |
|---------|-------|-------------|--------|----------|
| **`scubiee stop`** | Global | **Removed** | Stopped | `scubiee resume` |
| **`scubiee engine stop`** | Daemon only | **Kept** | Stopped | `scubiee engine start` or first MCP call |

---

## State axes

| Axis | Values |
|------|--------|
| **Global** | `active` · `stopped` (`scubiee stop`) |
| **Engine** | `running` · `down` |
| **Enrollment** | `enrolled` (registry + was inited) · `not` |
| **MCP wired** | `connected` · `not` |

Common compound states:

| State | Global | Engine | MCP on disk | Agent should |
|-------|--------|--------|-------------|--------------|
| **READY** | active | running | yes | Use Scubiee MCP |
| **ENGINE_DOWN** | active | down | yes | `engine start` or map/focus (auto-start) |
| **GLOBAL_STOPPED** | stopped | down | **no** | Native tools only → tell user `resume` |
| **NEED_INIT** | active | * | maybe | `init .` then `connect` |
| **NEED_CONNECT** | active | * | no | `connect --cursor` |

---

## Command guardrails (what happens when you run X in state Y)

### Global stop active (`scubiee stop` was run)

| Command | Allowed? | Outcome |
|---------|----------|---------|
| `scubiee resume` | ✅ | Restores MCP, rules, `id.json`, engine |
| `scubiee stop` | ✅ | No-op (already stopped) |
| `scubiee engine status` | ✅ | Shows `globally_paused: true` + hint |
| `scubiee engine stop` | ✅ noop | Hint: already globally stopped |
| `scubiee engine start` | ❌ | Blocked — use **`resume`**, not engine start |
| `scubiee engine ensure` | ❌ | Same |
| `scubiee init` / `connect` / `index` / `search` | ❌ | Blocked — run **`resume`** first |
| `scubiee setup` | ❌ | Blocked |
| `scubiee wipe` | ✅ | Escape hatch — full cleanup still works |
| `scubiee doctor` / `gate` / `preflight` | ✅ | Read-only diagnostics |
| `--version` / `--help` | ✅ | Always |
| MCP tools (stale session) | ❌ | `paused: true` — do not retry |

### Engine down only (`scubiee engine stop`, global still active)

| Command | Outcome |
|---------|---------|
| `scubiee engine start` | Starts daemon; MCP/rules unchanged |
| `scubiee stop` | Escalates to **global stop** (removes MCP too) |
| `scubiee init` / `connect` | Works normally |
| MCP `map` / `focus` | Auto-starts engine via `ensure_daemon` |
| Agent | Use Scubiee MCP (may warm 5s on first call) |

### Ready (normal)

| Command | Outcome |
|---------|---------|
| `scubiee stop` | Global stop — tears down everything Scubiee on disk |
| `scubiee engine stop` | Daemon only — MCP still in Cursor |
| `scubiee disconnect` | Removes MCP/rules; enrollment kept |
| `scubiee connect` | Wires MCP/rules for enrolled repos |

---

## Common sequences (user journeys)

### A. Engine stop → global stop

```
engine stop  →  engine down, MCP still in IDE
stop         →  MCP/rules/.scubiee removed, CLI blocked
resume       →  full restore
```

**Guardrail:** Second step is intentional escalation. Don't run `engine start` between them unless you changed your mind about global stop.

### B. Global stop → engine start (wrong recovery)

```
stop           →  global stopped
engine start   →  ❌ BLOCKED — message says use resume
resume         →  ✅ correct path
```

**Guardrail:** CLI + `guard_engine_action()` both block this.

### C. Engine stop → engine start (correct)

```
engine stop   →  daemon down
engine start  →  daemon up, MCP unchanged
```

**Guardrail:** Allowed. Not related to `scubiee stop`.

### D. Global stop → init (wrong)

```
stop   →  global stopped, id.json removed from repo
init   →  ❌ BLOCKED
resume →  restores id.json from registry (no re-index if store kept)
```

**Guardrail:** Don't init after stop — **resume** first.

### E. Global stop → connect (auto-resume)

```
stop     →  MCP removed, globally paused
connect  →  auto-resumes, then wires selected tools
resume   →  reconnects saved tools from pause_state (same end state)
```

**Guardrail:** `connect` and `setup --repair` call `resume()` first when globally stopped.

### F. Disconnect → stop

```
disconnect  →  MCP/rules gone, enrollment kept
stop        →  also removes repo .scubiee, blocks CLI
resume      →  restores MCP for previously connected tools
```

### G. Stop → wipe

```
stop              →  global stopped
wipe --all        →  ✅ allowed (nuclear escape)
setup → init → connect  →  fresh install path
```

### H. Engine stop → use Cursor MCP

```
engine stop  →  daemon down
map/focus    →  ensure_daemon auto-starts OR retry once after 5s
```

**Agent:** Scubiee MCP still valid; not a global stop.

### I. Stop while Cursor still has stale MCP process

```
stop         →  configs removed from disk
Cursor MCP   →  may still respond until reload
tool call    →  paused: true / gate p
```

**User:** Reload MCP in Cursor after `resume`.

---

## Agent decision table

| Signal | Meaning | Tell user |
|--------|---------|-----------|
| `gate = p` or `paused: true` | Global stop | `scubiee resume` — **not** init, **not** engine start |
| `gate = 1:ce_…`, tools fail transient | Engine down only | `scubiee engine start` or retry locate once |
| `gate = 0` | Not enrolled | `scubiee init .` (if global **not** stopped) |
| No Scubiee MCP in Cursor after stop | Expected | Native tools until user resumes |

---

## Implementation map

| Layer | File | Role |
|-------|------|------|
| CLI block | `lifecycle_guard.paused_blocks_command` | Blocks action cmds when globally stopped |
| Engine block | `lifecycle_guard.guard_engine_action` | Prevents engine start during global stop |
| Stop/resume | `pause_resume.pause` / `resume` | Tear down / restore all tools |
| MCP surgical | `rules_installer.remove_mcp_config` | Remove only `scubiee` key |
| Agent hints | `lifecycle_guidance.next_actions` | resume vs init vs engine start |
| MCP runtime | `mcp_locate._paused_locate_err` | Hard block locate tools when stopped |

---

## Quick reference card

```
Problem                          Fix
─────────────────────────────────────────────────────
Ran scubiee stop                 scubiee resume (+ reload MCP)
Ran engine stop only             scubiee engine start
Stopped then tried init/connect  scubiee resume first
Wiped everything                 setup → init → connect
Agent confused after stop        Native tools; user runs resume
```
