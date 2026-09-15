# Scubiee 0.3.89 macOS Gate M pre-prod check

**Date:** 2026-09-15  
**Machine:** MacBook Pro — Apple M5, macOS 26.5.2 (25F84), arm64  
**Install:** `uv tool install --force '.[macos]' --refresh` from commit `1307ee5`  
**Python:** `~/.local/share/uv/tools/scubiee/bin/python` (3.10.21)  
**Profile:** `mlx` @ **109.1–110.1 t/s** (Metal FP16)  
**Harness:** real `scubiee` CLI + uv-tool Python scripts — not in-process mocks for ship decision.

## Verdict

**Mac production READY for 0.3.89 (soft-path / MCP)** — Gates **A, M (pytest), C, D** green after killing a stale `.venv` 0.3.29 daemon.

**Not unconditional CLI parity:** `scubiee pack` crashes on this install (`ModuleNotFoundError: trace_lab.multi_seed` — module absent from both source tree and wheel). MCP `pack_context` in host-sim / ship_check is fine. `doctor` reports `checksum_mismatch` until a rebuild.

Windows already conditional READY; same version tag → **cross-platform soft-path can be claimed** with the CLI-pack caveat below.

| Gate | Result | Evidence |
|------|--------|----------|
| **A** Env | **PASS** | `scubiee 0.3.89`; profile `mlx`; enrolled; chunks=5710; MLX restore after `--repair` stays mlx |
| **B** Curated e2e | **PASS (partial)** | Official runner **hard-fails**: missing `tests/test_runtime_controller.py` (+ 4 other listed files). Existing 11 targets: **129 passed**. Not the Windows 163. |
| **C** MCP + availability | **PASS** | host-sim Lane A ok; warm_contract 0 failed; ship_check ladder ok |
| **D** CLI journey | **PASS** | `run_cli_combination_tests.py --quick` **30/30** |
| **M** macOS / MLX | **PASS** | Mac pytest **66 passed**; lifecycle optional **27 passed**; product journey soft-ready on 0.3.89 |
| **E** Full pytest | **not run** | Advisory per matrix |
| **W** Windows | **skip** | Windows-only |

## Host-sim SLAs (this run — after stale venv removed)

| Phase | Budget | Result |
|-------|--------|--------|
| soft_ready from host_start | ≤30s (prefer ≤10s) | **0.67 s** |
| map_first | ≤1000 ms | **3.3 ms** |
| pack_first | ≤1000 ms | **3.4 ms** |
| expand_first | ≤5000 ms (prefer ≤1000) | **141 ms** |

First attempt **failed** `WARM_TIMEOUT` because port 8765 was owned by a hung **`.venv` 0.3.29** engine while CLI was 0.3.89. After `mv .venv /tmp/...` and re-ensure, health reported `version: 0.3.89` and Lane A passed.

## Warm contract

All checks PASS (`failed: 0`): attach_kick, warm_ready_within_deadline (~1.36s, soft_search_ready=true), first_map_after_ready ~479ms, map_after_idle ~487ms.

## Mac pytest (Gate M0–M1)

```
tests/mac_production_test.py
tests/test_coreml_mac.py
tests/test_mlx_backend.py
tests/test_mlx_mac.py
tests/test_cross_platform_profiles.py
tests/test_coderank_fp16.py
→ 66 passed in 17.78s
```

Optional: `test_lifecycle_runtime.py` + `test_hw_track.py` → **27 passed**.

## Critical Mac pitfalls (this session)

1. **Stale local `.venv` steals the daemon.** `install_marker.json` still pointed at `.../hidden-context-engine-/.venv` (0.3.29). `scubiee engine ensure` spawned that interpreter even though `which scubiee` was uv-tool 0.3.89. Health then showed `version: 0.3.29`. Host-sim timed out on soft-ready. **Fix:** remove/rename `.venv` before Gate C; rewrite `~/.scubiee/install_marker.json` to the uv-tool prefix; never leave two installs sharing `~/.scubiee`.
2. **`run_scubiee_e2e_suite.py` is broken on this tree** — references `tests/test_runtime_controller.py` (and others) that do not exist. Runner exits before any tests.
3. **CLI `pack` import bug:** `from trace_lab.multi_seed import ...` but `multi_seed` is not in `packages/trace_lab/` or the installed wheel. MCP pack path still green.
4. **`doctor` → checksum_mismatch** (`rebuild_index` in repair_plan). Soft search still worked for host-sim; index may need `scubiee rebuild` / re-init for doctor green.
5. LaunchAgent / dual-install warnings can persist until marker + supervisor are aligned with uv-tool only.

## Ship decision language

> **Mac production READY for 0.3.89** for soft-path / MCP availability (Gate M + C + D), matching Windows conditional READY on the same tag.  
> Block claiming full CLI locate parity until `trace_lab.multi_seed` (CLI pack) is fixed or the import is removed.  
> Operators: wipe any repo-local `.venv` before uv-tool Gate C runs.

## Logs

Under `docs/superpowers/plans/_preprod_0_3_89_macos/`:

- `mac_pytest.log`, `mac_lifecycle.log`
- `host_sim.log`, `mcp-host-sim-20260915T122408Z.{json,md}`
- `warm_contract.log`, `ship_check.log`
- `cli_combo.log`, `e2e_suite*.log`, `doctor.log`, `preflight.log`
- `status_a.json`, `setup_*.log`, `install.log`
