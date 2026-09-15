# Scubiee Pre-Production Test Matrix Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or subagent-driven-development) to execute this plan phase-by-phase. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Define and run a complete pre-production test battery so Scubiee ships only when unit, CLI, MCP, availability, and OS-specific gates are green.

**Architecture:** Layered gates — (0) single-install env hygiene → (1) curated unit/integration → (2) full pytest → (3) MCP ship + host-sim availability → (4) CLI journey → (5) live Cursor/IDE → (6) Windows-specific → (7) macOS-specific. Fail-fast on availability; quality bakeoffs are recorded but do not block soft-path ship unless scores regress hard.

**Tech Stack:** `uv tool` Scubiee install, pytest, `scripts/run_scubiee_e2e_suite.py`, `scripts/run_mcp_ship_preprod.py`, `scripts/mcp_host_sim.py`, `scripts/warm_contract_acceptance.py`, `scripts/run_cli_combination_tests.py`, Windows JobObject CPU cap, macOS MLX/CoreML.

**Spec:** Lessons from `docs/superpowers/plans/_preprod_battery_0_3_89/REPORT.md`, `docs/macos-deferred-verification.md`, `docs/mac-cursor-session-handoff-2026-08-26.md`, `docs/superpowers/plans/2026-09-14-scubiee-e2e-test-report.md`.

## Global Constraints

- Target version under test must match `pyproject.toml` (today **0.3.89+**).
- **One** Scubiee install owns `~/.scubiee` — prefer `uv tool` only; no Miniconda + uv dual fight.
- Run pytest with the **same Python** that has FastEmbed/ORT (uv-tool `python.exe`), not a bare `.venv` missing accel deps.
- Soft map/pack SLA after warm: **≤1s**; expand first hydrate may be ≤1s once; CPU peaks **≤20%** (`CTX_ENGINE_CPU_CAP_PCT=20`).
- Full-warm RAM may be ~0.9–1.2GB while Cursor connected (availability over aggressive demote).
- Do not declare production until **Gate A–D** pass on Windows; **Gate M** required before claiming Mac/MLX production.

---

## Files / scripts this plan uses (no new harness required)

| Artifact | Role |
|----------|------|
| `scripts/run_scubiee_e2e_suite.py` | Curated cross-layer pytest |
| `scripts/run_mcp_ship_preprod.py` | MCP ship L1–L5 |
| `scripts/scubiee_mcp_ship_check.py` | Live gate→map→pack→expand→status |
| `scripts/mcp_host_sim.py` | Cold attach / map / pack / expand SLA |
| `scripts/warm_contract_acceptance.py` | Attach warm within deadline |
| `scripts/run_cli_combination_tests.py` | CLI stop/resume/connect matrix |
| `tests/mac_production_test.py` | Live Mac production suite |
| `tests/windows_production_test.py` | Live Windows production suite |
| `docs/superpowers/plans/_preprod_<ver>/` | Store logs + REPORT.md per run |

---

## Production gates (must all be green)

| Gate | Name | Pass criteria |
|------|------|----------------|
| **A** | Env hygiene | Single install; `scubiee --version` = expected; doctor binaries_match; engine soft-ready with chunks > 0 |
| **B** | Curated e2e | `run_scubiee_e2e_suite.py` exit 0 |
| **C** | MCP ship + availability | ship pytest L1–L3 pass; `scubiee_mcp_ship_check.py` ok; host-sim Lane A `--live --skip-idle` ok; warm_contract ok |
| **D** | CLI journey | `run_cli_combination_tests.py --quick` 36/36 (or full if time) |
| **E** | Full pytest (advisory → hard) | `pytest tests -m "not slow"` — target 0 fail on uv-tool Python after stale-test fixes; quality bakeoffs may be marked `slow`/`xfail` with ticket |
| **W** | Windows-specific | DML/CPU profile + JobObject 20% + pythonw MCP + host-sim on Windows |
| **M** | macOS-specific | MLX profile + Mac pytest modules + host-sim/MCP on Darwin |

---

### Task 0: Preflight env (both OS)

**Goal:** Eliminate dual-install and wrong-interpreter false fails.

- [ ] Stop all Scubiee processes: `scubiee stop` (and Task Manager / Activity Monitor if stuck).
- [ ] Confirm **one** install: `uv tool list` shows `scubiee`; uninstall stray pip/conda copies.
- [ ] Install under test: `uv tool install --force . --refresh` (or pinned PyPI version).
- [ ] Record: `scubiee --version`, `which scubiee` / `Get-Command scubiee`, Python path used for pytest.
- [ ] Set always: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `PYTHONPATH=packages` only when needed; prefer installed package.
- [ ] `scubiee engine ensure` then health: `soft_search_ready=true`, `chunks>0`.
- [ ] Create run folder: `docs/superpowers/plans/_preprod_<version>_<os>/`.

