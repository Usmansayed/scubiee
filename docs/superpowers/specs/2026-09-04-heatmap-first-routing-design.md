# GATE + MCP instructions — heatmap-first routing

**Date:** 2026-09-04  
**Status:** approved — applied 2026-09-04 (rules + card loc/rank/howto + hard-query + map soft split + local install)

## Goal

Agents treat the heatmap as a **ranked locate plan**: full path + line range + score tells them **where to Read/Grep first**.  
They may go wider only if that plan is insufficient — not by thrashing soft search first.

## Agent mental model (one sentence)

> `map_context` returns a scored map of *where the relevant code lives*; follow that map with native Read/Grep; expand or search further only if the map is thin or the answer is still missing.

---

## Heatmap card payload (full locate info + score)

Every card MUST be enough to open or search without a second locate tool.

```json
{
  "id": "pkg/auth.py::verify_token@120-180",
  "file": "packages/pipeline/auth.py",
  "symbol": "verify_token",
  "kind": "function",
  "start_line": 120,
  "end_line": 180,
  "loc": "packages/pipeline/auth.py:120-180",
  "score": 0.91,
  "heat": "hot",
  "rank": 1,
  "why": "call_from_seed+name_overlap",
  "path": ["seed_id", "...", "this_id"],
  "suggested": "read"
}
```

| Field | Why |
|-------|-----|
| `file`, `start_line`, `end_line`, `loc` | Exact place to Read |
| `symbol`, `kind` | Exact name to Grep / confirm |
| `score`, `heat`, `rank` | Priority — hot first, then warm |
| `why`, `path` | Trust / debug the hop |
| `suggested` | `read` for hot bodies; `grep` when you need call-sites / other mentions of that symbol |

**Response envelope** (every `map_context` / `expand_context`):

```text
howto:
  1. Work TOP-DOWN by score (hot → warm).
  2. Native-Read each card's loc (file:start-end). Prefer Read over dumping bodies.
  3. Native-Grep card symbols (and close variants) INSIDE those files / nearby dirs when you need call-sites or other mentions — the heatmap is your Grep plan, not a ban on Grep.
  4. If still missing a link → expand_context(hottest_or_seed_node, direction).
  5. Only if the map cannot help (no seed / wrong seed / still lost) → soft pinpoint/map/plate OR broader host Grep/Glob.
```

Do **not** strip location fields for “brevity.” Cards without loc+score are incomplete.

---

## Priority order (managed GATE 1)

| Priority | When | Action |
|----------|------|--------|
| **1** | Task/problem **and** a seed (file/symbol/chunk/path user named or agent already has) | **`map_context`** → follow cards (Read/Grep by score) |
| **2** | Map exists but thin / need one structural hop | **`expand_context`** → same follow-cards loop |
| **3** | Exact string / import / error / config key **and** you already know it is a literal hunt | **host Grep** (skip heatmap) |
| **4** | Filename / path pattern only | **host Glob** |
| **5** | Already know exact path+lines | **host Read** |
| **6** | Soft browse **with no seed** | `map` / `pinpoint` / `plate` |
| **7** | Session rematerialize | `workspace` / `expand(handle)` |

**Heatmap-guided Grep is allowed and recommended** after cards exist (step 3 in howto).  
**Blind** Grep/pinpoint/explore *before* heatmap is the anti-pattern when a seed exists.

`collect_hot_context` = rare escape hatch only.

---

## Proposed GATE body (`managed_gate_usage_short`)

Keep tight — always-applied rules. How-to detail lives in MCP instructions.

```text
**Use Scubiee for locate** when tools are available — follow this routing strictly:
- task/problem + seed (file/symbol/chunk) → USE `map_context` FIRST (relevance HEATMAP: each card = full loc + score). Then native Read/Grep those locations top-down by score. Prefer this BEFORE soft search/pinpoint/map/explore.
- need more of the same map → USE `expand_context` (delta cards; same follow-by-score loop). Broader Grep/Glob OK *after* the map if still missing.
- exact literal / import / error with NO seed hunt → host Grep. Filename → host Glob. Known path → host Read.
- soft browse with NO seed → `map` / `pinpoint` / `plate` as appropriate.
- session / rematerialize handle → `workspace` / `expand`.
**Native Grep/Glob/Read OK** after a heatmap (guided by cards), or when Scubiee MCP is down/blocked/paused/errors — continue; do not deadlock.
Avoid parallel explore thrash; one heatmap beat, then read/grep/edit.
Edit/Write/Shell stay native. How-to → Scubiee MCP server instructions.
```

