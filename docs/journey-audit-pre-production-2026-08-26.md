# Scubiee end-to-end journey audit (pre-production)

**Date:** 2026-08-26  
**Codebase / PyPI:** scubiee **0.2.82**  
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
- After a broken / forced reinstall, always re-run `scubiee setup --repair` before `init` — Windows CPU extras (`fastembed` / `onnxruntime`) are not in the base wheel.

Canonical machine sequence afterward (once diagnose looks good):

```text
cd path\to\repo
scubiee setup --repair          # if reinstalled or diagnose shows missing fastembed/ort
scubiee init .
scubiee connect --cursor          # or --kiro / --copilot / --cline / --roo-code
# Special-4 (Kiro, Copilot, Cline, Roo): run connect *inside each project*
```

### Live result — friend laptop (UMAIR, 2026-08-26)

| Check | Result |
|--------|--------|
| Machine | Windows 11, Intel **i5-1235U** (iGPU-only), ~16 GB RAM |
| Scubiee | **0.2.82** (after Access-denied reinstall recovery) |
| Profile | **`cpu`** — not DML |
| Reason | *No discrete AMD/NVIDIA GPU… Intel iGPU / APU graphics ignored for DirectML* |
| First setup | Succeeded (~**2.6 t/s**, batch 16) |
| Diagnose after reinstall | `acceleration.profile: cpu`, but `libraries.fastembed` / `onnxruntime: null` |
| Daemon / managed | Expected empty — never ran `init` |

**Issues hit during the journey (product gaps):**
1. `$env:USERPROFILE` in `--output` failed when pasted into CMD → fixed in **0.2.82** (`--desktop` + env expansion).
2. `uv tool install --force` **Access denied** on `...\uv\tools\scubiee\Scripts` while `ContextEngineSupervisor` held files → half-broken install (`No module named 'pipeline'`).
3. Recovery needed: kill supervisor / reboot, remove uv tool dir, reinstall **0.2.82**.
4. Post-reinstall diagnose-only left **stale `accel.json`** (2.6 t/s) while packages were missing — `init` would fail until `setup --repair`.

**Not exercised on friend machine:** `init`, `connect`, agent MCP use.

---

## GPU / CPU / Mac detection (already shipped)

Shipped through **0.2.75–0.2.82**:
- Windows DirectML only for discrete AMD/NVIDIA (not Intel UHD / AMD APU “Radeon Graphics”)
- Probe + calibrate timeouts; CPU fallback; light CPU calibrate (batch 16)
- Apple Silicon never demoted to CPU-only (MLX)
- Multi-signal classifier: names + PCI VEN + **PCI device-ID** APU denylist / discrete allowlist
- Forced `scubiee setup --profile cpu` + `scubiee init` verified end-to-end (dev machine)
- Live machine (APU + RX 6500M) still correctly selects **dml**
- **Live CPU-only laptop:** friend i5-1235U correctly selected **cpu** (setup finished; no DML hang)

Escape hatch if a rare discrete AMD chip is missed: `scubiee setup --profile dml`.

---

## Six end-to-end journeys (backtracked against code)

### Journey 1 — Fresh laptop (happy path)

1. Install uv → `uv tool install scubiee==0.2.82`
2. `scubiee setup --repair` → GPU/CPU profile, model, `accel.json`
3. Open IDE in a repo → `scubiee init .` → index + daemon
4. `scubiee connect --cursor` (or `--kiro` **inside** that repo for Kiro)
5. Agent calls `status()` → `managed: true` → map/grep work

**Verified:** Correct by design. Friend laptop completed steps 1–2 (CPU path). Steps 3–5 not run on friend machine.  
**Important:** `init` does **not** write MCP/rules; `connect` does. Setup alone does not make a repo managed.

Key code: `cmd_setup` / `cmd_init` / `cmd_connect` in `packages/pipeline/__main__.py`.

---

### Journey 2 — Open IDE and use agent immediately (daemon cold / down)

1. Repo already managed; laptop wake
2. Agent `status()` before daemon is healthy
3. Agent tries `map` / search right away

**What happens today:**
- `status()`: `managed: true`, **`warming: true`** when daemon down → **`ok: false`** (fixed; was `ok = healthy OR managed`)
- Tools: JSON `ok: false`, `status: "warming"`, hint to retry after ready
- Cursor rule: wait 5s, retry once on tool warming — **not** poll `status()` in a loop

**Risk (mitigated):** Agents that only check `ok` without the `warming` branch fall back to native tools until daemon is up — acceptable vs false-ready.

Key code: `status_impl` / `_backend_error` in `packages/pipeline/mcp_locate.py`; `ensure_daemon` in `packages/pipeline/daemon.py`.

---

### Journey 3 — Mid-session `init` (was unmanaged, then user inits)

1. Agent first `status()` → `managed: false` → uses native tools
2. User runs `scubiee init .`
3. Agent should re-check

**What happens today (templates in repo, post-fix):**
- **Cursor** (`context-agent.mdc`): event-driven retry — **good**
- **Kiro / Cline / append hosts** (`context-engine.md`): same event-driven retry — **aligned**
- Explicit anti-poll: “Do not call it every turn” / “never in a loop”
- **Deploy note:** already-connected machines keep old “ignore forever” text until `scubiee connect` again

