# Scubiee 0.3.131 — production readiness (sync + MCP tools)

Date: 2026-09-26. Project: `ce_c505c4e65dbe5e2063a6c1089fe4db4e`. Engine: `http://127.0.0.1:8765`. Build: installed uv-tool **0.3.131** with DirectML.

## Verdict

**Ship for IDE use.** Hot-lane sync + ship MCP locate surface are good enough for production agent workflows on this machine. Ranking channels unchanged (`D_channel_best` / `composite_v1` / `multi_seed_v1`).

Sync is **working well**, not literally perfect under every load shape — see caveats.

## Sync evidence

| Evidence | Result |
| --- | --- |
| Kiro worklog probe (idle keeper, DirectML) | **10/10 ≤5 s** (p50 ~3.2 s, p95 ~4.4 s) |
| Live Cursor MCP `map` after dirty (new file) | Hit **rank 2**, `D_channel_best:dense`, correct token |
| Burst 10 new files (one dirty) | Files 0/4/9 visible dense rank 1 in **4.9 / 1.4 / 0.6 s** |
| Copy-paste ×3 identical bodies | Distinct paths all searchable; MCP `map` lists them as separate cards |
| Edited unique paste | Rank 1 in **5.7 s** (slightly over 5 s) |
| Sequential dirty ×3 | **3.3 / 3.4 / 7.2 s** — 3rd pays keeper queue |
| Mutate existing | New token visible dense rank 1 in **0.5 s** |
| Earlier scripted 10-trial under load | **3/10** within 5 s (queue / publish-visible races / one engine restart) |

### Caveats (known, acceptable for ship)

- Keeper is **single-threaded**: a save behind delete/bulk/cleanup can miss a strict 5 s wall.
- **Edits/deletes** still use full publish (BM25 rebuild); append-only hot patch is for **new-file** hot reasons.
- `CTX_KEEPER_DEFER_WHILE_CLIENTS=1` can delay sync while MCP clients are chatty.
- After `uv tool install --reinstall`, run `scubiee setup --repair --skip-model --skip-bench` to keep DirectML.
- Keep **one** install owning `~/.scubiee` (uv-tool vs Miniconda fights the daemon).

## MCP ship tools — response times

Measured via Lane A (`mcp_bridge` stdio, same binary as Cursor). Wall = host `tools/call` RTT. Raw JSON: `docs/mcp-tool-timing-0.3.131.json`.

| Tool | Wall ms (best measured) | Notes |
| --- | --- | --- |
| `gate` | **72** (warm) / 1710 (cold attach) | Session gate; tiny when warm |
| `status` | **431–489** | Health snapshot; `agent_ready=yes` when dense up |
| `map` (cold query) | **938–1533** (`elapsed_ms` ~870–1450) | Dense `D_channel_best` |
| `map` (repeat / cached) | **161** (`elapsed_ms` ~92) | Same query, warm cache |
| `pack_context` (lean) | **2080–2855** first success | May return `ast_warming` 1–2×; retry; then `elapsed_ms` ~190–300, `thin=false`, 16 heatmap cards |
| `expand_context` | **58–1244** | Delta cards; `elapsed_ms` often &lt;2 ms once hydrated |
| `collect_hot_context` | **43–96** | Bodies for ids / heatmap; ship lean returns `pack[].text` (no `handle`) |
| `workspace` show/pin/clear | **71–80** each | Mid-session pins / clear |
| `expand` (handle) | — | Needs a session **handle**; lean `collect_hot_context` returns bodies inline — use those or Native-Read locs |

Cursor live MCP `map` in this chat: **`elapsed_ms` 571** (hot sync query, dense+graph cards).

### Tool battery outcome

- **gate / status / map / pack_context / expand_context / collect_hot_context / workspace** — OK on warm engine.
- First `pack_context` after a fresh bridge often hits **`ast_warming`**; one or two retries (≤~10 s total) then succeeds.
- `expand` is optional on the ship ladder when collect already returned bodies.

## Operator checklist

```text
scubiee --version          # 0.3.131
scubiee engine ensure .
# health: version 0.3.131, warm_state ready, embedder_loaded true
# .cursor/mcp.json → pythonw -m pipeline.mcp_bridge (not cmd /c exit 0)
# Reload Scubiee MCP in Cursor after install/halt
```

Nothing in this note was committed or pushed.
