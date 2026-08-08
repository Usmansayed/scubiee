# Session arch + LSP + Planner (experiment design)

**Date:** 2026-08-06  
**Status:** approved (chat) — experiment only; no production engine default changes.

## Goal

A/B session traversal arms that share **multishot blind arrow + small spans**, then differ in navigation — including a **real pyright LSP** arm and a **Context Planner** loop — on hard related-session missions (`hard_hop_v1`, `harder_chain_v1`).

Winner: **rubric rate**, then **session tokens**.

## Arms

| Arm | Behavior |
|-----|----------|
| **SeedSpan** | Control: multishot → spans + light memory. No hops. |
| **GraphHop** | SeedSpan + budgeted `neighbor_files` + BM25 confirm. |
| **Planner** | Goal infer → budgeted rounds → **import-follow + ident BM25/grep + graph** → evaluate → stop. |

**LSP removed from default path** (2026-08-06 follow-up): import-follow + identifier BM25/grep replace pyright goto-def/refs. Optional `LspHop` may still exist as a legacy comparison arm but is not scored by default.

Standalone **OutlineHop** is **not** a scored arm (already lost prior ladder).

## Shared core

Reuse `scripts/experiments/session_arch/core.py`:

- `retrieve_multishot`, span pack (~500–700 chars), `SessionState`, this-turn `must_open` rubric, memory reopen.

## Planner (no LSP)

Coarse goals: `memory` | `wiring` | `locate` | `followup`.

Per turn budget: max **2** expand rounds; stop early if all `must_open` covered.

Tools (in order by goal):

1. **import-follow** — AST parse imports on seeds; resolve module → file; score by name/path overlap + BM25 confirm  
2. **ident BM25/grep** — outline/query identifiers → `class|def Ident` grep + BM25  
3. **graph** — `neighbor_files` + confirm (rewrite-enriched)

## Eval result (hard_hop_v1, no LSP)

| Arm | Rubric | Tokens |
|-----|--------|--------|
| **Planner** | **6/6** | ~7177 |
| SeedSpan | 3/6 | ~4302 |
| GraphHop | 3/6 | ~7741 |

Import-follow recovered H2 (`DispatchRegistry`) and H3 (`BrowserSessionManager`) without pyright.

## Non-goals

- No change to `packages/pipeline/engine.py` defaults.
- No production MCP wiring.
- LSP not required for planner v1.
