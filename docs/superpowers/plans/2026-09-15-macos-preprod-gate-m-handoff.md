# Handoff: macOS Gate M pre-prod (0.3.89)

**For:** whoever runs Scubiee on the MacBook  
**Date:** 2026-09-15  
**Version under test:** `0.3.89` (same tree / tag as Windows)  
**Goal:** Complete **Gate M** so we can claim Mac production (and then cross-platform) on this version.

---

## 1. Why you are doing this

Windows soft-path is already **conditionally ready**. Mac was **not run** and is required before any Mac/MLX ship claim.

| Gate | Windows (2026-09-15) | Your job on Mac |
|------|----------------------|-----------------|
| **A** Env hygiene | PASS | Re-prove on Darwin |
| **B** Curated e2e | PASS (163) | Re-run with uv-tool Python |
| **C** MCP ship + host-sim + warm | PASS | **Must re-run** (Lane A SLAs) |
| **D** CLI combo `--quick` | PASS 30/30 | Re-run |
| **E** Full pytest not-slow | Advisory | Optional / triage only |
| **W** Windows-specific | PASS practical | **Skip** (Windows-only) |
| **M** macOS / MLX | **Not run** | **This is the main deliverable** |

**Ship rules (from matrix):**

- Windows production: A–D + W green  
- **Mac production: A–D style availability + Gate M green**  
- Cross-platform: both OS on the **same** version tag  

Full matrix: `docs/superpowers/plans/2026-09-14-scubiee-preprod-test-matrix.md`  
Windows evidence: `docs/superpowers/plans/_preprod_0_3_89_win_prodcheck/REPORT.md`

---

## 2. What Windows already fixed (pull these before you test)

Install from **this repo** (or a commit that includes them). Do **not** test a stale PyPI wheel without these:

| Fix | Why it matters on Mac too |
|-----|---------------------------|
| Codex TOML env write (nested tables + escape) | Connect Codex must not write invalid TOML |
| MCP verify includes `args` (bridge detect) | Upgrade/verify treats `python -m pipeline.mcp_bridge` as bridge |
| Wipe removes **all three** uv entrypoints (`scubiee`, `scubiee-mcp`, `scubiee-mcp-bridge`) | After `wipe --all`, `uv tool install scubiee` should work **without** `--force` |
| Setup UI: single “Runtime installed” line | UX / progress dedup |
| Open hard-fail → `open_repo_failed` (not mislabeled warming) | Admission errors |
| WinError 193 daemon spawn fallback | Windows-specific; ignore on Mac |
| Console blink: disk-backed schtasks cache + pythonw worker fallback | Mostly Windows; Mac uses LaunchAgent — still use same tree |

**Critical lesson from Windows:** unit tests against `packages/` can be green while the **installed** `uv tool` binary is stale. Always:

```bash
cd /path/to/context-engine
uv tool install --force '.[macos]' --refresh   # Apple Silicon
# Intel Mac without MLX: uv tool install --force '.[macos]' or CPU path per docs
scubiee --version   # expect 0.3.89
```

Then confirm the live package path:

```bash
python -c "import pipeline; print(pipeline.__file__)"
# Should be under ~/.local/share/uv/tools/scubiee/... (not only the source tree)
```

---

## 3. Machine / env rules (do not skip)

1. **One install owns `~/.scubiee`** — prefer `uv tool` only. Uninstall stray pip/conda scubiee copies.
2. Run pytest with the **uv-tool Python that has MLX/ORT**, not a bare venv missing accel.
3. Always set: `export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`
4. Prefer invoking the uv-tool `scubiee` on PATH after install; if `doctor` complains about binaries mismatch, call the tool binary under `$(uv tool dir)/scubiee/bin/scubiee` (path shape may vary — check `uv tool dir`).
5. Soft map/pack SLA after warm: **≤1s**; expand first hydrate may be slower once; keep CPU calm (Windows capped 20%; on Mac record Activity Monitor peaks).
6. Stop engine before `uv tool install --force` / upgrade (file locks).
7. After `scubiee stop`, use **`scubiee resume`** (not `wake`).
8. On Apple Silicon: profile must be **`mlx`**, never stuck on `cpu` after `--repair`.

Create a run folder:

```bash
mkdir -p docs/superpowers/plans/_preprod_0_3_89_macos
```

---

## 4. Exact sequence (copy-paste)

