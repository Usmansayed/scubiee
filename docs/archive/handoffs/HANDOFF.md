# MacBook Handoff — Full Session Summary & Test Plan

**Date:** Sep 2026  
**Base on Mac today:** `0.3.10` (last pull — commit `3da2c4f`)  
**Branch state on Windows:** `0.3.11` **uncommitted** — all work below is local, not pushed  

---

## 0. First steps on MacBook

```bash
# Get the Windows changes (however you sync: USB, branch, patch, etc.)
cd /path/to/context-engine

# Install dev copy
uv tool install --force . --refresh
scubiee --version          # expect 0.3.11

# Confirm you're not on stale 0.3.10
python -c "import importlib.metadata; print(importlib.metadata.version('scubiee'))"
```

**Untracked/new files that must be present** (if missing, sync is incomplete):

```
packages/pipeline/cli_banner.py
packages/pipeline/upgrade_registry.py
packages/pipeline/upgrade_scenarios.py
packages/pipeline/upgrade_releases/          (v0_2_18, v0_3_7, v0_3_10, v0_3_11, _template)
packages/pipeline/mcp_response_lean.py
scripts/simulate_upgrade_matrix.py
tests/test_cli_terminal.py
tests/test_setup_progress.py
tests/test_upgrade_registry.py
tests/test_upgrade_scenarios.py
tests/test_upgrade_cli_integration.py
tests/test_upgrade_health.py
tests/test_daemon_process_sweep.py
tests/test_mcp_response_lean.py
docs/HANDOFF.md
```

**Modified files** (vs `3da2c4f`):

```
pyproject.toml              # 0.3.11, colorama on win32
npm/package.json            # 0.3.11
packages/pipeline/cli_ui.py
packages/pipeline/__main__.py
packages/pipeline/wipe.py
packages/pipeline/daemon.py
packages/pipeline/process_control.py
packages/pipeline/mcp_locate.py
packages/pipeline/upgrade_manifest.py
packages/pipeline/upgrade_platform.py
```

---

## 1. Complete summary of changes (since 0.3.10 pull)

### A. Declarative upgrade system (biggest backend change)

**Problem:** Upgrades were ad-hoc — often wipe-and-reinstall. Needed incremental, version-to-version migrations.

**Built:**

| Component | Path | What it does |
|-----------|------|--------------|
| Upgrade registry | `upgrade_registry.py` | Dispositions: `preserve`, `clear`, `migrate`, `update`, `reinstall` |
| Per-release defs | `upgrade_releases/v0_*.py` | Each version declares only what changed |
| Manifest | `upgrade_manifest.py` | `build_diff_plan()` composes release chain + runtime staleness guards |
| Scenario harness | `upgrade_scenarios.py` | Seeds 10 mock stale states for matrix testing |
| Matrix runner | `scripts/simulate_upgrade_matrix.py` | Live CLI: seed → `upgrade --check` → `upgrade` → verify |
| Platform | `upgrade_platform.py` | Health poll after daemon restart (12×5s) |

**Upgrade scenarios (10):**

1. `stale_mcp_pins` — old MCP pin format  
2. `stale_gate_rules` — outdated GATE rules  
3. `stale_instructions` — stale MCP instructions  
4. `stale_index_schema` — old index schema  
5. `embed_abi_mismatch` — embed ABI drift (needs `scubiee setup`)  
6. `missing_accel` — missing accel.json  
7. `stale_home_layout` — old `~/.scubiee` layout  
8. `legacy_mcp_command` — old MCP command string  
9. `combined_surface` — multiple stale surfaces at once  
10. `force_reindex` — forced reindex flag (needs accel)  

**Tests:** `tests/test_upgrade_*.py` — 45+ passed on Windows (2 skipped without setup).

---

### B. Daemon & process reliability

| Fix | File | Detail |
|-----|------|--------|
| Orphan daemon kill | `process_control.py`, `daemon.py` | Better sweep; don't leave zombies after upgrade/wipe |
| Upgrade disconnect bypass | `lifecycle_runtime.py` | Upgrade can bypass disconnect grace period |
| Process release before wipe | `process_control.py` | Unlock uv tool dir, kill rounds, final sweep |
| Daemon health after upgrade | `upgrade_platform.py` | Poll until healthy or timeout |

**Tests:** `tests/test_daemon_process_sweep.py`, wipe tests, upgrade health tests.

---

### C. CLI / UX overhaul (0.3.11)

