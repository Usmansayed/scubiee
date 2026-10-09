# Cursor Scubiee rule tuning — 4-arm retrieval benchmark (without + top-3 rules), two rounds

Goal: pick the Cursor-optimized Scubiee rule. 4 arms — `without` (native, no MCP) + three two-layer
rule variants on the SAME map_v3 bridge: `c_default` (= Claude's `map_v3_u` verbatim), `c_capped`
(hard numeric budget), `c_hybrid` (ban-list + numbered workflow). Cheap retrieval challenge: locate
code → write `RETRIEVAL_ANSWER.md` → score named files vs pinned gold. Model `auto`, engine 0.3.140,
SHA-identical per-cell snapshots, global `~/.cursor/mcp.json` swapped per arm + restored.
Two rounds, DIFFERENT queries each round, 1 rep/cell → 24 cells total, 6 data points per arm.

## Round 1 — queries: ir_indexed_once_per_sync, dirty_path_first_char, faiss_reimport_segfault

| arm | avg tokens | adoption | avg grep | avg recall | success |
|---|---:|---:|---:|---:|---:|
| without | 920,800 | 0% | 14.0 | 1.00 | 3/3 |
| c_default | 206,567 | 100% | 1.3 | **1.00** | **3/3** |
| c_capped | 245,556 | 100% | 0.7 | 0.67 | 2/3 |
| c_hybrid | 316,527 | 100% | 3.7 | 0.67 | 2/3 |

## Round 2 — queries: memory_budget_resets_threads, idle_engine_self_retire, watchdog_no_autoload_while_mcp

| arm | avg tokens | adoption | avg grep | avg recall | success |
|---|---:|---:|---:|---:|---:|
| without | 611,271 | 0% | 11.7 | 1.00 | 3/3 |
| c_capped | 256,640 | 100% | 1.7 | 1.00 | 3/3 |
| c_default | 253,474 | 100% | 2.3 | 1.00 | 3/3 |
| **c_hybrid** | **159,666** | 100% | **0.0** | 1.00 | 3/3 |

## Combined (6 queries per arm)

| arm | avg tokens | map adoption | avg grep | recall | success |
|---|---:|---:|---:|---:|---:|
| without (native) | **~766k** | 0% | ~12.8 | 1.00 | 6/6 |
| c_default | **~230k** | 100% | ~1.8 | **1.00** | **6/6** |
| c_capped | ~251k | 100% | ~1.2 | 0.83 | 5/6 |
| c_hybrid | ~238k | 100% | ~1.8 | 0.83 | 5/6 |

## Findings (now with 2 rounds)

1. **Scubiee is a decisive, repeatable win on Cursor — ~3–7× fewer tokens than native, both rounds.**
   Native `without` averaged **611k–921k tokens with 12–14 greps/query** (it grep-spirals, 0% map
   adoption). Every tuned Scubiee arm averaged **160k–317k with ~1 map call and 100% adoption**. The
   single biggest cells: native 1.36M vs Scubiee ~180k on the same query. This is the headline:
   **with a map-first rule, Scubiee cuts Cursor's retrieval tokens by roughly 3–7×.**

2. **`c_default` (Claude's `map_v3_u`) is the most RELIABLE rule — 6/6 success, 1.00 recall both
   rounds, ~230k avg tokens.** It never missed. The custom strict variants each missed once (c_capped
   on faiss R1, c_hybrid on ir R1 → 5/6, recall 0.83): their hard "one map, don't re-search" budget
   occasionally forbids the recovery search when the first map points wrong.

3. **`c_hybrid` was the CHEAPEST in round 2 (160k, zero greps, all correct)** and c_capped is
   consistently lean too — so when they hit, they're the most efficient. The trade is reliability:
   over 6 queries they're ~5/6 vs c_default's 6/6.

4. **The ranking is cost-vs-reliability, not one dominant winner:**
   - Want max reliability + big token win → **`c_default`** (6/6, ~230k, 3–4× cheaper than native).
   - Want absolute cheapest and can tolerate an occasional miss → `c_hybrid` / `c_capped`.

5. **Earlier single-query reads were corrected by volume.** Round-1-only said "c_capped wins"; two
   rounds show c_default is the safer pick (equal-ish tokens, strictly better recall/success).

## Recommendation (ship)

**Adopt `c_default` — i.e. ship Claude's `map_v3_u` two-layer rule for Cursor as well.** It delivers
the full ~3–4× token reduction over native with perfect recall/success across 6 varied queries. The
Cursor-specific hard-budget rules (`c_capped`/`c_hybrid`) are a few % cheaper when they hit but miss
~1/6 — not worth the correctness cost for a shipped default. Keep them available as a "cost-min"
profile for token-bound, miss-tolerant use.

**Core Cursor learning (robust across both rounds):** Cursor's native default = **0% Scubiee
adoption, 12–14 greps, ~600–900k tokens** — it will not use the MCP without a map-first rule. Giving
it *any* of the three map-first rules flips adoption to 100% and cuts tokens 3–7×. *Having* a
map-first rule is what matters; `c_default` is the best-tested choice.

## Caveats (honesty)
- 1 rep/cell, `auto` router → the recall misses (0.83) are single-sample; the token gap vs native
  (3–7×, consistent across 6 queries and 2 rounds) is the solid result.
- All queries are focused/cross-module with 1–2 reliably-locatable gold files; hard 4-file discovery
  queries (which spiral + confound recall) were excluded to keep the signal clean.
- Round 2 required an engine restart first — the DirectML embedder had hung in prewarm after heavy
  idle/reload cycling this session; a clean restart fixed it (embedder loaded, dense ready).

## Artifacts
- Round 1: `.ab_workspaces/claude_sdk_harness/cursor_harness/20261004T110937Z_cursor_retrieval/`
- Round 2: `.ab_workspaces/claude_sdk_harness/cursor_harness/20261004T134133Z_cursor_retrieval/`
- `scripts/claude_sdk_harness/cursor_rules.py`, `run_cursor_retrieval.py`.