**Was production issue:** rule template split-brain — **fixed in templates**.

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
- `status()` when paused: hint says **`scubiee resume`** (fixed; was wrongly `wake`)
- `should_retry_status: false` while paused — agents must not poll; wait for user to resume
- Other MCP tools are **not** fully short-circuited on pause (only status is) → messy errors
- `scubiee wipe .` cleans repo; machine accel stays
- `scubiee wipe --all --confirm` is nuclear (home + models)

---

### Journey 7 — Windows upgrade while supervisor holds files (new, from friend)

1. User has working install + setup
2. `uv tool install --force scubiee==…` (or `scubiee upgrade`) while `ContextEngineSupervisor` / engine holds `Scripts\`
3. Access denied → half-broken tool env → `No module named 'pipeline'` / `scubiee` missing from PATH

**What happens today:**
- No automatic stop of supervisor before tool reinstall
- Recovery is manual (kill process / reboot / delete `%APPDATA%\uv\tools\scubiee` / reinstall)
- After recovery, **setup must run again** or diagnose shows missing `fastembed`/`onnxruntime` with stale calibrate numbers

**Production issue:** Windows upgrade / reinstall is fragile for non-CS users.

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
uv tool install --force scubiee==0.2.82 --index-url https://pypi.org/simple
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
scubiee diagnose --no-tests --desktop
scubiee diagnose --no-tests --output "$env:USERPROFILE\Desktop\scubiee-diagnose.json"
scubiee setup --status
scubiee doctor .

# Recover from Access denied / half-broken uv tool install (Windows)
scubiee engine stop
# if needed: Task Manager → end ContextEngineSupervisor
Remove-Item -Recurse -Force "$env:APPDATA\uv\tools\scubiee" -ErrorAction SilentlyContinue
uv tool install --force scubiee==0.2.82 --index-url https://pypi.org/simple --refresh
scubiee setup --repair
```

---

## Production issues to fix (priority)

| Priority | Issue | Why it matters |
|----------|--------|----------------|
| **P0** ~~done~~ | Pause hint said `scubiee wake` but CLI is `resume` | Fixed: hint → `scubiee resume`; `should_retry_status: false` while paused (no poll loop) |
| **P0** ~~done~~ | Kiro/Cline/`context-engine.md` “ignore forever” after one unmanaged `status()` | Fixed: event-driven retry only (never every turn); same policy as Cursor |
| **P1** ~~done~~ | `status.ok: true` while `warming: true` / daemon dead | Fixed: `ok` = daemon healthy only; warming hint anti-poll |
| **P1** ~~done~~ | Special-4 need per-repo `connect` with weak UX | Init + upgrade now print explicit per-repo connect notices; connect summary already warns when workspace MCP skipped |
| **P1** ~~done~~ | Windows upgrade blocked when supervisor holds uv tool files | `scubiee upgrade` now calls `stop_all_context_engine_processes` before package upgrade |
| **P2** ~~done~~ | `upgrade` doesn’t refresh MCP/rules | Loud `next_steps` to re-run `connect` (full auto-refresh still optional) |
| **P2** | Docs still mention old init→MCP behavior in places | Confuses install sequence |
| **P2** ~~done~~ | `warming` means “managed + unhealthy”, not “index still loading” | Naming confusion vs `warm_state` — left as-is (docs note) |
| **P2** ~~done~~ | Diagnose can show stale `accel.json` calibrate while packages missing after reinstall | Diagnose flags `stale_accel` + fails verdict when packages missing |
| **P2** | Windows path casefold in tests vs registry (`C:\` vs `c:\`) | Tests updated to use `_norm_path` (2026-08-26) |
| **P3** | Hung daemon + tool path can block ~2 minutes | Looks like agent freeze |
| **P3** | Pause does not hard-block map/focus (only status short-circuits) | Messy errors while stopped |
| **P3** | Rare new AMD discrete PCI ID + weird OEM name → CPU | Escape: `--profile dml` |

GPU/CPU path is **validated on a real CPU-only laptop**. Remaining work is mostly **journey / UX / agent-rule resilience** + **Windows upgrade locking**.

---

## Suggested fix order (when we return)

1. ~~Fix `scubiee wake` hint → `scubiee resume`~~ **done** (also: no `should_retry_status` while paused)
2. ~~Unify all agent rule templates to event-driven retry (anti-poll)~~ **done**
3. ~~Make `status.ok` false when `warming` / daemon unhealthy~~ **done**
4. ~~Stop/disable supervisor before `uv tool install --force` / `upgrade`~~ **done** (`stop_all_context_engine_processes` in `do_upgrade`)
5. ~~Improve Special-4 connect UX / notices~~ **done** (init + upgrade + connect notices)
6. ~~On `upgrade`, refresh MCP entry + rules (or print loud “run connect again”)~~ **done** (loud next_steps; auto-rewrite still optional)
7. ~~Diagnose: treat missing packages as stronger than stale calibrate numbers~~ **done**
8. Align docs (`getting-started`, mcp-workspace notes) with init ≠ MCP

**Note:** Existing installs keep old rules until the user runs `scubiee connect` again.

**Windows env note (dev machine, 2026-08-26):** a corrupted `numpy-*.dist-info` (METADATA missing) made full-suite `fastembed` imports fail after MCP collection (`importlib.metadata.version("numpy")` → TypeError). Fix: delete broken dist-info and `pip install --force-reinstall --no-deps numpy==<ver>`.

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
- Friend laptop (UMAIR): live CPU detect + setup; Access-denied upgrade recovery; diagnose JSON `scubiee-diagnose.json` (0.2.82)