---

## Proposed MCP header (`managed_gate_mcp_header`)

```text
Heatmap-first: task+seed → map_context (cards = loc+score) → native Read/Grep those spots by score; expand_context if thin; broader search only if still lost. Exact/name/path with no seed → host Grep/Glob/Read. No-seed soft → map/pinpoint/plate. Native OK if MCP down/errors.
```

---

## Proposed MCP hybrid body (`SERVER_INSTRUCTIONS_PHASE_HYBRID_BODY`)

```text
Scenario routing (follow strictly when tools are available):

HEATMAP-FIRST (default for understand/fix with a seed):
- USE map_context(query, seed_file, seed_symbol|seed_line, …).
  Returns GUIDE cards only (no bodies). Each card has: file, start_line, end_line, loc, symbol, kind, score, heat, rank, why, path.
- HOW TO USE THE HEATMAP:
  1) Sort/trust by score (hot first).
  2) Native-Read card.loc ranges — that is the primary open path.
  3) Native-Grep card.symbol (and tight variants) in those files/dirs when you need other mentions/call-sites — the heatmap tells you WHAT/WHERE to Grep; it does not forbid Grep.
  4) If the map is thin or a hop is missing → USE expand_context(node, direction) for more guide cards; repeat 1–3.
  5) If still insufficient → broader host Grep/Glob or soft pinpoint/map/plate. Do NOT start there when you had a seed.
- rare batch bodies → collect_hot_context(threshold). Prefer native Read.

EXCEPTIONS (skip heatmap):
- exact literal / import / error string as the whole task → host Grep.
- filename / path pattern only → host Glob.
- already know exact path → host Read.
- soft where/how/who with NO seed → pinpoint | plate | map (existing).
- session / rematerialize → workspace(show) / expand(handle).
- gate / status: managed / health (not locate).

One heatmap beat, then read/grep/edit. Avoid parallel explore for the same topic.
Shell = tests/build/git. Back off to classic: CTX_MCP_EXPERIMENT=classic.
```

Classic body: same heatmap howto block at top; keep focus/grep/glob lines below.

---

## Overview bullet (`managed_gate_overview_bullet`)

```text
**GATE 1:ce_*** (managed): task+seed → map_context heatmap (loc+score) then native Read/Grep those cards by score; expand_context if thin; broader search only if still lost. Exact/name/path → host Grep/Glob/Read. No-seed soft → map/pinpoint/plate. Native OK if MCP down/blocked/paused/errors. Edit/Write/Shell stay native. How-to → MCP server instructions.
```

---

## Tool description tweaks (MCP)

`map_context`:  
> Context TRACE guide: query+seed → ranked heatmap. Each card = full location (file:lines) + score + why. No bodies — native Read/Grep those locs top-down; expand_context if thin.

`expand_context`:  
> Grow the guide map from a node — more loc+score cards. Same follow-by-score Read/Grep loop.

---

## Files to update (after approval)

1. `packages/pipeline/context_trace.py` — add `loc`, `rank`, `suggested`; strengthen `guide`/`howto` on responses  
2. `packages/pipeline/rules_installer.py` — GATE short / MCP header / overview bullet  
3. `packages/pipeline/templates/scubiee.md` — overview GATE 1 line  
4. `packages/pipeline/mcp_locate.py` — SERVER_INSTRUCTIONS_* + tool descriptions  
5. Regenerate local `AGENTS.md`, `.cursor/rules/scubiee.mdc`, sibling rules via connect/rules install  

## Explicitly out of scope

- Changing polytrace scoring  
- Forcing `collect_hot_context`  
- Banning native Grep after heatmap (guided Grep is intended)
