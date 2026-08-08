# Session-Native Context Engine (beyond 3 search tools)

**Date:** 2026-08-08  
**Status:** implementing (Phase A–B landed in code)  
**Supersedes/extends:** `2026-08-08-tracelab-three-tool-context-engine-design.md`  
**KPI:** ≥**50%** cut in **retrieval-append tokens** (tool-result payload that becomes `newly_append_tokens`)

---

## 0. Hard numbers from 200 TraceLab sessions

| Fact | Value |
|---|---|
| Multi-turn (≥5 user msgs) | **195 / 200** |
| Locate+read share of tool calls | **46%** |
| Total tool `result_chars` | ~614M |
| P50 fraction of result chars that are **duplicate signatures** | **21%** |
| P90 duplicate fraction | **41%** |
| Near-duplicate read events | 33,176 |
| Large-unused result events | 5,537 |
| Naive stack (no re-send dups + skip near-dup reads + budget large unused) | **~68% of all result chars** |

Prefix cache is already strong in these traces. **The tax is append**, especially **re-sending the same retrieval** across a long session.

So: a perfect engine is not “better Grep”. It is a **session-native Context OS** that remembers what the agent already paid for.

---

## 1. Outside-the-box thesis

```text
TODAY (TraceLab agents)
  every turn → ls/rg/Read dumps → huge append → edit

TARGET
  turn 1 → map once → store spans in SESSION STORE (server)
         → LLM sees compact CARD + opaque HANDLES
  turn 2+ → focus/recall by handle → "unchanged" or DELTA only
         → expand(handle) only when editing that span
```

The LLM context window is the expensive medium. **Session store is cheap.**  
Anything already retrieved should live in the store and re-enter the prompt only as a **handle** (~20–40 tokens), not as a re-dump (~2k–10k tokens).

---

## 2. System architecture

```text
┌──────────────────────────────────────────────────────────┐
│                     AGENT (LLM)                          │
│  Tools: map | focus | workspace | recall | expand        │
└───────────────┬──────────────────────────────────────────┘
                │ compact JSON only
┌───────────────▼──────────────────────────────────────────┐
│              CONTEXT GOVERNOR                            │
│  - enforce budgets                                       │
│  - rewrite re-fetches → handle stubs                     │
│  - refuse oversized raw dumps                            │
└───────────────┬──────────────────────────────────────────┘
                │
     ┌──────────┼──────────┬─────────────────────┐
     ▼          ▼          ▼                     ▼
┌─────────┐ ┌────────┐ ┌───────────┐    ┌─────────────────┐
│ RETRIEVE│ │ SESSION│ │  LEDGER   │    │ HYBRID INDEX    │
│ map/    │ │ STORE  │ │ (what's   │    │ dense+BM25+     │
│ focus   │ │ spans  │ │ already   │    │ Graphify        │
│ workspace│ │facts  │ │ in prompt)│    │ (D_rerank)      │
└─────────┘ │pins   │ └───────────┘    └─────────────────┘
            │hashes │
            └────────┘
```

---

## 3. Tools to build (minimal set that can hit 50% without doubt)

Keep agent surface small. Five tools max; three are retrieval, two are session memory.

### A. Retrieval (use hybrid index)

| Tool | Job |
|---|---|
| **`map(query)`** | Cold start / new topic. One hybrid shot → card + **store spans** → return handles + tiny excerpts |
| **`focus(query\|path)`** | Follow-up / repair / deepen. Prefer hot zone; never full rediscovery |
| **`workspace(show\|pin\|clear)`** | Session heatmap + pins + subgraph (no bodies) |

### B. Session memory (the 50% unlock — currently underbuilt)

| Tool | Job |
|---|---|
| **`recall(need)`** | “What do we already know?” → list handles/pins/facts for this topic **without re-reading files** |
| **`expand(handle, max_chars?)`** | Materialize one stored span into the prompt **on demand** (edit time only) |

Optional internal (not agent-facing): **Governor** middleware on every tool response.

### Why this beats “just map/focus/workspace”

TraceLab follow-ups and multi-turn sessions (almost the whole sample) **re-pay** for context they already fetched.  
`recall` + handles make turn 2+ retrieval nearly free. That alone can clear the P50 **21%** dup tax; with budgets + near-dup suppression you clear past **50%**.

---

## 4. Session Store schema (persist under `.context-engine/`)

