# Scubiee Context Engine — E2E Test Report (2026-09-14)

## 1. Architecture summary

Scubiee is a multi-process context system:

| Layer | Process / module | Role |
|-------|------------------|------|
| IDE wrapper | Cursor → `pipeline.mcp_bridge` | Stdio MCP proxy; spawns `mcp_locate` workers; attach-warm kick |
| Tool surface | `pipeline.mcp_locate` | `gate/map/pack_context/expand_context/collect_hot_context/workspace/expand/status` |
| Engine | `pipeline engine run` / `ce_service.RuntimeManager` | HTTP search, publish binder, open_repo, health |
| Sync / keeper | `BackgroundSyncLoop` | Dirty ledger, debounce, locate-streak deferral, publish |
| Resources | `memory_governor` + `memory_budget` | Tiered RAM (locate_only → indexing), embed demote |
| Lifecycle | `lifecycle_runtime` + `RuntimeController` | Clients, idle unload, coalesce, supervisor/watchdog |

**Locate flow:** soft `map` → lean `pack_context` → optional `expand_context` / `collect_hot_context`. Soft search uses BM25/hash binder; FastEmbed may still be loading (`soft_search_ready` ≠ `embedder_loaded`).

**Sync flow:** watch/editor `mark_dirty` → debounce → incremental sync → `publish_engine` (generation bump). Locate streak defers sync so map/pack are not GIL-starved; **final_check must flush** on stop.

## 2. Existing test audit

~194 `tests/test_*.py` modules. Strong clusters already exist:

- **Wrapper / lifecycle:** `test_lifecycle_*`, `test_mcp_bridge*`, `test_runtime_controller`, `test_mcp_host_sim`
- **Resources:** `test_memory_governor`, `test_memory_budget`, `test_runtime_publish`
- **Sync:** `test_live_reindexing`, `test_watcher_recovery`, `test_freshness`, `test_sync_status_canaries`
- **Tools:** `test_incremental_context_ladder`, `test_expand_*`, `test_multi_seed_v1`, semantic/trace bakeoffs
- **Acceptance scripts:** `mcp_host_sim.py`, `warm_contract_acceptance.py`, `run_mcp_ship_preprod.py`

### Gaps found (and addressed this session)

| Gap | Severity | Action |
|-----|----------|--------|
| Bridge emitted `tools/list_changed` on every tools/call | High (duplicate Cursor bridges) | Fixed + unit test |
| `expand_context` cold AST bake wedged worker ~23s | High | Bundle-only + warming; MCP no-bake |
| Soft warm ~20s after connect | High | Listen-then-bg-open; skip re-open when soft |
| `final_check` left dirty unpublished under locate streak | High | Clear streak + force flush |
| No single curated e2e runner across layers | Medium | `scripts/run_scubiee_e2e_suite.py` |
| Matrix tests for concurrent dirty / empty publish keep | Medium | `tests/test_e2e_system_matrix.py` |

## 3. Scenario matrix (priority)

### A. Wrapper / resources
- Attach warm singleflight; soft vs embed ready
- Client register / coalesce (bridge kept, workers dropped)
- Idle unload only after leave + debounce
- Governor indexing tier caps over multi-session
- Empty `publish_engine` keeps previous binder

### B. Tools
- map ≤1s after soft; steady map hundreds of ms
- 3-seed lean pack ≤1s warm
- expand without cold bake; DUP_BRIDGE gate in host-sim
- collect_hot_context / gate / status / workspace smoke

### C. Sync
- Concurrent mark_dirty coalescing
- Watcher overflow → full reconcile
- Locate streak defers live sync
- **final_check forces held publish** (bug fixed)
- Oversized change → explicit full index required

### D. Large / concurrent
- Host-sim cold attach → map → pack → expand (no dup bridge)
- Dual Cursor MCP groups (detected live; root cause list_changed)

## 4. What was added / modified

| Artifact | Purpose |
|----------|---------|
| `tests/test_e2e_system_matrix.py` | Gap fillers (dirty burst, empty publish, AST no-bake, coalesce, governor) |
| `scripts/run_scubiee_e2e_suite.py` | Curated cross-layer pytest battery + JSON report |
| `packages/pipeline/mcp_bridge.py` | list_changed only on real respawn |
| `packages/pipeline/mcp_locate.py` / `context_trace.py` | Expand hydrate / no MCP bake |
| `packages/pipeline/sync_loop.py` | final_check clears locate streak + delivers publish |
| `packages/pipeline/daemon.py` / `runtime_controller.py` / `ce_service.py` | Soft warm speedups (prior beat) |
| Host-sim `expand_first` + DUP_BRIDGE | Live process-group regression |

## 5. Execution results

### Curated unit/integration suite
```
163 passed in ~35s
scripts/run_scubiee_e2e_suite.py → ok=True
Report: docs/superpowers/plans/e2e-suite-results.json
```

### Host-sim (lane A, live, skip-idle) — 2026-09-14T121133Z
| Phase | ms | notes |
|-------|-----|-------|
| soft_ready FIRST | +1.14s from host_start | was ~20s |
| map_first | 315 | ≤1s |
| pack_first | 285 | ≤1s |
| expand_first | 1874 | was ~23s; no DUP_BRIDGE |

### Live Cursor maps (same day)
| Call | ms |
|------|-----|
| after ~30s settle | 1378 |
| steady | 736 / 1025 / 654 |
| 3-seed pack | 426 |

## 6. Bugs found → root cause → fix

1. **Duplicate MCP process groups** — `tools/list_changed` spam + expand GIL wedge → Cursor second NodeService bridge. Fixed emit-on-respawn-only + expand no-bake.
2. **final_check unpublished dirty** — locate streak deferred forever on stop. Fixed clear streak + force flush/publish.
3. **Stale publish test** — `load_engine(..., base_dir=None)` API drift. Test updated.

## 7. Performance baselines (this machine)

| Metric | Target | Observed |
|--------|--------|----------|
| Soft ready after attach | ≤10s | ~1.1s (engine reused / bg-open) |
| First map after soft | ≤1s | 315–1378 ms |
| Steady map | ≤300–800 ms | 650–1025 ms |
| Lean pack | ≤1–5s | ~285–426 ms |
| Expand (bundle warm) | ≤5s | ~1.9s |
| Expand (cold bake) | forbid on MCP | warming / bg bake |

## 8. Remaining risks / follow-ups

- Bridge nested pythonw parentage still looks like “double bridge” in Task Manager (display quirk) — count **top-level** bridges only.
- Full 194-file pytest not re-run this beat (curated 163); schedule nightly full.
- Large monorepo AST bundle miss still needs background bake UX (`ast_warming` retry).
- Live multi-window Cursor still can start two MCP configs if duplicate `mcp.json` entries exist — audit global+project.
- Stress: intentional multi-MB dirty while 3 parallel packs (not yet automated beyond unit dirty burst).
- Reinstall + Cursor MCP reload required for production pick-up of today’s fixes.

## 9. How to re-run

```bash
uv tool install --force . --refresh
.\.venv\Scripts\python.exe scripts\run_scubiee_e2e_suite.py
.\.venv\Scripts\python.exe scripts\mcp_host_sim.py --lane a --live --skip-idle
```
