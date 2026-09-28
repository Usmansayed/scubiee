# Scubiee pre-prod battery — 0.3.89 (2026-09-14)

## Verdict: **NOT production-ready yet**

Core CLI combo and most unit/integration tests pass, but **availability/warm gates failed** (host-sim WARM_TIMEOUT with `chunks=0`) and **44 pytest failures** remain. Dual-install PATH noise is present.

Logs: `docs/superpowers/plans/_preprod_battery_0_3_89/`

| Layer | Result | Detail |
|-------|--------|--------|
| A. Curated e2e suite | **FAIL** | 160 passed, **3 failed** (~30s) |
| B. Full pytest `not slow` | **FAIL** | **1555 passed**, 18 skipped, **44 failed**, 1 error (~8m) |
| C. MCP ship preprod | **PARTIAL** | L1+L2+L4 pytest **PASS**; live ladder pytest **PASS**; `scubiee_mcp_ship_check.py` **FAIL** (status not healthy / warming) |
| D. Host-sim Lane A live | **FAIL** | `auto_warm: WARM_TIMEOUT` (~30s); engine `chunks=0`, `soft_search_ready=false` (retry also failed) |
| E. CLI doctor / preflight | **WARN** | version **0.3.89**; doctor reports PATH binary mismatch + embed_accel cache/`local_files_only` issues |
| F. Warm contract | **FAIL** | attach kick PASS; warm_ready within 10s deadline **FAIL** |
| G. CLI combination quick | **PASS** | **36/36** |

## What is green (ship-critical surfaces)

- Most MCP unit contracts (lean / permissions / pack bodies / bridge concurrency / wipe)
- Live ladder pytest: gate → map → pack → expand
- CLI combination matrix (stop/resume/connect/lifecycle guards)
- Large majority of the suite (1555 tests)

## Ship-check live tool results (script fail reason)

During `scubiee_mcp_ship_check.py`, tools that returned ok:

- `pack_context` ok (heatmap_n=8)
- `expand_context` ok (count=10)
- `workspace` ok
- `collect_hot_context` ok

Failed gate:

- `status` → `ok=false`, `engine_healthy=false`, agent warming / engine starting

## Host-sim failure (availability)

After clean_slate + bridge spawn, soft never became ready within 30s:

- Engine process observed with **`chunks: 0`**
- `soft_search_ready: false`
- Health socket intermittently `ConnectionAbortedError` (WinError 10053)
- Clients registered (`kiro` bridge+proc) but binder never published

This is a **production blocker** for cold-attach availability.

## Curated e2e failures (3)

1. `test_runtime_controller.py::test_ensure_attach_is_singleflight`
2. `test_runtime_publish.py::test_publish_engine_bumps_generation`
3. `test_attach_warm_pipeline.py::test_start_attach_warm_pipeline_returns_immediately`

## Full pytest failure buckets (44 + 1 error)

Rough groups:

- **lifecycle / attach / client retry** — runtime_controller, attach_warm, lifecycle_ownership, mcp_agent_warm_retry, mcp_lifecycle_universal, production_hardening, root_probe
- **publish** — runtime_publish generation bump
- **install / connect / upgrade / hosts** — package_install versions, upgrade scenarios, codex connect fans-out, mcp_config_merge
- **semantic / quality bakeoffs** — venture_stack, embed_power, polytrace, verify_board, vague_prompts, seeded_compare, locate_quality
- **platform / CPU job / CoreML / MLX / progress** — process_job breakaway flag, coreml_mac, mlx_backend, embedder_progress, setup_progress, console_blink
- **ERROR** — `test_venture_stack.py::test_t1_dml_provider_present` (ModuleNotFound)

## Environment risks seen during battery

1. **Two Scubiee installs** fighting over `~/.scubiee` (uv tool + another install / PATH shim at `~/.local/bin/scubiee`).
2. Doctor: `binaries_match=false` (invoked shim ≠ expected uv tool binary).
3. FastEmbed cache errors under `local_files_only=True` during doctor.

## Recommended fix order before production

1. Stabilize **cold attach → soft_search_ready** (host-sim WARM_TIMEOUT / chunks=0).
2. Resolve **dual install / PATH** so one binary owns `~/.scubiee`.
3. Fix the **3 curated e2e** attach/publish regressions.
4. Triage remaining pytest fails (many are quality/bakeoff or host-specific; not all are ship blockers).
5. Re-run this battery until: e2e PASS, host-sim PASS, ship_check PASS, warm_contract PASS.
