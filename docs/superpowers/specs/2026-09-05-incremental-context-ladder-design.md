# Design: Incremental Context Ladder (≤3 calls, lean tokens)

**Date:** 2026-09-05  
**Status:** approved — implementing

## Problem
One fat `pack_context` wastes tokens when the seed is wrong. Soft `map` at k=8 often buries the real seed. Agents need a **set of tools** that reach full understanding in **2–3 calls** with **minimal re-send**.

## Insight
Full context is **incremental disclosure**, not one oracle:
1. Locate seed cheaply (cards only)
2. Trace structure + few hottest bodies
3. Expand **delta only** if thin — never re-pack what was already sent

## Ladder (agent recipe)

| Call | Tool | Returns | Token posture |
|------|------|---------|---------------|
| 1 | `map(query, k=10)` | Slim cards + `role` + `suggested_seed` | Low |
| 2 | `pack_context(..., mode=lean)` | Slim heatmap + call `chain` + ≤N hottest bodies | Medium |
| 3 | `expand_context(node)` *(optional)* | Delta cards only; skip `packed_ids` | Low |

Same rich query on every step. Do not rematch vaguer.

## Product rules
- Soft map default **k=10**; demote `tests/` + `docs/` when `packages/` function cards exist.
- `suggested_seed`: best non-test function/method card (or null).
- Seed resolve: prefer `function`/`method`; refuse landing on `ROOT`/bare `const` when a covering def exists.
- `pack_context(mode=lean)`: default budget **6000** chars, **max_bodies=4**, emit compact `chain` (id + edge why), persist `packed_ids`.
- `mode=full`: previous behavior (budget 12000, more bodies) for when agent already has a trusted seed.
- Session `context_trace` remembers cards + `packed_ids`; expand never re-lists packed as bodies.

## Non-goals
- Replace Graphify with an external 30-tool MCP graph server.
- Teach soft map AST semantics (structure stays in pack/expand).
- Jedi/pyright resolution channel (follow-up spike).

## Success
On the 10-problem eval: ≥70% solvable in ≤3 calls with lean packs; mean packed chars down vs always-full without hurting file recall on strong seeds.