| Feature | Files | Behavior |
|---------|-------|----------|
| Windows ANSI fix | `cli_ui.py`, `pyproject.toml` | `colorama` + UTF-8 console; no raw `[90m` escape garbage |
| SCUBIEE banner | `cli_banner.py` | Figlet **ANSI Shadow** block letters, framed with `──` rules |
| Single setup bar | `SetupProgress` in `cli_ui.py` | One `[████░░]` bar 0→100% for entire `scubiee setup`; checkmarks stack above |
| Single wipe bar | `WipeProgress` in `cli_ui.py`, `wipe.py` | One bar for full wipe; phase label + elapsed time; checkmarks above |
| Wipe confirm UX | `__main__.py` | Banner/progress only when wipe actually runs (not on confirm gate) |
| Duplicate runtime fix | `SetupProgress` | "Runtime installed" deduped |

**Visual expectation during setup:**

```
  ────────────────────────────────────────────────────
  [SCUBIEE ANSI Shadow banner]
  ────────────────────────────────────────────────────

  > scubiee setup
    local AI code context engine

  ✓ Hardware detected  mlx
  ✓ Runtime installed
  ✓ Model ready
  ✓ Calibrated

  [████████████░░░░░░░░░░░░] 72%  Downloading model…  45s
```

**Visual expectation during wipe:**

```
  [banner + frame]

  ✓ Prepared machine (stub MCP, kill, unlock)
  ✓ Repository data wiped

  [████████████░░░░░░░░░░░░] 58%  Removing model caches  72s
```

---

### D. MCP / lean response (opt-in)

| Item | Path | Note |
|------|------|------|
| Lean MCP echo | `mcp_response_lean.py` | Opt-in only: `CTX_MCP_LEAN_ECHO=1` |
| Tests | `tests/test_mcp_response_lean.py` | Unit tests |

---

### E. Version bump

- `pyproject.toml` → **0.3.11**
- `npm/package.json` → **0.3.11**
- `upgrade_releases/v0_3_11.py` — CLI UX release (no migration actions)

---

## 2. Windows test results (already run)

| Suite | Result | Notes |
|-------|--------|-------|
| CLI + setup + wipe + upgrade (focused) | **50 passed**, 3 skipped | Safe to trust |
| Full `pytest tests/` (~21 min) | **1155 passed**, **9 failed**, 27 skipped | Failures mostly drift/env |
| CLI combination runner | **24/24** (Aug 30, isolated CTX_HOME) | See matrix doc |
| Upgrade matrix (live, warm engine) | **8/8** non-destructive | Cold start can flake |
| Upgrade matrix dry-run | **10/10** | |

**9 full-suite failures (complete list):**

| Test | Likely cause |
|------|--------------|
| `test_coderank_fp16.py::test_register_coderank_points_fastembed_at_fp16` | Embed/model env |
| `test_coderank_fp16.py::test_register_coderank_upgrades_stale_fp32_registry` | Embed/model env |
| `test_cpu_only_laptop_path.py::test_real_light_cpu_calibrate_against_installed_fastembed` | CPU-only laptop path |
| `test_e2e_pipeline.py::test_full_pipeline_stores_in_faiss_collection` | FAISS/pipeline env |
| `test_embedder_progress.py::test_embed_many_suppresses_stderr_when_progress_set` | Progress/stderr behavior |
| `test_embedder_progress.py::test_embed_many_prints_without_progress` | Progress/stderr behavior |
| `test_mcp_hot_reload_reliability.py::test_upgrade_supervisor_includes_hot_reload_on_connect` | Upgrade message text drift |
| `test_mlx_backend.py::test_choose_backend_still_defaults_to_fastembed` | Platform (MLX on Mac vs Windows) |
| `test_scenario_backtracking.py::test_bound_unmanaged_pause_is_noop` | GATE format drift (`GATE p.` vs `GATE 0.`) |

---

## 3. Mac test plan — run in this order

Use a **real enrolled repo** (this repo is fine). For destructive tests, use isolated home:

```bash
export CTX_HOME="/tmp/scubiee-mac-test-$$"
mkdir -p "$CTX_HOME"
cd /path/to/context-engine
```

---

### Phase 1 — Install & version (2 min)

```bash
uv tool install --force . --refresh
scubiee --version                    # 0.3.11
scubiee --help                       # no crash, UTF-8 ok
```

| Check | Pass if |
|-------|---------|
| Version | Prints `0.3.11` |
| Help | No UnicodeEncodeError |

---

### Phase 2 — Unit / integration pytest (10 min)

```bash
# Fast — must all pass
python -m pytest \
  tests/test_cli_terminal.py \
  tests/test_setup_progress.py \
  tests/test_wipe.py \
  tests/test_upgrade_registry.py \
  tests/test_upgrade_scenarios.py \
  tests/test_upgrade_cli_integration.py \
  tests/test_upgrade_health.py \
  tests/test_daemon_process_sweep.py \
  -q --tb=short
```

