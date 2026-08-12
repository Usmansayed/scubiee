# Research: one `search` tool — scenarios, waste, params

**Date:** 2026-08-11  
**Goal:** Before locking parameters, mine real agent sessions for *when* they need CE locate and *how* payloads waste context. Then propose ≤3 params with safe defaults + ≤500-token instructions.  
**Miner:** `scripts/experiments/mine_search_scenarios.py` → `docs/superpowers/specs/_search_scenario_mine.json`

## Evidence corpus

| Run / arm | Work tokens | Complete | MCP search | Notes |
|---|---:|---|---:|---|
| `214438Z` ce_search | 3.10M | yes | 60 | Fair vs nav; search-only |
| `214438Z` ce_nav | 7.81M | yes | 24 | +312 MCP reads |
| `f4133b…` ce_search | 0.51M | yes | 66 | Cheapest successful search-only |
| `175138Z` ce_nav | 4.84M | no | 162 | Exact thrash (120× mode=exact) |
| `191029Z` ce_nav | 8.26M | yes* | 16 | Read/expand thrash |
| `202752Z` cbm_ce | 4.53M | no | 1 | Hybrid; mostly shell later |
| raw arms | ~2.9–3.2M | mixed | 0 | Native Grep/Read only |

\*cancelled/ceiling variants omitted from design claims except as waste exemplars.

---

## Scenario catalog (what the agent actually asked for)

Queries classified from MCP `search` args across arms:

### S1 — Soft / meaning locate (dominant on successful search-only)
**Examples:** “where are perception MCP tools defined…”, “session evidence observe verify recall”, “env toggle … degraded envelope”  
**Need:** ranked *places* (file + lines + why), not full files.  
**Native gap:** Grep fails on paraphrase / intent.  
**Share:** majority of `ce_search` queries (`soft_meaning` ~42/60 and ~48/66).

### S2 — Structural / wiring intent
**Examples:** “…handlers and runtime **dispatch**”, “code **graph** … related files **neighbors**”, “who wires …” phrasing.  
**Need:** not just the def, but *callers / registration / neighbors*.  
**Native gap:** Grep finds the string; not 1-hop structure.  
**Share:** material (`structural` ~15/60 on search-only; ~6–21 on nav).  
**Failure mode today:** nav answers with dozens of MCP `read`/`expand` instead of one graph ribbon.

### S3 — Symbol / token probes
**Examples:** `CODEBASE_INTELLIGENCE`, `session_evidence`, short flags.  
**Need:** exact or near-exact.  
**Native gap:** none — **Grep is better**.  
**Waste:** `175138Z` ran **120× `mode=exact`**; nav later still mixes soft+exact duplicates.

### S4 — Open body to edit (post-locate)
**Not a search scenario** — but drives params.  
After `search`, next tool was:

| Arm | Next after search |
|---|---|
| ce_search | **another search 30**, native read 16, grep 10, glob 4 |
| ce_nav | MCP read 10, another search 8, files 5, expand 1 |

So the agent often **re-searches** instead of opening; when it opens, search-only uses **native Read**, nav uses **MCP read** (then re-reads).

### S5 — Map / inventory
Nav used `files` 27–36×. Search-only used native Glob.  
**Verdict for v1:** leave map to native Glob; don’t add a CE files mode into search.

---

## Context-waste patterns (why params must control payload)

1. **Duplicate queries** — search-only: 40 dup among 60; cheap run 44 among 66; nav sealed rematch 109 among 162. Same question pasted 2–3×.
2. **Fat defaults** — `fetch=true` on 24/60 searches in the 3.1M run → bodies for many hits in prompt. Cheap successful run used **fetch_true=0**.
3. **Knob thrash on `k`** — agents pick 5/8/10/15/20; larger k = more hit text. No quality signal that k=20 helped finish.
4. **Second-tool thrash** — MCP `read` 312× / 40 unique (272 dups) + ~89 unchanged stubs on nav. Separate locate tools *invite* re-fetch loops.
5. **Exact-as-Grep** — mode=exact floods tiny probes; burns budget without meaning locate.

