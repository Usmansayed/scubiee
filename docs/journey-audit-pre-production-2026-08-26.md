# Scubiee end-to-end journey audit (pre-production)

**Date:** 2026-08-26  
**Codebase / PyPI:** scubiee **0.2.81**  
**Scope:** Full product journeys (not only GPU/CPU detection).  
**Purpose:** Capture realistic user sequences, verified behavior, and production gaps to fix later.

---

## Friend install + share diagnose (non-CS)

```text
1. Open PowerShell (search “PowerShell” in the Start menu)

2. Paste this and press Enter (installs uv):

powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

3. Close that PowerShell window, open a NEW PowerShell window, then paste this and press Enter:

uv tool install --force scubiee==0.2.82 --index-url https://pypi.org/simple
scubiee setup --repair
scubiee diagnose --no-tests --desktop

4. When it finishes, look on your Desktop for a file named:
   scubiee-diagnose.json

5. Send me that file (WhatsApp / email / Discord — whatever).
```

Notes:
- The `file:///` link diagnose prints is **local only** — not a shareable web URL.
- Writing to Desktop makes the file easy to find and attach.
- For the CPU-only laptop check: in the JSON, `acceleration.profile` should be `"cpu"` (not `"dml"`).

Canonical machine sequence afterward (once diagnose looks good):

```text
cd path\to\repo
scubiee init .
scubiee connect --cursor          # or --kiro / --copilot / --cline / --roo-code
# Special-4 (Kiro, Copilot, Cline, Roo): run connect *inside each project*
```

---

## GPU / CPU / Mac detection (already shipped)

Shipped through **0.2.75–0.2.81**:
- Windows DirectML only for discrete AMD/NVIDIA (not Intel UHD / AMD APU “Radeon Graphics”)
- Probe + calibrate timeouts; CPU fallback; light CPU calibrate (batch 16)
- Apple Silicon never demoted to CPU-only (MLX)
- Multi-signal classifier: names + PCI VEN + **PCI device-ID** APU denylist / discrete allowlist
- Forced `scubiee setup --profile cpu` + `scubiee init` verified end-to-end
- Live machine (APU + RX 6500M) still correctly selects **dml**

**Still untested live:** auto-detect on a real CPU-only / iGPU-only Windows laptop (friend diagnose above).

Escape hatch if a rare discrete AMD chip is missed: `scubiee setup --profile dml`.

---

## Six end-to-end journeys (backtracked against code)

### Journey 1 — Fresh laptop (happy path)

1. Install uv → `uv tool install scubiee==0.2.81`
2. `scubiee setup --repair` → GPU/CPU profile, model, `accel.json`
3. Open IDE in a repo → `scubiee init .` → index + daemon
4. `scubiee connect --cursor` (or `--kiro` **inside** that repo for Kiro)
5. Agent calls `status()` → `managed: true` → map/grep work

**Verified:** Correct by design.  
**Important:** `init` does **not** write MCP/rules; `connect` does. Setup alone does not make a repo managed.

Key code: `cmd_setup` / `cmd_init` / `cmd_connect` in `packages/pipeline/__main__.py`.

---

### Journey 2 — Open IDE and use agent immediately (daemon cold / down)

1. Repo already managed; laptop wake
2. Agent `status()` before daemon is healthy
3. Agent tries `map` / search right away

**What happens today:**
- `status()`: `managed: true`, **`warming: true`**, and often **`ok: true`** (`ok = healthy OR managed`)
- Tools: JSON `ok: false`, `status: "warming"`, hint to retry after ready
- Cursor rule: wait 5s, retry once

**Risk:** Agents that only check `ok` think Scubiee is ready while the engine is dead.

Key code: `status_impl` / `_backend_error` in `packages/pipeline/mcp_locate.py`; `ensure_daemon` in `packages/pipeline/daemon.py`.

---

### Journey 3 — Mid-session `init` (was unmanaged, then user inits)

1. Agent first `status()` → `managed: false` → uses native tools
2. User runs `scubiee init .`
3. Agent should re-check

**What happens today:**
- **Cursor** (`packages/pipeline/templates/context-agent.mdc`): retry `status()` after init — **good**
- **Kiro / Cline / append hosts** (`packages/pipeline/templates/context-engine.md`): “one status, then **ignore forever**” — **bad**
- Tools still return `should_retry_status: true` when unmanaged, but old rules may never look again

**Production issue:** rule template split-brain.

---

### Journey 4 — Daemon crash / hung process

1. Engine dies or lock file stuck
2. Agent calls a tool

**What happens today:**
- Tool path: `ensure_daemon(..., force_if_hung=True)` → can restart (~up to ~2 min) — may look like a hang
- `status()`: **does not** force-restart hung daemon (by design)
- Recovery CLI: `scubiee engine ensure .`

**Mostly resilient**, but long silent restart is confusing.

---

### Journey 5 — Multi-project / wrong workspace (Kiro / Copilot / Cline / Roo)

1. User connects from home → global MCP only
2. Opens Project B; agent asks about Project B

**What happens today:**
- Without per-repo connect: pin missing → `managed: false` or wrong repo / `stale_ctx_repo` / `ambiguous_repos`
- Fix: `scubiee connect --kiro` (etc.) **inside each project**
- Paths:
  - Kiro: `.kiro/settings/mcp.json`
  - Copilot: `.vscode/mcp.json`, `.mcp.json`
  - Cline: `.cline/mcp.json`
  - Roo: `.roo/mcp.json`