**Pass:** Gate A green.

---

### Task 1: Curated e2e suite

```bash
# Use uv-tool python (Windows example)
UVPY="$HOME/AppData/Roaming/uv/tools/scubiee/Scripts/python.exe"   # Win
# UVPY="$(uv tool dir)/scubiee/bin/python"                        # macOS/Linux shape may vary

$UVPY scripts/run_scubiee_e2e_suite.py --out docs/superpowers/plans/_preprod_<ver>/e2e-suite-results.json
```

Covers: lifecycle, bridge, memory governor/budget, sync/freshness, locate ladder, attach warm, reliability master plan.

- [ ] Run curated suite.
- [ ] If fail: fix **product or update stale mocks** (known 0.3.89: attach singleflight, publish `drop_engine`, attach-warm `ensure` hook) — do not skip.
- [ ] Re-run until exit 0.

**Pass:** Gate B green.

---

### Task 2: Focused regression packs (after known failure classes)

Run on **uv-tool Python**:

```bash
$UVPY -m pytest \
  tests/test_runtime_controller.py \
  tests/test_attach_warm_pipeline.py \
  tests/test_runtime_publish.py \
  tests/test_mcp_bridge_concurrency.py \
  tests/test_process_job.py \
  tests/test_memory_governor.py \
  tests/test_memory_budget.py \
  tests/test_mcp_ship_preprod.py \
  -q --tb=short
```

- [ ] Run focused pack.
- [ ] Sync `npm/package.json` version with `pyproject.toml` if version-match test fails.
- [ ] Confirm CPU cap default is 20 (`engine_cpu_cap_pct() == 20`).

**Pass:** 0 fails in this pack.

---

### Task 3: Full pytest (`not slow`)

```bash
$UVPY -m pytest tests -m "not slow" -q --tb=line --maxfail=30 \
  2>&1 | tee docs/superpowers/plans/_preprod_<ver>/pytest_not_slow.log
```

- [ ] Run full suite on uv-tool Python (has ORT/FastEmbed).
- [ ] Triage remaining fails into: **ship blocker** vs **quality bakeoff** vs **stale fixture** vs **OS-skip**.
- [ ] Ship blockers must be fixed; bakeoffs (polytrace/embed_power F1) either fixed or explicitly deferred with version note in REPORT.

**Pass:** Gate E — 0 ship-blocker fails (ideal: 0 fails total).

---

### Task 4: MCP ship preprod + live ladder

```bash
$UVPY scripts/run_mcp_ship_preprod.py --require-live
# or with CLI combo included (default)
```

- [ ] L1+L2+L4 fast pytest pass.
- [ ] L3 live ladder pytest pass.
- [ ] `scripts/scubiee_mcp_ship_check.py` — **status must be ok**, not only map/pack/expand.
- [ ] If status fails while tools work: fix warming/`ok` contract (engine healthy before ship_check asserts).

**Pass:** ship script exit 0.

---

### Task 5: Availability — host-sim + warm contract

```bash
# Ensure engine can soft-ready BEFORE measuring cold attach; then let sim clean_slate itself
scubiee engine ensure
$UVPY scripts/mcp_host_sim.py --lane a --live --skip-idle \
  2>&1 | tee docs/superpowers/plans/_preprod_<ver>/host_sim.log

$UVPY scripts/warm_contract_acceptance.py \
  2>&1 | tee docs/superpowers/plans/_preprod_<ver>/warm_contract.log
```

**SLAs (Lane A):**

| Phase | Budget |
|-------|--------|
| soft_ready after host_start | ≤30s (prefer ≤10s) |
| map_first after soft | ≤1000 ms |
| pack_first | ≤1000 ms |
| expand_first | ≤5000 ms (prefer ≤1000 ms with prewarmed AST) |

- [ ] Host-sim exit 0 (no `WARM_TIMEOUT`, no `chunks=0` stuck).
- [ ] Warm contract: attach kick + warm_ready within deadline.
- [ ] If `chunks=0` after clean_slate: treat as **P0** — open/publish binder must complete before soft_ready.

**Pass:** Gate C availability green.

---

### Task 6: CLI combination + doctor/preflight

```bash
$UVPY scripts/run_cli_combination_tests.py --quick
scubiee doctor .
scubiee preflight .
```