**Pass:** 0 failures (skips OK for embed scenarios without setup).

---

### Phase 3 — Automated CLI combinations (5 min)

Same pattern as Windows `24/24`:

```bash
python scripts/run_cli_combination_tests.py \
  --json tests/_cli_combination_results_mac.json
```

**Pass:** exit 0, all scenarios match expectation.

**Covers:** stop→init BLOCK, stop→setup BLOCK, stop→setup --repair OK, stop→engine start BLOCK, engine stop→init OK, halt, wipe confirm gate, resume roundtrip.

Full matrix reference: `docs/scubiee-cli-combination-test-matrix.md`

---

### Phase 4 — Real CLI e2e script (15–30 min, destructive)

**This is the main Windows-style combination run.** Logs to `tests/_e2e_cmd_results.txt`.

```bash
bash tests/_e2e_run_cmds.sh
```

**What it runs (in order):**

| Block | IDs | What |
|-------|-----|------|
| Baseline | B1, B3, B5, B7, B8, B10 | version, doctor, status, setup --repair, init, status |
| Global stop | G1, G2, G3, G5, G12, G14, G17, G18 | stop, noop stop, init BLOCK, repair OK, resume |
| Halt | H1, H2 | halt + resume |
| Repo wipe | W1, W1b, W2 | wipe repo, re-init, stop |
| Full wipe | G16, G16b | confirm gate, full wipe keep-package |
| Post-wipe | P1, P2, P3 | setup, init, status |
| Read-only | R1–R4 | help, halt help, wipe help, list |
| Connect | C1, C2 | multi-tool dry-run connect |

**Pass checks in log:**

```bash
grep -E '^\[G3\].*BLOCK|^\[G16\].*CONFIRM|^\[G16b\]' tests/_e2e_cmd_results.txt
grep 'G16b-check' tests/_e2e_cmd_results.txt   # ~/.scubiee gone, scubiee still on PATH
```

**Mac-specific during G16b:**

- [ ] Works with **Cursor open** (MCP stubbed, no reboot)
- [ ] `~/.scubiee` deleted
- [ ] `scubiee` still on PATH after `--keep-package`
- [ ] Wipe shows **one progress bar** + checkmarks (visual)

---

### Phase 5 — Visual UX verification (10 min)

Run manually and **look at the terminal** (not just exit codes):

```bash
# 1. Setup — banner + single bar
scubiee setup
# ✓ ANSI Shadow SCUBIEE banner with frame lines
# ✓ ONE bar at bottom updating (not multiple bars)
# ✓ Checkmarks stack above bar
# ✓ No duplicate "Runtime installed"

# 2. Init
scubiee init .

# 3. Search — colors, no escape garbage
scubiee search "how is the repo structured?"

# 4. Connect
scubiee connect --cursor

# 5. Stop / resume roundtrip
scubiee stop -y
scubiee init .          # must BLOCK (tell user: resume)
scubiee resume

# 6. Wipe with progress
scubiee wipe . --confirm
# ✓ One bar, checkmarks above

# 7. Full wipe (keep package)
scubiee wipe --all --confirm --keep-package
# ✓ Bar goes 0→100% over ~1-2 min
# ✓ Elapsed seconds show on long steps
```

---

### Phase 6 — Upgrade matrix (20–40 min)

**Warm engine first** (avoids cold-start flake):

```bash
scubiee engine start
scubiee upgrade --check
```

**Dry-run all scenarios (safe, no upgrade applied):**

```bash
python scripts/simulate_upgrade_matrix.py --all --dry-run
```

**Pass:** 10/10 OK.

**Live non-destructive scenarios:**

```bash
python scripts/simulate_upgrade_matrix.py --all --pause-between 15
```

**Pass:** 8/8 minimum (embed_abi + force_reindex skip without full setup).

**List scenarios:**

```bash
python scripts/simulate_upgrade_matrix.py --list
```

**Single scenario debug:**

```bash
python scripts/simulate_upgrade_matrix.py --scenario stale_mcp_pins
```

---

### Phase 7 — CLI smoke (non-destructive, 5 min)

```bash
python tests/_cli_smoke_all.py
```

**Pass:** all cases exit as expected; results in stdout.

Covers: version, help, preflight, setup --status, resources, migrate, diagnose, connect/disconnect dry-run, wipe gate, engine status, doctor, init --fast, sync, search, certify, stop.

---

### Phase 8 — Engine / lifecycle combinations (10 min)