- Cursor is better (setup can write project MCP; IDE env helps)

**Production issue:** Special-4 still easy to misconfigure for non-CS users.

---

### Journey 6 — Pause / stop / resume / wipe

1. `scubiee stop` → MCP disabled, rules hidden, daemon killed
2. Agent session continues
3. User tries to resume

**What happens today:**
- `status()` when paused: hint says **`scubiee wake`**
- Real command is **`scubiee resume`** — **`wake` does not exist** (verified in CLI help)
- Other MCP tools are **not** fully short-circuited on pause (only status is) → messy errors
- `scubiee wipe .` cleans repo; machine accel stays
- `scubiee wipe --all --confirm` is nuclear (home + models)

---

## MCP `status()` signal cheat sheet

| Field | Meaning |
|-------|---------|
| `managed` | Repo enrolled (id.json + registry managed) |
| `should_use_mcp` | Same as managed |
| `should_retry_status` | `true` when not managed |
| `warming` | Managed but daemon `/health` failed (not the same as index `warm_state`) |
| `stale_ctx_repo` | Dead / wiped `CTX_REPO` pin |
| `ambiguous_repos` / `candidates` | Multiple enrolled candidates visible |
| `paused` | Global pause early-return |

Tool errors merge managed signals via `_err()` so agents can recover after init.

---

## Exact commands users run

```text
# Fresh machine
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# new PowerShell window:
uv tool install --force scubiee==0.2.81 --index-url https://pypi.org/simple
scubiee setup --repair
scubiee init .
scubiee connect --cursor
# Inside each Kiro/Copilot/Cline/Roo project:
scubiee connect --kiro   # or --copilot / --cline / --roo-code

# Daemon
scubiee engine status
scubiee engine ensure .
scubiee engine stop
scubiee engine start

# Global pause / resume
scubiee stop
scubiee resume            # NOT "wake"

# Teardown
scubiee disconnect --cursor
scubiee wipe .
scubiee wipe --all --confirm

# Diagnose (shareable JSON)
scubiee diagnose --no-tests
scubiee diagnose --no-tests --output "$env:USERPROFILE\Desktop\scubiee-diagnose.json"
scubiee setup --status
scubiee doctor .
```

---

## Production issues to fix (priority)

| Priority | Issue | Why it matters |
|----------|--------|----------------|
| **P0** | Pause hint says `scubiee wake` but CLI is `resume` | Broken recovery instruction (`mcp_locate.py` ~2054) |
| **P0** | Kiro/Cline/`context-engine.md` still “ignore forever” after one unmanaged `status()` | Mid-session init never recovers |
| **P1** | `status.ok: true` while `warming: true` / daemon dead | Agents misread readiness |
| **P1** | Special-4 need per-repo `connect` with weak UX | Common “MCP doesn’t work” support load |
| **P2** | `upgrade` doesn’t refresh MCP/rules | Stale configs after version bump |
| **P2** | Docs still mention old init→MCP behavior in places | Confuses install sequence |
| **P2** | `warming` means “managed + unhealthy”, not “index still loading” | Naming confusion vs `warm_state` |
| **P3** | Hung daemon + tool path can block ~2 minutes | Looks like agent freeze |
| **P3** | Pause does not hard-block map/focus (only status short-circuits) | Messy errors while stopped |
| **P3** | Rare new AMD discrete PCI ID + weird OEM name → CPU | Escape: `--profile dml` |

GPU/CPU path is production-ready for known silicon. Remaining work is mostly **journey / UX / agent-rule resilience**.

---

## Suggested fix order (when we return)

1. Fix `scubiee wake` hint → `scubiee resume` (or add `wake` alias)
2. Unify all agent rule templates to Cursor’s retry-`status()` policy
3. Make `status.ok` false (or add `ready: false`) when `warming` / daemon unhealthy
4. Improve Special-4 connect UX / notices (and optionally soft-prompt after init)
5. On `upgrade`, refresh MCP entry + rules (or print loud “run connect again”)
6. Align docs (`getting-started`, mcp-workspace notes) with init ≠ MCP

---

## Key file map

| Area | Path |
|------|------|
| CLI entrypoints | `packages/pipeline/__main__.py` |
| MCP locate / status | `packages/pipeline/mcp_locate.py` |
| Daemon | `packages/pipeline/daemon.py` |
| Connect / rules | `packages/pipeline/rules_installer.py`, `tool_registry.py` |
| Cursor retry rules | `packages/pipeline/templates/context-agent.mdc` |
| Legacy one-shot rules | `packages/pipeline/templates/context-engine.md`, `context-engine.mdc` |
| Accel / GPU | `packages/pipeline/accel.py` |
| Diagnose JSON | `packages/pipeline/diagnose.py` |
| Upgrade | `packages/pipeline/upgrade.py` |
| Connect research | `docs/connect-global-mcp-research.md` |

---

## Audit sources

- Code exploration of setup/init/connect/status/daemon/pause/wipe (2026-08-26)
- Local verification: `scubiee --help` has `resume` not `wake`; engine status; GPU classifier audits; forced CPU setup+init smoke earlier in session
