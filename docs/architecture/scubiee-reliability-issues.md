# Scubiee Reliability — Master Issues Inventory

> **Source of truth** for MCP / engine / watchdog reliability.
> Historical context: [`watchdog-root-causes.md`](watchdog-root-causes.md), [`watchdog-mcp-lifecycle.md`](watchdog-mcp-lifecycle.md).
>
> **Package baseline:** 0.3.74  
> **Last updated:** 2026-09-12

## Agent-facing contract (short)

| Signal | Meaning | Agent action |
|--------|---------|--------------|
| `warming: true` / `should_retry: true` / `retry_after_s: N` | Engine coming up | Wait N seconds; **retry the same tool once**. Do not poll `status()` in a loop. |
| `agent_ready: "yes"` + `embedder_loaded: true` | Semantic locate ready | `map` → `pack_context(lean)` as needed |
| `agent_ready: "warming"` + `embedder_loaded: false` | HTTP/index may be up; FastEmbed still loading | Wait ~3s; retry map once — not fully ready |
| `agent_ready: "warming"` (engine down) | Not ready | Retry locate shortly |
| `gate` line `1:ce_… warming retry:3` | Managed + engine warming | Wait ~3s; retry locate |
| `pack` `sla_hint` when slow | Pack is heavy AST/trace | Not a hang; prefer lean single-seed |

### Expected process tree (one Cursor connection)

```
Cursor
  └─ pythonw -m pipeline.mcp_bridge     # stable stdio front (hot-reload)
       └─ pythonw -m pipeline.mcp_locate  # tool worker
Engine (separate):
  pythonw -m pipeline engine run … --no-open
```

Two Cursor connections ⇒ two bridge+locate trees (4 MCP processes). That is **by design**, not a double engine.

Nested bridge→bridge / locate→locate rows in Windows explorers are usually **parentage display** of `pythonw -m`, not a second tool server (see R10).

---

## Issue inventory

### R1 — First MCP call hangs past Cursor ~60s timeout

| | |
|--|--|
| **Symptom** | `map`/`gate` never returns; MCP error `-32001` timeout |
| **Root cause** | Request thread blocked on `ensure_daemon` health wait, `open_repo(wait=True)`, `ensure_embedder_ready`, and historically `force_restart_daemon`; nonblocking path still POSTed `/v1/open` while `/health` down (~8s+) |
| **Status** | `fixed` (0.3.72–0.3.73) |
| **Evidence** | Pre-fix: map timed out 3×. 0.3.73 cold: `ensure_nonblocking` **~1.5s**; first call **0.36s** with `warming=true` |
| **Acceptance** | `python scripts/cold_start_acceptance.py` after `engine stop` — all PASS; first call &lt;15s with success **or** explicit warming/retry |
| **Owner** | `mcp_lifecycle.py`, `mcp_locate.py`, `ce_service.py`, `scripts/cold_start_acceptance.py` |

### R2 — Double engine start via `_client_for` force_restart

| | |
|--|--|
| **Symptom** | Two `--- start` lines ~40s apart; extra console/WMI churn |
| **Root cause** | `_client_for` called `force_restart_daemon` when `/v1/open` status ≠ `activated` |
| **Status** | `fixed` (0.3.72) |
| **Evidence** | Removed from `_client_for` |
| **Acceptance** | `test_client_for_returns_warming_without_force_restart` |
| **Owner** | `mcp_locate.py` |

### R3 — Watchdog auto-load races agent warm

| | |
|--|--|
| **Symptom** | Watchdog `force_restart` while agent also starts engine |
| **Root cause** | Watchdog auto-start with MCP clients + dead PID |
| **Status** | `fixed` (0.3.71) — default skip; `CTX_WATCHDOG_AUTO_START=1` opt-in |
| **Evidence** | `watchdog.log`: `skip auto load (agent warm)` |
| **Acceptance** | `tests/test_watchdog.py` default no autoload |
| **Owner** | `watchdog.py` |

### R4 — Terminal blink (console shims / DETACHED / taskkill)

| | |
|--|--|
| **Symptom** | Console windows flash on MCP reconnect / spawn |
| **Root cause** | uv `scubiee-mcp*.exe` console subsystem; `DETACHED_PROCESS`; raw `taskkill` |
| **Status** | `partial` → **fixed** (0.3.75): heal no longer netstats every 15s; schtasks Query sticky-cached + `hidden_run` |
| **Evidence** | 0.3.74: helper probes → `hidden_run`. 0.3.75: `heal_engine_lock` lock-present fast path; `_live_engine_identity` lock-before-netstat; schtasks SW_HIDE + miss cache; accel GPU probes hidden. |
| **Acceptance** | `tests/test_console_blink_hotpaths.py`; live mcp.json uses `pythonw` + `windowsHide`; no periodic heal netstat; no `DETACHED_PROCESS` in schedule-delete |
| **Owner** | `daemon.py`, `lifecycle_runtime.py`, `process_job.py`, `mcp_bridge.py` |