```json
{
  "session_id": "...",
  "topic": "current map query",
  "pins": ["path/a.py"],
  "heatmap": {"path/a.py": {"hits": 12, "last_ts": 0}},
  "spans": {
    "sp_01abc": {
      "path": "path/a.py",
      "start": 40,
      "end": 88,
      "content_hash": "sha256:...",
      "text": "...stored server-side, NOT re-sent...",
      "source": "dense|bm25|graph",
      "created_turn": 1,
      "last_served_turn": 1,
      "serve_count": 1
    }
  },
  "facts": [
    {"id": "fa_1", "text": "Auth lives in packages/x/auth.py", "handles": ["sp_01abc"]}
  ],
  "ledger": {
    "served_handles": ["sp_01abc"],
    "approx_prompt_tokens": 12000
  }
}
```

**Rules:**
- Tool results to the LLM include `handle`, `path`, `lines`, `why`, `hash`, **not** full `text` by default  
- `expand(handle)` returns text only if hash still matches file; else refresh once and update store  
- If agent asks `focus`/`map` that resolves to an existing hash → respond:

```json
{"status": "already_in_session", "handle": "sp_01abc", "path": "...", "lines": [40,88], "hint": "call expand only if you need the body again"}
```

Cost: ~30 tokens instead of ~3k.

---

## 5. Savings model (why 50% is not hand-wavy)

From the 200-session lever study (`session_savings_levers.json`):

| Lever | Mechanism | Share of result chars (order of mag.) |
|---|---|---|
| L1 Duplicate signature suppression | Session store + already_in_session stubs | ~21% median (up to 41% p90) |
| L2 Near-dup read elimination | `focus(path)` / handle instead of re-Read | large additional (33k events) |
| L3 Large-unused budgeting | map/focus return pointers; expand only if used | 5.5k events, very large tails |
| L4 Orient cascade removal | workspace/map once | smaller but removes whole tool rounds |
| L5 Hybrid one-shot vs rg loops | D_rerank map | fewer rounds + smaller payloads |

**Conservative stack for KPI:**
- L1 + half of L2 + strong L3 ≈ **≥50% retrieval-append** on multi-turn coding sessions  
- Naive upper bound if all applied fully ≈ **~68%** of result chars (overlapping, so treat as ceiling)

---

## 6. TraceLab workflow → tool playbooks (session-aware)

| Workflow | Playbook |
|---|---|
| **WF1 Cold start** | `map` → store spans → Edit from handles/`expand` → test |
| **WF2 Follow-up** | `recall` → `focus` only for **new** need → stub if known |
| **WF3 Repair** | `recall` hot pins → `focus(error symbols)` in zone → `expand` failing span |
| **WF4 Search-heavy** | Single richer `map` (still budgeted); forbid shell search for context |
| **WF5 Edit-heavy** | `workspace(pin)` + `expand` pinned handles only |
| **WF6 Multi-turn** | Every user steer starts with `recall`, not `map`, unless topic change |

---

## 7. Build plan (implementation order)

### Phase A — Session Context Store + Governor (highest ROI)
1. Persist spans/facts/ledger in `.context-engine/session_store.json`  
2. Wrap `map`/`focus` responses: store full text server-side; return handles + ≤N excerpt lines  
3. On repeat hit (same path+hash or same signature): return `already_in_session` stub  
4. Add tools **`recall`** + **`expand`**

### Phase B — Tighten retrieve (use full hybrid)
5. Ensure map/focus always go through D_rerank (dense+BM25+graph)  
6. `CTX_TOKEN_MODE=savings` budgets (excerpt caps, max_targets)  
7. Heatmap/pin bias in focus ranking  

### Phase C — Prove 50%
8. A/B harness: same tasks with Grep/Read baseline vs CE tools  
9. Metric: sum retrieval `result_chars` / append tokens; gate merge on ≥50%  

### Phase D — Agent contract
10. Cursor/MCP rule: context locate **only** via map/focus/workspace/recall/expand  
11. Bash/Grep allowed for **verify**, not for discovery  

---

## 8. What we will NOT do

- Train a model  
- Dump full files “to be safe”  
- Expose unbounded `search_code` as the primary agent path  
- Count prefix-cache hits as “our” savings  

---

## 9. Approval checkpoint

This is the research-backed shape for a **doubt-free 50%**:

1. **Session store + handles** (must-have)  
2. **recall / expand** (must-have)  
3. **map / focus / workspace** over D_rerank (must-have)  
4. **Governor budgets** (must-have)  
5. A/B measurement (must-have before claiming 50% in marketing)

Reply **approve** to implement Phase A→B next, or name changes (e.g. merge recall into workspace, drop expand, etc.).
