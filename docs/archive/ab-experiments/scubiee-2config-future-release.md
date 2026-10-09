# 2-config map surface — DEFERRED to a future release (not in this ship)

## Decision (ship day, v0.3.140)
Ship the **4-config** map surface (`find | focus | related | graph`) that production already runs.
Do NOT convert to 2-config in this release.

## Why defer
- The production contract is built on 4 configs in multiple places that would all have to change
  together, on ship day: `pipeline/mcp_ship_check.py` (`SHIP_CONFIGS = {find,focus,related,graph}`),
  `map_v3_server.SERVER_INSTRUCTIONS` + tool description + schema enum, and the live acceptance
  scripts (`scripts/scubiee_mcp_ship_check.py`, `bug_bounty_update_surface`, production_test files).
- The 2-config win was measured on **harness bridges**, not the installed package, and was
  **neutral-to-slightly-better** (Kiro: equal-or-cheaper + lower variance; Cursor: token tie). It is
  a simplification, not a correctness or a large-cost win.
- Changing the shipped tool surface the same day we ship is exactly the high-blast-radius change to
  avoid. Low reward, real risk.

## What we learned (carry into the future-release change)
- `related` is near-dead in real usage (~2% of map calls across all sessions); `graph` ~5%.
  `find`+`focus` are ~92% of usage. A 2-config surface loses almost nothing.
- Best 2-config RULE (from the Kiro rule search): **k_2cfg_decomp** — the find|focus decision table
  PLUS query-decomposition discipline ("one target per query; known name → focus first; don't bundle
  two targets into one broad query"). It won the complex-task tiebreak (3.39 vs 4.04 credits, lower
  native_ops) and tied/led on the integration task. k_2cfg_lean (minimal) was weakest.
- The decomposition discipline was motivated by a diagnosed Cursor failure (a compound find query
  under-retrieved one of two targets → map lost trust → grep-walk). See
  `docs/scubiee-cursor-underadoption-diagnosis.md`.

## How to do the 2-config change when the time comes (checklist)
1. `map_v3_server.py`: `HANDLERS = {find, focus}` (drop related/graph or keep as hidden graceful
   fallbacks that degrade to find/focus so no legacy call hard-errors); update the tool
   `description`, the schema `enum`, and `SERVER_INSTRUCTIONS`.
2. `mcp_ship_check.py`: `SHIP_CONFIGS = {find, focus}`; update the ladder (drop the graph assertion
   or make it tolerate the fallback note).
3. Live scripts + production_test files that assert the 4-config ladder.
4. Ship the `k_2cfg_decomp` rule text in the connect rule/instructions.
5. Re-run the installed-package MCP smoke + ship ladder before releasing.
All of the harness-side variants (`map_v3_bridge_2cfg.py`, `k_2cfg*` rules, kab_2cfg* agents) remain
in `scripts/claude_sdk_harness/` as the validated reference implementation to port from.