### R5 — Confusing multi-process tree

| | |
|--|--|
| **Symptom** | “Why are there 2 MCP processes?” |
| **Root cause** | Bridge + worker architecture for hot reload |
| **Status** | `by-design` (documented) |
| **Evidence** | Parent chain Cursor→bridge→locate |
| **Acceptance** | Documented above; warming `status.hint` mentions bridge→locate |
| **Owner** | this doc; `mcp_locate.py` status hint |

### R6 — Warm `map` latency variance (0.8s vs 15s)

| | |
|--|--|
| **Symptom** | Same warm engine; map sometimes slow |
| **Root cause** | Keeper sync / embed / GC contention vs locate path |
| **Status** | `partial` (0.3.73) — keeper skips interval ticks + change polls during `locate_streak`; skips GC while streak active |
| **Evidence** | Prior: map2 **15168ms**. Unit: `test_keeper_tick_skips_during_locate_streak` |
| **Acceptance** | Warm map p95 &lt; ~2s when no concurrent pack; keeper logs `skip tick — locate_streak` |
| **Owner** | `sync_loop.py` |

### R7 — `pack_context` often ~15–20s

| | |
|--|--|
| **Symptom** | Pack feels hung; agents think Scubiee is broken |
| **Root cause** | AST/trace multi-seed work is heavy |
| **Status** | `partial` (0.3.78) — total Scubiee tree budget ≤800 MB serve / ≤1 GB index; no FastEmbed in bridge/locate |
| **Evidence** | Pre-fix tree ~2.3 GB (engine~1GB + locate~800 + bridge~488). Post: bridge~30 MB, locate~80 MB; engine still ~1.2 GB with warm DML (ORT). |
| **Acceptance** | Pack always has `elapsed_ms` + `timing`; lean single-seed target **5s**, multi-seed **8s**; total process-tree serve ≤**800 MB** when possible, ≤**1 GB** for index/init; bakeoff hard/F1 no regress |
| **Owner** | `context_trace.py` |

### R8 — Agent tool story opaque

| | |
|--|--|
| **Symptom** | “Don’t understand tools / feels unreliable” |
| **Root cause** | Dense GATE rules; ready vs warming conflated |
| **Status** | `partial` (0.3.73) — contract table + `embedder_loaded` / honest `agent_ready` |
| **Acceptance** | `status` exposes `embedder_loaded` + `semantic_ready`; `agent_ready≠yes` when embedder not loaded |
| **Owner** | `sync_status.py`, `mcp_locate.py`, this doc |

### R12 — Attach warm ≤10s then ms steady

| | |
|--|--|
| **Symptom** | First map pays 15–25s; idle minutes feel cold again |
| **Root cause** | Warm deferred to first tool; AST rebuild on pack; no join of attach budget |
| **Status** | `partial` (0.3.79) — `CTX_MCP_ATTACH_WARM` parallel pipeline; `warm_ready`; AST bundle hydrate; map cache; hold while any client |
| **Evidence** | Unit: `tests/test_attach_warm_pipeline.py`; live: `scripts/warm_contract_acceptance.py` |
| **Acceptance** | Attach → `warm_ready` ≤10s; after idle ≥60s with bridge: map wall ≤300ms; unload only when clients=0 |
| **Owner** | `warm_contract.py`, `mcp_lifecycle.py`, `mcp_bridge.py` |

### R9 — Pin/build stamp lag after install

| | |
|--|--|
| **Symptom** | `mcp.json` shows `CTX_SCUBIEE_BUILD: 0.3.71-*` after newer install |
| **Root cause** | `server_entry` reused stale `active_build.json` without rewriting for installed version |
| **Status** | `fixed` (0.3.73) — `ensure_active_build_stamp()` on connect/server_entry |
| **Acceptance** | After `server_entry()`, stamp version matches `installed_version()`; unit `test_server_entry_build_matches_installed` |
| **Owner** | `mcp_hot_reload.py`, `mcp_install.py` |

### R10 — Nested bridge→bridge / locate→locate chains

| | |
|--|--|
| **Symptom** | Process explorer shows 4-deep MCP chain |
| **Root cause** | Windows `pythonw -m` parentage display; spawn code creates one bridge→one locate |
| **Status** | `by-design` (appearance) — no double-exec found in `spawn_child_process` |
| **Acceptance** | One connection: one bridge parent + one locate worker; documented in bridge docstring |
| **Owner** | `mcp_bridge.py`, this doc |

### R11 — Registry `PermissionError` on `/v1/open`