### Step 0 — Sync + install

```bash
cd /path/to/context-engine
git status   # confirm you’re on the handoff commit / branch with 0.3.89 fixes
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
unset CTX_HOME CTX_ALLOW_TEST_HOME   # never leave test home pointed at real ~/.scubiee mid-battery

uv tool install --force '.[macos]' --refresh
scubiee stop || true
scubiee --version
```

Find uv-tool Python (use this for all scripts/pytest below):

```bash
# Typical Apple Silicon / uv layout — adjust if `uv tool dir` differs:
UVPY="$(uv tool dir)/scubiee/bin/python"
# Fallback if needed:
# UVPY="$(dirname "$(dirname "$(readlink -f "$(which scubiee)")")")/bin/python"

"$UVPY" -c "import mlx, fastembed, onnxruntime; print('mlx_ok', mlx.__file__)"
```

### Step 1 — Gate A (env + soft ready)

```bash
scubiee setup --repair
scubiee setup --status          # expect profile: mlx on Apple Silicon
scubiee engine ensure
scubiee status --json | tee docs/superpowers/plans/_preprod_0_3_89_macos/status_a.json
```

**Pass:** `enrolled` (if this repo is managed), `soft_search_ready: true`, `chunks > 0`.  
If this is a fresh Mac checkout of context-engine: `scubiee init .` then ensure/status again.

**Forced MLX restore check:**

```bash
scubiee setup --profile cpu
scubiee setup --repair
scubiee setup --status          # must return to mlx on Apple Silicon
```

### Step 2 — Gate M0–M1 (Mac pytest)

```bash
# Install pytest into uv-tool env if missing:
uv pip install --python "$UVPY" pytest

"$UVPY" -m pytest \
  tests/mac_production_test.py \
  tests/test_coreml_mac.py \
  tests/test_mlx_backend.py \
  tests/test_mlx_mac.py \
  tests/test_cross_platform_profiles.py \
  tests/test_coderank_fp16.py \
  -q --tb=short \
  2>&1 | tee docs/superpowers/plans/_preprod_0_3_89_macos/mac_pytest.log
```

| Module | Why |
|--------|-----|
| `mac_production_test.py` | Live Mac paths, permissions, multi-repo, MCP stdio |
| `test_mlx_backend.py` / `test_mlx_mac.py` | MLX embed / cache |
| `test_coreml_mac.py` | CoreML / CodeRank ONNX |
| `test_cross_platform_profiles.py` | M-series stays `mlx` |
| `test_coderank_fp16.py` | FP16 / CoreML helpers |

Optional Darwin lifecycle:

```bash
"$UVPY" -m pytest tests/test_lifecycle_runtime.py tests/test_hw_track.py -q --tb=short \
  2>&1 | tee docs/superpowers/plans/_preprod_0_3_89_macos/mac_lifecycle.log
```

### Step 3 — Gate B (curated e2e, same as Windows)

```bash
"$UVPY" scripts/run_scubiee_e2e_suite.py \
  --out docs/superpowers/plans/_preprod_0_3_89_macos/e2e-suite-results.json \
  2>&1 | tee docs/superpowers/plans/_preprod_0_3_89_macos/e2e_suite.log
```

**Pass:** `[e2e] ok=True` (Windows had 163 passed).

### Step 4 — Gate C (real MCP ship + host-sim + warm) — **P0**

```bash
scubiee engine ensure

"$UVPY" scripts/scubiee_mcp_ship_check.py \
  2>&1 | tee docs/superpowers/plans/_preprod_0_3_89_macos/ship_check.log

"$UVPY" scripts/mcp_host_sim.py --lane a --live --skip-idle \
  2>&1 | tee docs/superpowers/plans/_preprod_0_3_89_macos/host_sim.log

"$UVPY" scripts/warm_contract_acceptance.py \
  2>&1 | tee docs/superpowers/plans/_preprod_0_3_89_macos/warm_contract.log
```

**Lane A budgets (must meet):**

| Phase | Budget |
|-------|--------|
| soft_ready after host_start | ≤30s (prefer ≤10s) |
| map_first after soft | ≤1000 ms |
| pack_first | ≤1000 ms |
| expand_first | ≤5000 ms (prefer ≤1000 ms) |

