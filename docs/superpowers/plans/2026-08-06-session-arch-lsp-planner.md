# Session Arch LSP + Planner Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add LspHop (real pyright) + Planner arms to session_arch A/B; run hard ladder; pick winner by rubric then tokens.

**Architecture:** Shared multishot+spans core; arms under `scripts/experiments/session_arch/`; pyright via stdio JSON-RPC; no production engine changes.

**Tech Stack:** Python 3, existing pipeline/conductor, `npx pyright-langserver`, existing mission ladder.

---

### Task 1: Pyright LSP client (experiment)

**Files:**
- Create: `scripts/experiments/session_arch/lsp_client.py`

**Steps:**
1. Implement `PyrightLsp` context manager: spawn `npx --yes pyright-langserver --stdio`, initialize, shutdown.
2. Methods: `definition(path, line, character)`, `references(path, line, character)`, `did_open`.
3. Parse Location / LocationLink → `(rel_path, line)`.
4. Soft-fail if spawn/init fails (`available=False`).

### Task 2: LspHop policy

**Files:**
- Create: `scripts/experiments/session_arch/lsp_hop.py`
- Modify: `scripts/experiments/session_arch/core.py` (add `lsp_calls` to `Ops` if needed)

**Steps:**
1. After seed spans, pick symbols via outline + query overlap.
2. Call definition + references; pack spans; BM25 confirm; distractor demote.
3. Memory/anchors same pattern as OutlineHop/GraphHop.

### Task 3: Planner policy

**Files:**
- Create: `scripts/experiments/session_arch/planner.py`

**Steps:**
1. Infer goal; budgeted loop calling graph and/or LSP helpers.
2. Stop when `must_open` satisfied or budget exhausted.
3. Count `planner_rounds` in ops or turn logs.

### Task 4: Wire A/B + run

**Files:**
- Modify: `scripts/experiments/session_arch_ab.py` — arms SeedSpan, GraphHop, LspHop, Planner; ladder default.
- Run: `--ladder` on frontend-mcp; write `session_arch_latest.json`.

**Done when:** Report shows rubric separation and winner (or explicit lsp_unavailable).
