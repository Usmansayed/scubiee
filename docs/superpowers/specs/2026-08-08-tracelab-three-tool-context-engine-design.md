# TraceLab → Context Engine: 3-tool design

**Date:** 2026-08-08  
**Status:** proposed (awaiting approval to implement gaps)  
**Choice:** Hybrid **C** — agent sees **3 tools**; internals reuse **D_rerank = dense + BM25 + Graphify**  
**Token goal:** ~**50% reduction in retrieval-append tokens** (tool-result chars that become `newly_append_tokens`), not magic on already-cached prefix  
**Evidence base:** TraceLab v0.0.2 · 100 Claude + 100 Codex · `DETAILED_AGENT_WORKFLOWS.md`

---

## 1. What the research says agents do (and waste)

From real sessions, context collection is almost always:

```text
orient (ls/find/pwd) → search (rg/grep/find) → read (Read/cat/sed) → mutate → verify
```

Repeated across cold start, follow-ups, and repair. Failures:

| Observed thrash | Cost | Engine replacement |
|---|---|---|
| Orientation cascades (`ls`/`find`/`pwd`) | Many rounds, little signal | **`workspace` / `map` outline** |
| Shell search dumps (`rg`/`grep` huge `result_chars`) | Dominant append bloat | **`map` / `focus` budgeted hits** |
| Near-duplicate re-reads | Re-append same files | **`focus(path=…)` + pins** |
| Search loops before edit | Latency + tokens | One hybrid locate, then edit |
| Blind retries after error | More dumps | **`focus` in hot zone** not new Grep |

Opportunity means (structural): semantic locate ≈ 1.0, focus ≈ 1.0, result budgeting ≈ 0.95.

---

## 2. Recommended product shape (already started in-repo)

**Ship / harden the locate MCP as the only context-collection surface:**

| Tool | Replaces agent pattern | TraceLab workflow |
|---|---|---|
| **`map(query)`** | Cold-start `ls`→`rg`→many `Read` | WF1, WF4 |
| **`focus(query\|path)`** | Follow-up Grep/re-Read; repair re-search | WF2, WF3, WF5 |
| **`workspace(action=show\|pin\|clear)`** | Re-orient mid-session; remember hot files | WF2, WF6 |

Optional 4th: **`status`** (health only — not for retrieval).

**Do not** expose `search_code` + Grep + Glob as the primary path for coding agents using this engine. Native `Read`/`Edit` stay for mutation after pointers are known.

This matches `packages/pipeline/mcp_locate.py` + `packages/pipeline/locate.py` + D_rerank searcher.

```text
                    ┌─────────────────────────────────────┐
  User / LLM ask ──►│  map  |  focus  |  workspace        │  ← 3 tools
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │ locate() / work_session / snippet     │
                    └──────────────┬──────────────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
         Dense (FAISS)         BM25              Graphify
              └──────────── D_rerank merge ─────────────┘
                                   │
                         Budgeted card / spans
                         (pointers + short excerpts)
```

---

## 3. Tool contracts (research-shaped)

### 3.1 `map(query)` — cold start / new topic

**When (agent rule):** first ask on a topic; after topic change; never for “show me that file again”.

**Internally:**
1. D_rerank hybrid retrieve (`CTX_RETRIEVE=D`) — dense + BM25 + graph
2. Rank/diversify files (penalize `__init__`, distractors)
3. Pull **short excerpts** only (`excerpt_chars` default ≤ 800–1200 for savings mode)
4. Optional graph neighborhood under `graph_budget`
5. Touch work-session heatmap
6. Return JSON card: targets[{file, lines, why, score_sources}], excerpts, next hint

**Token policy (50% lever):**
- Default **savings mode**: `top_k≤10`, `max_targets≤5`, `excerpt_chars≤900`, hard cap `CTX_LOCATE_BUDGET≈12k` chars (~3k tok)
- Emit **pointers first**; full file only via later `focus(path=…)` or native Read of cited lines
- Distill LLM **off** by default (already)

**Replaces:** WF1 bootstrap + WF4 search-heavy locate loops.

### 3.2 `focus(query, path?)` — follow-up / repair / deepen

**When:** same topic; after error; “more of X”; mid-edit clarification.