**Design rule:** default response must be **skinny** (paths + lines + why). Fat payloads only when the agent *opts in*.

---

## What one tool must do that native can’t

| Capability | Native | CE `search` |
|---|---|---|
| Meaning / paraphrase locate | weak | **core** |
| Right span pointers (file:lines + why) | no | **core** |
| Optional bounded span body (top hits only) | Read whole file | **opt-in** |
| Optional 1-hop wiring ribbon on top hit | no | **opt-in graph** |
| Exact string hunt | **Grep** | do not own |
| Filename map | **Glob** | do not own |

---

## Proposed parameters (≤3, with defaults)

```text
search(query, include="hits", k=8)
```

| Param | Default | Allowed | Why it exists (from scenarios) |
|---|---|---|---|
| **`query`** | required | string | S1–S3: the only required intent |
| **`include`** | `"hits"` | `hits` \| `span` \| `graph` | Controls **payload fatness**: skim vs open vs wiring |
| **`k`** | `8` | int 3–12 (hard clamp) | Rarely need more; clamp stops 15/20 thrash |

### `include` semantics

- **`hits` (default):** `{file, start_line, end_line, score, why}` × k. Skim → native Read one path. Matches cheap successful runs.
- **`span`:** hits + bounded excerpt for **top 1–3 only** (not all k). For “I need to see code without a second tool” without pasting 8 bodies (`fetch=true` anti-pattern).
- **`graph`:** hits + **capped 1-hop** callers/callees for **top hit only** (S2). Not a neighbor browser; not expand/recall.

Server rules (not agent knobs):

- Duplicate normalized `query` → refuse / stub (thrash gate).  
- Soft search only (no `mode=exact` on this surface).  
- Ignore or clamp `k>12`.  
- Never attach span bodies for all k unless `include=span` (and still top‑N only).

---

## Instructions budget (≤500 tokens) — draft

```text
Context Engine = one locate tool: search(query, include="hits", k=8).
Ban Task/explore. Shell = tests/build/git. Exact strings → native Grep. Filenames → Glob.
Open a known path → native Read (one span). Do not Grep-first for "where/how/who".

WHEN to call search:
- Soft / unfamiliar / where|how|who|what handles X → search(query)  [include=hits]
- Need a short code peek on the best hits without opening files → include="span"
- Wiring / who calls / dispatch / neighbors of the best hit → include="graph"
- New topic mid-task → new query (do not repeat the same query)

include (default hits — keep prompts thin):
- hits  = file+lines+why only. Skim, then native Read the ONE file you will edit.
- span  = hits + bounded body for top 1–3 only. Not for every hit.
- graph = hits + capped 1-hop callers/callees on the top hit only.

k: default 8. Raise to 10 once if thin; never spray k>12.
Hard: ≤2 searches per topic, then edit. Duplicate query is blocked.
Trajectory: search → (optional span|graph once) → native Read once → edit → test.
```

(~320–380 tokens depending on tokenizer — under 500.)

---

## Alternatives considered

| Option | Reject | Why |
|---|---|---|
| `fetch: bool` | yes | Binary; agents set true often → 8 bodies |
| `mode: soft\|exact` | yes | Exact thrash in sealed runs |
| Auto-graph on structural regex | maybe later | Params give control; auto surprises + fattens default |
| Separate neighbors tool | yes | Proven thrash amplifier |

---

## Success criteria for a rematch

Same frontend thrash, arms: **new search-only** vs prior baseline mindset:

- work_tokens ≤ search-only median (~0.5–3.1M band), ideally closer to cheap run  
- `include=hits` is majority of calls  
- `include=span|graph` rare (≪20%)  
- dup query rate ≪ 50%  
- task complete + quality  

---

## Ask before implementation

Approve this param triad?

1. `query` (required)  
2. `include` ∈ {hits, span, graph} default **hits**  
3. `k` default **8**, clamp 3–12  

If yes → write formal design spec + plan and implement on the search surface only.