Manual — from matrix section 2–3:

```bash
# READY state (after setup + init + connect)
scubiee engine stop
scubiee init .              # must OK (not globally blocked)
scubiee engine ensure .

scubiee stop -y
scubiee engine start .      # must BLOCK — use resume
scubiee resume

scubiee halt
scubiee wipe --all          # must exit 2 (confirm gate, no banner-only wipe)
scubiee wipe --all --confirm --keep-package
```

Record in matrix doc table (section 10).

---

### Phase 9 — Mac-specific paths (10 min)

```bash
# MLX / CoreML (Apple Silicon)
scubiee setup               # confirm mlx or coreml profile in checkmarks
scubiee search "embedding"

# MCP hot reload after upgrade
scubiee upgrade --check
# If update available: scubiee upgrade

# Optional break-it suite (if time)
python tests/_mcp_break_it_suite.py
```

---

### Phase 10 — Full pytest (optional, ~20 min)

```bash
python -m pytest tests/ -q --tb=line 2>&1 | tee tests/_mac_full_pytest.txt
```

**Pass:** same or better than Windows (1154+ passed). Triage any new Mac-only failures.

---

## 4. Combination test pattern (how Windows did it)

Windows pre-prod used **layered combinations**, not single commands in isolation:

```
Layer 1: pytest unit/integration     → fast regression
Layer 2: run_cli_combination_tests   → stop/engine/wipe state machine
Layer 3: _e2e_run_cmds.sh            → real scubiee binary, destructive path
Layer 4: simulate_upgrade_matrix     → stale state × upgrade
Layer 5: _cli_smoke_all              → broad command surface
Layer 6: visual check                → banner, bars, colors
```

**Key combination bugs we caught on Windows:**

| Pattern | Expected |
|---------|----------|
| `stop` → `init` | BLOCK, message says `resume` |
| `stop` → `engine start` | BLOCK |
| `stop` → `setup` | BLOCK |
| `stop` → `setup --repair` | OK |
| `engine stop` → `init` | OK (not global stop) |
| `wipe --all` (no confirm) | exit 2, no delete |
| `wipe --all --confirm --keep-package` | clean audit, CLI stays on PATH |
| `halt` → `wipe --all --confirm` | one-shot, no manual taskkill |
| upgrade cold daemon | flake — warm with `engine start` |

**Mac must re-verify all of the above** — especially wipe with Cursor open and MLX setup path.

---

## 5. Production go / no-go

| Gate | Windows | Mac |
|------|---------|-----|
| Focused pytest (phase 2) | ✅ | ⬜ |
| CLI combinations (phase 3) | ✅ 24/24 | ⬜ |
| E2e script (phase 4) | ✅ | ⬜ |
| Visual UX (phase 5) | ✅ | ⬜ |
| Upgrade matrix (phase 6) | ✅ 8/8 live | ⬜ |
| MLX/CoreML setup | N/A | ⬜ |
| Full pytest (phase 10) | 1155/1164 | ⬜ |
| Git commit + tag 0.3.11 | ⬜ | ⬜ |
| PyPI publish | ⬜ | ⬜ |

**Ship when:** Mac phases 2–6 pass + MLX setup verified.

---

## 6. Quick reference commands

```bash
# Install
uv tool install --force . --refresh

# Fast regression
python -m pytest tests/test_cli_terminal.py tests/test_setup_progress.py \
  tests/test_wipe.py tests/test_upgrade_scenarios.py -q

# Combination tests
python scripts/run_cli_combination_tests.py --json /tmp/mac-cli.json

# Full e2e (destructive)
bash tests/_e2e_run_cmds.sh

# Upgrade matrix
scubiee engine start
python scripts/simulate_upgrade_matrix.py --all --pause-between 15

# Smoke
python tests/_cli_smoke_all.py
```

---

## 7. Related docs

| Doc | Purpose |
|-----|---------|
| `docs/scubiee-cli-combination-test-matrix.md` | Full G/E/W/C/L/X matrix tables |
| `docs/scubiee-cli-e2e-manual-test.md` | Manual e2e notes (if present) |
| `scripts/simulate_upgrade_matrix.py --help` | Upgrade scenario runner |
| `scripts/run_cli_combination_tests.py --help` | Automated combination runner |

---

## 8. After Mac testing

1. Fill in go/no-go table (section 5)  
2. Commit all changes with message e.g. `Release 0.3.11: upgrade registry, CLI UX, process reliability`  
3. Tag `v0.3.11`  
4. `uv build && uv publish` (when ready)  
5. On Windows laptop: `uv tool install --force scubiee --refresh` to get published build  
