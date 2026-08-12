# Sealed Retrieval Surface (`nav`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `CTX_MCP_SURFACE=nav` with tools `search | files | read | recall | expand | status`, &lt;300 tok instructions, and a sealed trial path that can beat native locate on success + tokens + thrash KPIs.

**Architecture:** New surface flag in `packages/pipeline/mcp_locate.py` wiring existing backends (hybrid search, grep, files glob, read/outline/neighbors, session_store recall/expand). Sync cursor rule + smoke staging. Extend SDK trial to ban/score native locate under seal.

**Tech Stack:** Python, FastMCP, existing `pipeline.ce_service` / `session_store`, pytest, `sdk_mcp_dev_trial.py`.

**Spec:** `docs/superpowers/specs/2026-08-10-sealed-retrieval-nav-design.md`

## Global Constraints

- Agent-facing tools exactly: search, files, read, recall, expand, status (no separate outline/grep/neighbors tools on `nav`)
- Server instructions &lt;300 tokens (~1200 chars); assert in tests
- Do not remove existing surfaces (`read`, `rich`, …)
- No commit unless user asks
- TDD: failing test → implement → pass per task
- Shell stays for tests/git; locate seal is Grep/Glob/Read (and shell rg/ls) only

## File map

| File | Responsibility |
|---|---|
| `packages/pipeline/mcp_locate.py` | Register `nav` surface, instructions, tool wiring, `search(mode=exact)`, `read(detail=…)`, expose recall/expand/files |
| `tests/test_mcp_locate.py` | Surface membership, instructions budget, mode/detail behavior |
| `.cursor/rules/context-agent.mdc` | Optional: only if local soft mode; sealed copy lives in trial staging |
| `scripts/experiments/sdk_mcp_smoke.py` | Stage `CONTEXT_ENGINE_NAV_RULE` / surface env |
| `scripts/experiments/sdk_mcp_dev_trial.py` | `--surface nav` + seal scoring (native locate penalty / ban) |
| `tests/test_sdk_mcp_dev_trial.py` | Harness flags for seal |
| `docs/context-engine-mcp.md` | Document `nav` surface |
| `docs/superpowers/specs/2026-08-10-retrieval-seal-completeness-r4.md` | Mark §4 approved |

---

### Task 1: Register `nav` surface + instruction budget test

**Files:**
- Modify: `packages/pipeline/mcp_locate.py`
- Modify: `tests/test_mcp_locate.py`

- [x] **Step 1: Write failing tests** for `_active_surface()` accepting `nav`, `SERVER_INSTRUCTIONS_NAV` length ≤ ~1200 chars / tok budget consistent with existing caps, and `status` tool list for nav = six tools.

- [x] **Step 2: Run tests — expect fail**

- [x] **Step 3: Implement** `SERVER_INSTRUCTIONS_NAV` (copy from design §4), add `"nav"` to `_SURFACES`, `_server_instructions`, and `status` tool_lists.

- [x] **Step 4: Run tests — expect pass**

- [ ] **Step 5: Commit** (only if user requested)

---

### Task 2: Wire `files`, `recall`, `expand` onto `nav`

**Files:**
- Modify: `packages/pipeline/mcp_locate.py`
- Modify: `tests/test_mcp_locate.py`

- [x] **Step 1: Failing tests** — when `CTX_MCP_SURFACE=nav`, registered tool names == `{search, files, read, recall, expand, status}` (not outline/grep/neighbors as top-level).

- [x] **Step 2: Run — expect fail**

- [x] **Step 3: Implement** — reuse `files_impl`; add thin `recall_impl` / `expand_impl` calling `session_store.recall` / `expand`; register only those six on `nav`. Keep rich/graph registrations unchanged.

- [x] **Step 4: Smoke call** each tool against a tiny fixture repo or existing locate tests — `ok: true` or validated error shape.

- [x] **Step 5: Tests pass**

---

### Task 3: `search(mode=exact)` + `read(detail=…)`

**Files:**
- Modify: `packages/pipeline/mcp_locate.py` (`search_impl`, `read_impl`, pydantic args)
- Modify: `tests/test_mcp_locate.py`

- [x] **Step 1: Failing tests**
  - `search(mode="exact")` returns grep-shaped hits (file/line/text), not semantic-only.
  - `read(detail="outline")` returns symbols without full body (or body empty/minimal).
  - `read(detail="neighbors")` equivalent to `neighbors=true`.
  - Default `mode=soft` / `detail=body` preserves current behavior.

- [x] **Step 2: Run — expect fail**

- [x] **Step 3: Implement** exact via existing `grep` client path; outline via `outline` client path inside `read`; map `detail` ↔ neighbors flag. Update tool descriptions for nav.

- [x] **Step 4: Tests pass**

---

### Task 4: Docs + cursor/smoke staging strings

**Files:**
- Modify: `docs/context-engine-mcp.md`
- Modify: `scripts/experiments/sdk_mcp_smoke.py` (NAV rule constant)
- Modify: `docs/superpowers/specs/2026-08-10-retrieval-seal-completeness-r4.md` (check approval boxes)
- Modify: `docs/superpowers/specs/2026-08-10-retrieval-trajectory-research.md` (R5 done when instructions land)

- [x] **Step 1: Document** `CTX_MCP_SURFACE=nav` and tool table.

- [x] **Step 2: Add** `CONTEXT_ENGINE_NAV_RULE` mirroring `SERVER_INSTRUCTIONS_NAV` for trial injection.

- [x] **Step 3: Mark** R4 §7 / research R5 instruction item complete when Task 1 instructions match design.

---

### Task 5: Sealed trial harness

**Files:**
- Modify: `scripts/experiments/sdk_mcp_dev_trial.py`
- Modify: `scripts/experiments/_run_trial_unrestricted.py` (if env plumbing)
- Modify: `tests/test_sdk_mcp_dev_trial.py`

- [x] **Step 1: Failing tests** for flags e.g. `--surface nav` / `--seal-locate` setting env `CTX_MCP_SURFACE=nav` and recording `native_locate_count`; seal mode treats native grep/glob/read as score violations (or blocks via rules text + post-hoc fail).

- [x] **Step 2: Implement** arm config: inject NAV instructions; set surface; extend scoring with thrash KPIs (`first_edit_step`, `pre_locate_calls`, `post_locate_calls`) already partially available via analyzers — wire into arm JSON summary.

- [x] **Step 3: Unit tests pass** (no full paid trial required in CI).

---

### Task 6: Local verification + optional rematch

**Files:** none (commands)

- [x] **Step 1: Unit suite**

```bash
.venv\Scripts\python.exe -m pytest tests/test_mcp_locate.py tests/test_sdk_mcp_dev_trial.py -q
```

- [ ] **Step 2: Optional sealed rematch** (when usage allows):

```bash
.venv\Scripts\python.exe scripts/experiments/sdk_mcp_dev_trial.py --prompt-id combo --arms ce_nav,raw --surface nav --seal-locate --model default
```

- [ ] **Step 3: Compare** to raw on KPIs in design §5; do not claim win on a single run.

---

## Done when

- [x] `CTX_MCP_SURFACE=nav` lists exactly six tools
- [x] Instructions under budget; anti-thrash lines present
- [x] exact search + outline/neighbors-via-detail covered by tests
- [x] Trial can run sealed and emit thrash KPIs
- [x] Design/research docs point at `nav` as approved sealed surface