- [ ] CLI combo all PASS.
- [ ] Doctor: enrolled, capabilities ok for this OS profile (dml/cpu on Win; mlx on Mac).
- [ ] Preflight ok (or documented known skip).

**Pass:** Gate D green.

---

### Task 7: Live Cursor / IDE smoke (manual + timed MCP)

With Scubiee MCP enabled in Cursor:

- [ ] `gate` / `status` → managed true, soft ready (or clear warming once).
- [ ] `map` #1 and #2 — record `elapsed_ms` (warm ≤1s).
- [ ] `pack_context` lean with suggested seed — ≤1s.
- [ ] `expand_context` — record hydrate_ms / source.
- [ ] `collect_hot_context`, `workspace` show/pin.
- [ ] Confirm Task Manager / Activity Monitor: idle CPU ~0; peaks ≤20%; RAM policy as agreed.

**Pass:** Live tools usable without reconnect thrash.

---

## Gate W — Windows-specific tests

Run **on Windows** (this machine / friend CPU-only laptop as needed).

### W1 — Profile & accel

- [ ] `scubiee setup --status` → profile `dml` (GPU) or `cpu` (iGPU-only) — never silent wrong profile.
- [ ] `tests/windows_production_test.py` (if marked for nt) or `tests/test_windows_discrete_gpu.py` / `tests/test_cpu_only_laptop_path.py` as applicable.
- [ ] FastEmbed + `onnxruntime-directml` (or CPU ORT) importable from **uv-tool** Python.

### W2 — Process / JobObject / pythonw

- [ ] `tests/test_process_job.py` — CPU rate = 20% default (`cpu_rate_for_percent(20)==2000`).
- [ ] `tests/test_console_blink_hotpaths.py` / `tests/test_silent_windows_spawn.py` / `tests/test_pythonw_mcp_stdio.py` — MCP uses **pythonw**, no console flash.
- [ ] `tests/test_disconnect_ram_exit.py` — disconnect RAM behavior.

### W3 — Availability under Windows dual-process pattern

- [ ] Host-sim Lane A live (parent+child pythonw tree OK; no `chunks=0` after clean_slate).
- [ ] After battery thrash: `scubiee engine stop` → `ensure` → soft_ready with chunks > 0 within budget.

### W4 — Optional friend laptop (CPU-only)

- [ ] Install, `setup --repair`, init, connect Cursor on Intel iGPU-only machine.
- [ ] Soft map works; profile stays `cpu`.

**Pass:** Gate W green on at least one Windows GPU or CPU-only path.

---

## Gate M — macOS-specific tests (required before Mac production claim)

Run **on Apple Silicon (preferred)** or Intel Mac. Do **not** invent new harnesses — use existing modules.

### M0 — Install & profile

```bash
uv tool install --force 'scubiee[macos]'   # or scubiee[mlx] on arm64
# from repo: uv tool install --force '.[macos]' --refresh
scubiee stop
scubiee setup --repair
scubiee setup --status
```

- [ ] Profile is **`mlx`** on Apple Silicon (never stuck on `cpu` after repair).
- [ ] Forced wrong path: `scubiee setup --profile cpu` then `scubiee setup --repair` → restores MLX.
- [ ] Libraries: mlx + fastembed + onnxruntime present as expected.

### M1 — Mac pytest modules (must-run)

```bash
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
cd /path/to/context-engine
# Prefer uv-tool interpreter that has mlx extras
python -m pytest \
  tests/mac_production_test.py \
  tests/test_coreml_mac.py \
  tests/test_mlx_backend.py \
  tests/test_mlx_mac.py \
  tests/test_cross_platform_profiles.py \
  tests/test_coderank_fp16.py \
  -q --tb=short \
  2>&1 | tee docs/superpowers/plans/_preprod_<ver>_macos/mac_pytest.log
```

| Module | Why Mac-only / Mac-critical |
|--------|------------------------------|
| `tests/mac_production_test.py` | Live Mac paths, permissions, multi-repo, MCP stdio on Darwin |
| `tests/test_mlx_backend.py` | MLX embed backend selection |
| `tests/test_mlx_mac.py` | MLX runtime / cache / embed paths |
| `tests/test_coreml_mac.py` | CoreML EP / CodeRank ONNX graph |
| `tests/test_cross_platform_profiles.py` | M-series recommend profile stays `mlx` |
| `tests/test_coderank_fp16.py` | FP16 ONNX / CoreML cache helpers |

- [ ] All above pass (or documented skip only for Intel-without-MLX with CoreML path proven).

### M2 — Darwin lifecycle / LaunchAgent

