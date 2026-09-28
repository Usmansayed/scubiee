# MCP Host Simulator Implementation Plan

> **For agentic workers:** Implement task-by-task. Spec: `docs/superpowers/specs/2026-09-13-mcp-host-sim-design.md`

**Goal:** Dual-lane MCP host sim (bridge stdio + Kiro) with SLAs: warm ≤30s, post-warm map/pack ≤1s, unload ≤10s after leave; plus lifecycle holds so cold attach cannot thrash.

**Architecture:** Product fixes first (leave-only unload + deferred register hold), then `packages/pipeline/mcp_host_sim/` + `scripts/mcp_host_sim.py`.

**Tech Stack:** Python, MCP JSON-RPC stdio, existing `server_entry` / lifecycle APIs.

## Status (2026-09-13)

Implemented:
- Leave-only unload + deferred local register hold
- `packages/pipeline/mcp_host_sim/` + `scripts/mcp_host_sim.py`
- Unit tests green (29)

Lane A live smoke (`--live --skip-idle`): harness works end-to-end; currently fails
`WARM_TIMEOUT` because cold probe map is ~36–40s (>30s SLA). That is the product
gap the sim is meant to catch — do not loosen the budget.
