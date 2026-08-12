# CBM + Context Engine hybrid (Option A)

**Date:** 2026-08-11  
**Status:** design approved — implemented (v1 facade + trial arm `cbm_ce`)  
**Upstream:** [DeusData/codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) (local clone: `C:\Users\usman\Downloads\codebase-memory-mcp`)  
**Related:** sealed nav / thrash work in `docs/superpowers/specs/2026-08-10-sealed-retrieval-nav-design.md`

## 1. Problem

Context Engine’s soft search (CodeRankEmbed + FAISS) is strong at meaning locate but agents still thrash and burn tokens. CBM claims strong **graph** navigation (call paths, architecture, snippets) with far fewer tokens on structural questions, but its semantic path is a **bundled** Nomic embed compiled into C — not a plug for our stack.

We want CBM’s graph behavior **plus** our embedding/vector stack, without a deep C fork.

## 2. Goal

Ship a **hybrid MCP facade** that:

1. Uses **stock CBM** for structural tools (`search_graph`, `trace_path`, `get_code_snippet`, architecture, etc.).
2. Uses **CE** `embedder` + `vectordb` / `search_repo` (or engine `search`) for soft/semantic locate.
3. Presents **one** MCP server to the agent so tool choice is unambiguous.
4. Can be A/B’d in the existing SDK trial harness (fair isolation) on token + task-complete KPIs.

**Success (v1):** hybrid arm completes the thrash-style frontend task with **lower work_tokens** than CE-nav-only and **≥** task success vs raw, with seal-friendly locate (no native Grep/Glob/Read when sealed).

## 3. Non-goals (v1)

- Forking/patching CBM `semantic.c` or replacing its on-disk graph store.
- Replacing CE’s FAISS with CBM’s int8 vector index.
- Full rewrite of CE `nav` surface into CBM tools.
- Shipping a production install story for CBM binary (trial/dev path first).

## 4. Architecture

```text
Agent
  │
  ▼
cbm-ce MCP facade (Python, this repo)
  ├─ semantic / soft search ──► pipeline.embedder + vectordb / search_repo
  ├─ graph tools ─────────────► stdio JSON-RPC proxy → codebase-memory-mcp binary
  └─ short instructions ──────► soft→CE; structure→CBM; anti-thrash budgets
```

### 4.1 Facade tools (proposed v1 set)

Keep the surface small (≤8 tools):

| Tool | Backend | When |
|---|---|---|
| `search` | CE dense (+ existing fusion if cheap) | Soft / where|how|who |
| `search_graph` | CBM proxy | Symbol / structure patterns |
| `trace_path` (or CBM’s trace name) | CBM proxy | Callers/callees / paths |
| `get_code_snippet` | CBM proxy | Open known symbol once |
| `get_architecture` | CBM proxy | Orient (optional; may omit if noisy) |
| `status` | CE + CBM health | Health only |
| `recall` / `expand` | CE session_store | Optional; reuse CE anti-re-read |

Exact naming must match CBM’s `tools/list` for proxied tools (no rename that breaks schemas).

### 4.2 Indexing

Both indexes share the **same workspace root**:

1. **CE:** existing `pipeline index --fast` → FAISS collection for cwd.
2. **CBM:** CLI/MCP index for that project (their auto_index or explicit index command).

Trial harness creates the workspace, runs both indexes before the agent starts (or documents a warm-cache mode later).

### 4.3 Proxy mechanics

- Launch CBM as **stdio MCP subprocess** from the facade (same pattern as CE’s Stdio MCP in trials).
- Forward `tools/call` for allowlisted graph tools; strip/ignore CBM `semantic_query` usage in agent instructions (CE owns soft search).
- Map errors: if CBM down, facade `status` reports it; soft search still works.

### 4.4 Instructions (budget ≤600 tok)

Override host Grep/parallel defaults:

- Soft meaning → `search` (CE) ≤4; no duplicate queries (reuse CE thrash gate).
- Structure / “who calls” → CBM graph tools; then one snippet.
- Unchanged/already-in-session → stop re-read; edit early.
- Ban native Grep/Glob/Read when sealed.

## 5. Repo layout (v1)

Under context-engine (not inside the CBM clone as a submodule requirement):

- `packages/hybrid_cbm/` (or `packages/pipeline/cbm_facade/`)
  - `server.py` — FastMCP/stdio entry
  - `proxy.py` — CBM stdio client
  - `semantic.py` — CE search wiring
  - `instructions.py` — short always-on card
- Trial wiring: new arm `cbm_ce` in `sdk_mcp_smoke.py` / `sdk_mcp_dev_trial.py`
- Docs: this spec + short runbook note

CBM binary: install from release **or** build from local clone; path via `CBM_BIN` / `CTX_CBM_BIN`.

## 6. Testing

### Unit / smoke

- Facade lists expected tools.
- CE `search` returns hits against a tiny indexed fixture.
- Proxy forwards a mocked CBM `search_graph` response.
- Thrash gate still blocks duplicate soft searches.

### Trial

- Preflight: both indexes alive; soft search + one graph call.
- Arms: `cbm_ce` vs `raw` (optional third: `ce_nav`).
- Prompt: `thrash` (frontend profile), seal-locate, vault isolation.
- Timeout: enough to finish (~15–20 min agent), not 5 min cancel.
- KPIs: work_tokens, first_edit_step, pre/post_locate, seal_ok, work_complete, cross_arm_contamination=[].

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Agent calls both CE search and CBM semantic | Instructions + don’t expose CBM semantic as a separate tool; proxy only structural tools |
| Double index time | Parallelize CE+CBM index in harness; later warm-cache |
| CBM binary / Defender noise | Document path; prefer verified release; trial-only |
| Read thrash moves off search | Keep CE read dedupe + later read caps if KPIs still bad |
| Schema drift in CBM tools | Pin CBM version; generate allowlist from `tools/list` at startup |

## 8. Implementation order

1. Facade skeleton + CE `search` + `status`.
2. CBM stdio proxy for 2–3 graph tools.
3. Instructions + smoke tests.
4. Trial arm `cbm_ce` + preflight.
5. Small sealed rematch vs raw (and optional ce_nav).

## 9. Open points (decide during plan if needed)

- Exact proxied tool allowlist (minimal vs include `query_graph` / Cypher).
- Whether facade `read` is CE `read` or only CBM `get_code_snippet`.
- Windows path to CBM binary in CI vs local-only trials.
