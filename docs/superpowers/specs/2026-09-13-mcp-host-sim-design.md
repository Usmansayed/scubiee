# MCP Host Simulator — Design

**Date:** 2026-09-13  
**Status:** draft (awaiting implementation plan)  
**Package context:** Scubiee 0.3.84+  
**Related:** today’s cold-attach thrash (10s unload with `clients=0` before register), `scripts/kiro_mcp_reliability_probe.py`, `scripts/kiro_mcp_ab_dev_eval.py`, `docs/architecture/scubiee-reliability-issues.md`

## Goal

Build a **dual-lane** simulation that mimics real Kiro MCP start → warm → locate → idle → locate → stop → unload, with pass/fail SLAs tight enough to catch lifecycle thrash before wipe/install/reboot pain.

Fidelity target: **process-real** for daily gates; **host-real (Kiro CLI)** for the gold lane. Cursor UI automation is out of scope for v1.

## Product SLAs (source of truth)

| Event | Requirement |
|-------|-------------|
| Host (Kiro / bridge) starts | Auto warm begins immediately |
| Warm-up complete | `warm_ready` (embedder + soft search usable) ≤ **30s** from host start |
| After warm | **Every** `map` and `pack_context` (first and after any idle interval) ≤ **1s** |
| Host stops | Leave/unregister; engine + heavy RSS gone after **10s** disconnect debounce (±2s assert window) |

Hard fails while host is connected: `retire_self` / standby unload, `Connection closed` on locate, `active_clients=0` while host alive, unexpected second engine restart during warm.

## Approach (approved)

**Dual-lane simulator (option 3)**

| Lane | Mechanism | When |
|------|-----------|------|
| **A — Bridge host** | Spawn real `scubiee-mcp-bridge` + env from `server_entry`; MCP JSON-RPC over stdio | Default / CI |
| **B — Kiro host** | Real Kiro CLI session with Scubiee MCP enrolled | Nightly or `--kiro` |

Shared scenario runner + observatory + report. In-process unit tests remain for policy math only; they are **not** the fidelity bar.

## Isolation (approved)

| Mode | Behavior |
|------|----------|
| **Sandbox (default)** | Temp `CTX_HOME`, tiny fixture repo, dedicated engine port |
| **`--live`** | Real `~/.scubiee` + enrolled repo; **warn/abort** if another IDE MCP client is already attached |

## Canonical scenario: `kiro_cold_attach_steady_leave`

| Phase | Action | Pass criteria |
|-------|--------|----------------|
| 0 | Halt engine; assert sim port clear; clients empty | Clean slate |
| 1 | Host start (A: bridge + `initialize`; B: Kiro MCP session) | Process up |
| 2 | Poll auto-warm (`warm_ready` / embedder / soft_search); **no map yet** | ≤ 30s from host start |
| 3 | First `map` then first `pack_context` (lean; seeds from map) | Each ≤ 1s |
| 4 | Idle hold (default `--idle-s 120`); host stays connected | `clients > 0` entire time; no retire/standby |
| 5 | Post-idle `map` + `pack` | Each ≤ 1s |
| 6 | Host stop (clean leave / session end) | Leave OK |
| 7 | Unload wait | Engine process gone + RSS freed within 10s ± 2s |

### v1 extra scenarios (same runner)

- `reconnect_storm` — drop/reopen bridge twice in 5s; stay warm; no blink-kill  
- `double_host` — two bridge clients; one leave must not unload  

### Deferred (not v1)

- Lane C: full agent session replay / retrieval quality grading  
- Cursor UI automation  

## Components & layout

```text
packages/pipeline/mcp_host_sim/
  __init__.py
  observatory.py       # PID/RSS/clients/warm/health snapshots
  scenario.py          # phase runner + SLA assertions
  report.py            # JSON + markdown
  hosts/
    bridge_stdio.py    # Lane A
    kiro_cli.py        # Lane B
scripts/mcp_host_sim.py
```

**Reuse**

- `pipeline.mcp_install.server_entry` — exact bridge command/env  
- JSON-RPC patterns from `scripts/kiro_mcp_reliability_probe.py`  
- Kiro enrollment patterns from `scripts/kiro_mcp_ab_dev_eval.py`  
- Lifecycle observatory via `load_clients`, `load_policy`, `daemon.is_running`, engine log tail  

**CLI**

```bash
python scripts/mcp_host_sim.py --lane a
python scripts/mcp_host_sim.py --lane both --idle-s 120
python scripts/mcp_host_sim.py --lane b --live
```

Exit nonzero on any phase fail. Write:

- `docs/superpowers/plans/mcp-host-sim-<timestamp>.json`  
- matching `.md` summary  

## Observatory evidence (every phase)

Snapshot at least:

- engine running + pid + RSS  
- `active_clients` count + ids  
- `desired_mode`, `last_client_left_at`  
- `warm_ready` / `embedder_loaded` / `soft_search_ready` (best available surface)  
- HTTP health to sim engine URL  
- on fail: last ~40 lines of `engine.log`  

## Failure taxonomy

| Code | Meaning |
|------|---------|
| `WARM_TIMEOUT` | not warm_ready in 30s |
| `LOCATE_SLA` | map/pack >1s after warm |
| `THRASH_KILL` | retire/standby while host connected |
| `CONN_CLOSED` | MCP/engine pipe died mid-call |
| `UNLOAD_TIMEOUT` | engine still alive >12s after leave |
| `HOST_SETUP` | Kiro/bridge failed to start |

## Product changes required for SLAs (same ship)

The simulator will **fail until** these lifecycle bugs are fixed:

1. **Unload only after a real leave** — do not treat “0 clients + no `last_client_left_at`” with a 10s `last_activity` clock as disconnect unload (that kills CLI/init and deferred MCP attach).  
2. **Hold-warm on deferred attach** — if non-blocking ensure returns before `/health` is up, still register or stamp a hold so the 10s sweeper cannot `retire_self` mid-warm.  
3. **Attach warm ≤30s** — first locate after `warm_ready` must be ≤1s; cold DML cost belongs in phase 2, not phase 3.

These are product requirements discovered by the recent wipe/reboot incident; the sim makes them regressions.

## Rollout

1. Land product holds (1–3 above).  
2. Lane A green on sandbox against `kiro_cold_attach_steady_leave`.  
3. Enable Lane B via `--kiro`.  
4. Add reliability inventory row (e.g. **R11 — MCP host sim SLAs**) in `docs/architecture/scubiee-reliability-issues.md`.  
5. Later: session-replay lane C.

## Non-goals (v1)

- Grading map/pack *relevance*  
- Multi-repo / multi-project_id stress  
- macOS as primary (Windows first; Darwin best-effort)  
- Replacing unit tests for debounce math  

## Success definition

A green Lane A run on a cold machine (engine halted) proves: auto-warm ≤30s, post-warm locate ≤1s before and after 120s idle, unload ≤10s after leave, and no thrash while connected. Lane B proves the same under a real Kiro process tree.