**P0 failures:** `WARM_TIMEOUT`, `chunks=0` stuck after clean_slate, empty heatmap with soft false.  
Windows reference SLAs this cycle: soft ~2.9s, map/pack ~60ms, expand ~0.65s.

Also acceptable: `scripts/run_mcp_ship_preprod.py --require-live --skip-cli` if you use that wrapper.

### Step 5 — Gate D (real CLI combo)

```bash
"$UVPY" scripts/run_cli_combination_tests.py --quick \
  2>&1 | tee docs/superpowers/plans/_preprod_0_3_89_macos/cli_combo.log

scubiee doctor . 2>&1 | tee docs/superpowers/plans/_preprod_0_3_89_macos/doctor.log
scubiee preflight . 2>&1 | tee docs/superpowers/plans/_preprod_0_3_89_macos/preflight.log
```

**Pass:** all combo rows PASS (Windows: 30/30).  
Note: CLI combo **stops the engine** — re-run `scubiee engine ensure` before claiming soft-ready again.

### Step 6 — Gate M3 product journey (manual)

```bash
# Small clean repo or this checkout after ensure:
scubiee init .          # if not enrolled
scubiee connect --cursor
scubiee status --json   # managed / soft_search_ready
scubiee stop
scubiee resume          # not wake
```

- [ ] Cursor (or Kiro) MCP: `gate` / `status` → managed; soft ready  
- [ ] Live `map` then `pack_context` lean ≤1s when warm  
- [ ] Activity Monitor: idle CPU low; RSS full-warm while connected is OK  

### Step 7 — Report

Write:

`docs/superpowers/plans/_preprod_0_3_89_macos/REPORT.md`

Copy the scoreboard shape from `_preprod_0_3_89_win_prodcheck/REPORT.md`.

Also fill one row in `docs/macos-deferred-verification.md` “Record results” table.

---

## 5. What “done” looks like

| Check | Done when |
|-------|-----------|
| Gate M | MLX profile + Mac pytest green + journey OK |
| Availability | host-sim Lane A + warm_contract + ship_check exit 0 |
| CLI | combo `--quick` all PASS |
| Report | `_preprod_0_3_89_macos/REPORT.md` with numbers + ship decision |

**Ship decision language to use:**

- If M + C + D green: **Mac production READY for 0.3.89** (plus Windows already conditional).  
- If only Mac pytest green but host-sim fails: **not ready** — host-sim is P0.

---

## 6. Pitfalls (from Windows + older Mac sessions)

1. **Wrong interpreter** → cascade CapabilityError; always uv-tool Python with MLX.  
2. **Stale uv tool** after pulling fixes → `uv tool install --force '.[macos]' --refresh`.  
3. **`CTX_HOME` / `CTX_ALLOW_TEST_HOME` left set** → wrong home / wrong port; unset before Gate A.  
4. **Dual install** (pip + uv) fighting `~/.scubiee`.  
5. **Host-sim leftovers** — sim should kill MCP leftovers; if soft stuck false, quit IDE MCP / kill stray scubiee MCP procs then re-ensure.  
6. **Cursor `${workspaceFolder}`** — older Mac notes: global pins may leave `managed=false`; prefer project-level connect (`scubiee connect --cursor` in the repo).  
7. **Do not** re-prove Windows DML / JobObject / pythonw blink on Mac.  
8. Quality bakeoffs (polytrace F1, etc.) are **advisory** — do not block soft-path if map/pack SLAs are green.

---

## 7. Optional wipe sanity (quick)

Only if you have time — validates the wipe shim fix on Darwin too:

```bash
# Destructive to local scubiee state — use a throwaway machine profile or accept re-setup
# scubiee wipe --all --confirm
# ls ~/.local/bin/scubiee*     # should be gone
# uv tool install '.[macos]'   # should NOT need --force for “executables already present”
# scubiee setup --repair
```

---

## 8. How to send results back

Paste or commit:

1. `docs/superpowers/plans/_preprod_0_3_89_macos/REPORT.md`  
2. Logs under that folder (`host_sim.log`, `cli_combo.log`, `mac_pytest.log`, …)  
3. Machine line: model (e.g. MacBook Pro M-series), macOS version, `scubiee --version`, profile (`mlx`/`cpu`)  
4. One-line verdict: **Gate M PASS/FAIL** + any P0 blocker  

Contact context: Windows operator already signed A–D/W conditional green on 0.3.89; you own Gate M + Mac availability parity.