- [ ] `tests/test_lifecycle_runtime.py` Darwin cases (register LaunchAgent / bootout) — run on Mac or confirm still mocked-green on CI.
- [ ] `tests/test_hw_track.py` Darwin branch.
- [ ] Live: supervisor uses LaunchAgent (not orphan engine) after connect.

### M3 — Mac product journey

- [ ] `scubiee init .` on a small repo — index completes.
- [ ] `scubiee connect --cursor` (and optionally `--kiro`) — `status` → `managed: true`.
- [ ] Spot-check: after `scubiee stop`, use `scubiee resume` (not `wake`).
- [ ] Never demote Apple Silicon to CPU after transient GPU/MLX blip.
- [ ] Stop engine before `uv tool install --force` / upgrade (file locks).

### M4 — Mac availability (same scripts as Windows)

```bash
python scripts/run_mcp_ship_preprod.py --require-live --skip-cli
python scripts/mcp_host_sim.py --lane a --live --skip-idle
python scripts/warm_contract_acceptance.py
```

- [ ] Same SLAs as Task 5.
- [ ] Optional: `pytest tests/test_mcp_locate.py::test_live_search_read_flow -q`

### M5 — Mac memory / MLX cache behavior

- [ ] Confirm MLX cache limit / `clear_cache` after embed does **not** unload weights while MCP connected.
- [ ] Activity Monitor: idle CPU low; peaks acceptable; RSS full-warm policy documented.

### Do **not** require Mac to re-prove

- Windows DirectML discrete-GPU classifier
- Windows JobObject / pythonw console-blink
- Full Windows-only pytest already green on Windows

**Pass:** Gate M green on one Apple Silicon machine.

---

### Task 8: Write run report & ship decision

- [ ] Write `docs/superpowers/plans/_preprod_<ver>_<os>/REPORT.md` with scoreboard (copy structure from `_preprod_battery_0_3_89/REPORT.md`).
- [ ] Fill Mac results table in `docs/macos-deferred-verification.md` when Gate M runs.
- [ ] **Ship decision:**
  - **Windows production:** Gates A–D + W green; E has 0 ship-blockers.
  - **Mac production:** additionally Gate M green.
  - **Cross-platform production:** both OS gates green on the same version tag.

---

## Suggested execution order (calendar)

| Day | Focus |
|-----|--------|
| 1 | Task 0–2: env + curated e2e + fix stale attach/publish tests |
| 1–2 | Task 4–5: ship_check + host-sim P0 (`chunks=0` / WARM_TIMEOUT) |
| 2 | Task 3 + 6: full pytest triage + CLI |
| 2 | Task 7 + Gate W: live Cursor + Windows specifics |
| 3 | Gate M on Mac (MLX setup + Mac pytest + host-sim) |
| 3 | Task 8: REPORT + tag release only if gates pass |

---

## Known failure classes to watch (from 0.3.89 battery)

1. **Wrong interpreter** — `.venv` without ORT → cascade CapabilityError (not product bugs).
2. **Stale unit mocks** — attach singleflight / publish drop_engine / attach-warm ensure.
3. **Cold attach binder** — host-sim `chunks=0`, `soft_search_ready=false` → P0.
4. **Dual install** — uv-tool vs PATH shim fighting `~/.scubiee`.
5. **Quality bakeoffs** — polytrace/embed_power F1 under threshold (track separately).
6. **Version drift** — `npm/package.json` vs `pyproject.toml`.

---

## Quick command cheat-sheet

**Windows (PowerShell):**
```powershell
$UVPY = "$env:APPDATA\uv\tools\scubiee\Scripts\python.exe"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
scubiee engine ensure
& $UVPY scripts\run_scubiee_e2e_suite.py
& $UVPY scripts\run_mcp_ship_preprod.py --require-live
& $UVPY scripts\mcp_host_sim.py --lane a --live --skip-idle
& $UVPY scripts\warm_contract_acceptance.py
& $UVPY scripts\run_cli_combination_tests.py --quick
& $UVPY -m pytest tests -m "not slow" -q --tb=line
```

**macOS (zsh):**
```bash
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
uv tool install --force '.[macos]' --refresh
scubiee setup --repair && scubiee setup --status   # expect mlx on Apple Silicon
scubiee engine ensure
python -m pytest tests/mac_production_test.py tests/test_coreml_mac.py \
  tests/test_mlx_backend.py tests/test_mlx_mac.py tests/test_cross_platform_profiles.py -q --tb=short
python scripts/run_mcp_ship_preprod.py --require-live
python scripts/mcp_host_sim.py --lane a --live --skip-idle
```