| | |
|--|--|
| **Symptom** | `engine.log` traceback: `os.replace` Access Denied on `registry.json` |
| **Root cause** | Concurrent writers / AV locking file during atomic replace |
| **Status** | `fixed` (0.3.73) — `_write_json` retries replace with backoff |
| **Evidence** | Unit `test_write_json_retries_permission_error` |
| **Acceptance** | Simulated PermissionError then success; no uncaught replace failure under light contention |
| **Owner** | `project_id.py` |

### R12 — Historical Problem G (mcp.json restore storm)

| | |
|--|--|
| **Symptom** | Continuous MCP reconnect / blink storm |
| **Root cause** | `heal_mcp_pins` from `start_daemon`; pythonw bridge treated as stub |
| **Status** | `fixed` (0.3.68) |
| **Acceptance** | `tests/test_watchdog_lifecycle_contract.py`, `tests/test_mcp_restore.py` |
| **Owner** | `mcp_restore.py`, `daemon.py` |

### R13 — Engine stays up with no clients

| | |
|--|--|
| **Symptom** | GPU/RAM held after Cursor close |
| **Root cause** | Sticky desired_run / debounce |
| **Status** | `fixed/partial` — disconnect unload works; keep idle tests green |
| **Acceptance** | `tests/test_lifecycle_disconnect_unload.py`, `tests/test_idle_no_clients_standby.py` |
| **Owner** | `lifecycle_runtime.py`, `mcp_lifecycle.py` |

---

## Priority board

| Pri | Items | Result (0.3.73) |
|-----|-------|-----------------|
| P0 | R1 cold contract, R8 ready honesty, R9 stamp | Done |
| P1 | R6 keeper defer, R11 registry retry | Done (R6 partial — measure p95 live later) |
| P2 | R7 pack SLA hints | Done (messaging); speed still open |
| P3 | R5/R10 process UX docs | Done |

**Do not touch:** leave/unregister/idle disconnect unload unless regression.

---

## Verification log

| Date | Check | Result |
|------|-------|--------|
| 2026-09-12 | Cold listen ~3.1s; FastEmbed ~1.3–1.6s; first map ~5.3s (0.3.72) | PASS partial R1 |
| 2026-09-12 | Warm maps 15.2s / 1.4s / 0.8s | FAIL R6 variance (pre P1) |
| 2026-09-12 | Pack multi-seed lean ~19.5s | OPEN R7 speed |
| 2026-09-12 | Process list all pythonw; no scubiee-mcp.exe | PASS partial R4 |
| 2026-09-12 | mcp.json build stamp still 0.3.71 after 0.3.72 install | FAIL R9 (pre fix) |
| 2026-09-12 | `_client_for` no force_restart (unit) | PASS R2 |
| 2026-09-12 | Watchdog skip auto load | PASS R3 |
| 2026-09-12 | Master doc written | PASS |
| 2026-09-12 | `pytest tests/test_reliability_master_plan.py` (+ warm/stamp) | PASS |
| 2026-09-12 | `python scripts/cold_start_acceptance.py` (stop→warm) ensure ~1.5s; first call 0.36s warming | PASS R1 |
| 2026-09-12 | Nonblocking warm skips open while health down | PASS R1 tighten |
| 2026-09-12 | `ensure_active_build_stamp` refreshes stale version (unit) | PASS R9 |
| 2026-09-12 | Registry PermissionError retry (unit) | PASS R11 |
| 2026-09-12 | Keeper tick/poll skip during locate_streak (unit) | PASS R6 partial |
| 2026-09-12 | R10 investigation: single spawn path bridge→locate; nested = display | by-design |
| 2026-09-12 | Unnoticed blink hot paths: daemon_python/netstat/DETACHED powershell/pip | FIXED 0.3.74 |
| 2026-09-12 | `pytest tests/test_console_blink_hotpaths.py` | PASS |
| 2026-09-12 | ~15s blink: heal→netstat every watchdog tick; schtasks Query on missing task | FIXED 0.3.75 |
| 2026-09-13 | Unit warm/lifecycle/lazy/reliability **69→49 core + full attach suite PASS** (0.3.79) | PASS |
| 2026-09-13 | `warm_contract_acceptance.py --no-stop` warm≤1.2s; map after idle ~0.3–0.6s | PASS |
| 2026-09-13 | `cold_start_acceptance.py --no-stop` first search 0.26s | PASS |
| 2026-09-13 | MCP stdio bridge full probe: map2 **142ms**, pack2 **348ms** after 5s idle; 6/6 checks | PASS |
| 2026-09-13 | First pack in fresh locate worker can still pay one AST hydrate (~wall seconds); steady stays ms | KNOWN |
| 2026-09-13 | **0.3.80** RuntimeController + httpx/tenacity; unit engine_http/runtime/attach/lazy/lifecycle **55 passed** | PASS |
| 2026-09-13 | **0.3.81** embed keepalive + keeper defer while clients; unit keepalive/keeper | PASS |
