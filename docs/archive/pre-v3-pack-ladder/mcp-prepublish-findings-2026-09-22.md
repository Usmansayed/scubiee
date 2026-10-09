# MCP findings before publish

Live ship tools on this repo, session `cursor@conn-450c20`, project `ce_7d597c1390dca6a1c5b8c4d661f421be`. The running uv tool is 0.3.106 plus a hand-copied prewarm overlay. Prewarm is not in the published wheel.

Fix the blockers in one pass, then publish as 0.3.107. Do not republish 0.3.106.

## Blockers

### 1. Default lean pack drops every score and the hot rows are wrong

`pack_context` with `mode=lean` (the default) returned `sc: 0.0` on every heatmap row. Hot was just the first four rows. For seed `packages/pipeline/context_trace.py::run_pack_context` those four were short helpers (`resolve_seed_node`, `build_call_chain`, `card_role`). The functions the ranker actually prefers were buried:

| rank | symbol | lines |
|---|---|---|
| 9 | `run_map_context` | 2358–2554 |
| 10 | `ensure_seeds_on_heatmap` | 1372–1460 |
| 11 | `run_collect_hot` | 3189–3308 |

The same seed with `include_bodies=1` kept the real scores and the real order:

| symbol | score |
|---|---|
| `run_pack_context` | 1.05 |
| `run_map_context` | 0.9902 |
| `resolve_seed_node` | 0.9901 |
| `run_collect_hot` | 0.9901 |

So composite ranking is fine. The lean formatter is not. `_format` runs lean twice: `attach_gate_lean` then `_dumps` → `apply_lean_fields`. The first pass stores `sc` and drops `score`. The second pass does `item.get("score") or 0`, so every `sc` becomes 0.0. `_pack_heatmap_only` also treats numeric 0 as a real value (`v not in (None, "")`), so a 0 can overwrite a real score, and “top 4 by score” then marks the wrong rows hot.

Expand and the body pack still show scores, because they do not go through `_heat_card`.

### 2. The first lean pack, while the in-process AST cache is cold, replays the last map

Status reported `ast_hydrated: false`. The next lean pack finished in 12.2ms and did not trace. Its heatmap was the previous map: two seeds, then `tests/test_composite_helper_rank.py`, `tests/test_composite_edge_prewarm.py`, and `docs/phase2-metadata-injection.md`.

That is `_lean_pack_fallback_heatmap` (`engine` tag `map_reuse`), used when `mode=lean`, bodies are off, and `ast_cache_ready` is false. It is silent: `ok: true`, `thin: false`. An agent will read tests and docs as the callees of `prewarm_pack_graph`.

After the cache was warm, a real trace was 20–33ms (`poly_ms` about 11). The fallback should not look like a successful structural pack.

### 3. `expand_context` does not see new symbols, and its callee list misses the pack neighbors

`expand_context` on `packages/pipeline/context_trace.py::prewarm_pack_graph` returned `unknown node`, with `hydrate_source: cache`. The function is on disk (lines 590–641) and map found it. The baked call graph has not picked it up.

Callees of `run_pack_context` (tracer used, 17ms) led with `card_role` and `refresh_node_from_disk`. `run_map_context` and `run_collect_hot` were not in the top 8. The body pack of the same seed leads with those two. Callers and effects were fine: callers start at `cli_pack`, effects are empty.

### 4. A bad `root` or `project_id` is ignored

`status` with `root=C:\Users\usman\Downloads\not-a-repo` and `project_id=ce_does_not_exist` returned `managed: true` for `C:\Users\usman\Downloads\context-engine` and gate `1:ce_7d597c1390dca6a1c5b8c4d661f421be`. An unenrolled folder should come back unmanaged.

## Fix in the same release

### 5. `prewarm_pack_graph` contains dead code, and it is not in the published wheel

The function returns at line 615. Lines 617–641 are the tail of `hydrate_ast_bundle` (`bake_on_miss`, `set_ast_hydrated`) pasted inside the function, so they never run. Map’s loc for this symbol is `590–751`, which also swallows the module-level `_SKIP_SEED_SYMBOLS` set. The live span is `590–641`.

Shipping prewarm means version 0.3.107, including `ensure_composite_edges` and `prewarm_pack_graph`. The uv tool overlay will be wiped by a normal install.

### 6. Body pack labels the best callees `cold`

`include_bodies=1`, `max_bodies=2`, `k=4` returned one body (the seed) and put `run_map_context` (0.9902) and `run_collect_hot` (0.9901) in `cold`. Cold here means “no body was collected,” not “low score.” Only one body came back though `max_bodies` was 2.

### 7. Map card order is not score order, and `k=12` returned 8 cards

Map for the prewarm query (915ms, dense) put a docs hit at rank 3 with score 3.37 ahead of test hits scored 23.7, 23.2, and 18.7. Requested `k=12`, got 8 cards. The top two seeds were right: `prewarm_pack_graph`, `ensure_composite_edges`.

### 8. Tool text still says broad pack is polytrace

`pack_context`’s `policy` description says `broad = one-shot polytrace escape`. Broad stays on composite and reports `composite_rerank`. The live broad pack did not show an engine name; it did show `escape_helped: false` and the same short-helper lean heatmap as strict.

### 9. One MCP process mixes chats

Gate warned that `cursor@conn-450c20` is shared. `workspace` show listed map queries from another chat in the same heatmap. Pins are per that shared session.

### 10. Health flags disagree

Full status: `agent_ready: stale`, `sync_state: syncing`, `ast_hydrated: false`, daemon healthy, embedder loaded, 7234 chunks. A later summary status: `agent_ready: yes`, `sync_state: ready`. Expand at the same time: AST `hydrate_source: cache`. `overlay_ready` stayed false while keeper dirty entries for `context_trace.py` and `composite_v1.py` were `published`.

## What already works

- Gate returns `1:ce_7d597c1390dca6a1c5b8c4d661f421be`.
- Map is dense and names the right seeds, with line spans.
- Warm composite trace is about 11ms (`poly_ms`), pack wall about 20–33ms.
- `include_bodies=1` chain order is the ranking fix: `run_map_context`, then `resolve_seed_node`, then `run_collect_hot`.
- `collect_hot_context` returned live source for `run_pack_context`, `run_map_context`, and `cli_pack`.
- `expand` accepts a heatmap id (`file::symbol`) and returns that span. An unknown handle is a clean error.
- Callers lead with `cli_pack`. Effects are empty.
- `workspace` pin of `packages/pipeline/context_trace.py` stuck.

## Not blockers

- Private helpers such as `_encode_batch` still share one demotion with tiny functions. Public callees still lead on the body pack.
- A fresh process that packs before prewarm finishes still pays about 0.8s to unpickle the AST bundle. That is the remaining floor, not the 6s edge build.