**Internally:**
- If `path` set → bounded snippet (`max_chars`), touch heatmap — **no re-search**
- Else → D_rerank **biased to heatmap + pins** (smaller `top_k`, smaller graph budget)

**Token policy:**
- `max_targets≤3`, `excerpt_chars≤800`, snippet cap ≤2k chars
- Dedup: if signature of last returned span matches, return `{cached:true, pointer}` instead of re-dumping

**Replaces:** WF2 follow-up re-grep; WF3 repair widen; WF5 light re-read.

### 3.3 `workspace(action, path?)` — session brain

**When:** staying on a feature for hours; after several focuses; before another map.

**Actions:**
- `show` — heatmap + induced graph subgraph (no full file bodies)
- `pin` — mark hot file (WF5/WF6)
- `clear` — new task boundary

**Token policy:** paths + symbols + 1-line blurbs only; no file dumps.

**Replaces:** mid-session `ls`/`find` re-orientation (WF6).

---

## 4. How this hits ~50% token savings

**Definition:** compare **sum of retrieval tool `result_chars`** (and thus append tokens from tool results) in a coding session.

**Baseline (TraceLab):** agents append large shell/read dumps repeatedly.

**With 3 tools:**

| Lever | Mechanism | Expected cut of retrieval append |
|---|---|---|
| One hybrid locate vs N greps | Fewer tool rounds + smaller payloads | 15–25% |
| Excerpt budgets vs full files | Cap per target | 20–30% |
| Focus/pin vs re-read duplicates | Skip near-dup dumps | 10–20% |
| Workspace vs orient cascades | Almost free | 5–10% |

Stacked (not fully additive): **~40–60%** on retrieval-append is plausible; claim **50%** as the target KPI on a held-out agent A/B (same tasks, with/without CE tools).

**Not counted as savings:** prefix-cache hits on conversation history (already high in TraceLab). We optimize **append**, especially tool results.

---

## 5. Mapping TraceLab workflows → tool playbooks

| Workflow | Agent playbook |
|---|---|
| WF1 Cold start | `map(task)` → native Read cited spans → Edit → test |
| WF2 Follow-up | `workspace(show)` → `focus(delta)` or `focus(path=hot)` → Edit |
| WF3 Repair | `focus(error+symbol)` in hot zone → Edit → test; **no** new repo-wide Grep |
| WF4 Search-heavy | Single `map` with slightly higher `top_k`; forbid shell rg loops |
| WF5 Edit-heavy | `workspace(pin=…)` + `focus(path=…)` only |
| WF6 Multi-turn | Each user steer: `focus` not `map`, unless topic shift |

Cursor rule (already): *map first / workspace while hot / focus for small asks / no Grep rediscovery*.

---

## 6. Gaps vs current code (what to build)

Already exists: `mcp_locate.py`, `locate.py`, D_rerank searcher, `work_session`, graph touches.

**Implement next (priority order):**

1. **Savings-mode budgets** — env `CTX_TOKEN_MODE=savings|rich`; tighten defaults in `locate.py`  
2. **Heatmap-biased focus** — ensure focus mode truly upweights pinned/hot files in retrieve merge  
3. **Dedup / reopen** — return pointer-only if same path+line span served recently  
4. **Result card shape** — always include `token_estimate`, `sources: {dense,bm25,graph}`, `next` playbook string  
5. **Agent rule pack** — one short RULE.md / Cursor rule: only map|focus|workspace for locate  
6. **A/B harness** — replay or live tasks measuring retrieval `result_chars` / append tokens with vs without CE  
7. **(Optional)** merge `search_code` MCP into locate-only so agents can’t bypass budgets

Out of scope for this pass: training a model; replacing Edit/Bash for tests.

---

## 7. Success metrics

- Retrieval tool calls / session ↓ ≥ 40% vs Grep/Bash-search baseline  
- Mean retrieval `result_chars` / session ↓ ≥ **50%**  
- Time-to-first-edit ↓  
- Task success ≥ baseline (no quality regression)  
- Agents still reach correct files (hit@k on labeled tasks)

---

## 8. Approval

Recommended path: **approve this design → implement gaps 1–6 → measure KPI**.

Reply **approve** (or note changes). Implementation plan + code follows approval.
