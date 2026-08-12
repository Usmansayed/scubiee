# CBM–CE Hybrid Facade Implementation Plan

> **For agentic workers:** Implement task-by-task. Spec: `docs/superpowers/specs/2026-08-11-cbm-ce-hybrid-design.md`.

**Goal:** Python MCP facade `cbm-ce`: CE soft search + stock CBM graph tools via CLI proxy; trial arm + smoke.

**Architecture:** FastMCP server in `packages/hybrid_cbm/`; semantic via `pipeline` search; graph tools forwarded to `codebase-memory-mcp` binary (`cli` JSON args).

**Tech Stack:** Python, FastMCP, existing `pipeline.locate` / engine search, subprocess CBM CLI.

## Global Constraints

- Do not fork/patch CBM C sources in v1.
- Do not expose CBM semantic as a separate agent tool.
- Soft search thrash gate: reuse CE nav caps where applicable.
- Trial isolation vault rules unchanged.

---

### Task 1: Package + CE search + status

**Files:** `packages/hybrid_cbm/{__init__,instructions,semantic,server}.py`, `tests/test_hybrid_cbm.py`

- [x] Failing tests for instructions budget + search returns shape
- [x] Implement CE-backed `search` + `status`
- [x] `python -m hybrid_cbm` / `python -m hybrid_cbm.server` stdio entry

### Task 2: CBM proxy + graph tools

**Files:** `packages/hybrid_cbm/proxy.py`, extend server + tests

- [x] Mockable proxy interface
- [x] Proxy `search_graph`, `trace_path`, `get_code_snippet` (names from CBM tools/list)
- [x] Missing binary → clear error JSON

### Task 3: Trial arm `cbm_ce`

**Files:** `sdk_mcp_smoke.py`, `sdk_mcp_dev_trial.py`, preflight unfix

- [x] Arm config + rule
- [x] Preflight probes soft + one graph call when binary present

### Task 4: Smoke / small trial

- [x] Locate or install CBM binary
- [x] Index fixture + smoke
- [ ] Optional short sealed trial if binary + time allow
