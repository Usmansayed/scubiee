# 3-way compare: map-only vs map+heatmap vs native (seed-pick)

**Work prompt:** Improve map→pack seed selection (public packages/ defs; not empty cards / private helpers).

| Arm | Agent | Host tokens (k) | Chars ingested (self-report) | Ladder |
|---|---|---|---|---|
| Map-only | [e7589f89](e7589f89-7b9b-43b4-b1a1-80997285b5d7) | **~470** | ~28k | gate+map |
| Map+heatmap | [77b947a9](77b947a9-d901-4dbf-a8ba-dc4a85504028) | **~347** | ~22k | gate+map+pack(+expand) |
| Native (no Scubiee) | [379afd9b](379afd9b-bb22-4ea4-9a77-0463b0f8c22c) | **~506.7** | ~98k | Grep/Read only |

## Context quality

All three hit the **same island** and same fix sketch:
- `pick_suggested_seed` / `resolve_seed_node` / `_SKIP_SEED_SYMBOLS`
- CLI `cli_map` empty-symbol fabrication
- MCP soft hits → often `suggested_seed` null
- tests gap in `test_incremental_context_ladder.py`

| Extra evidence | Who |
|---|---|
| Live hot `_root` next to `cli_map` | Map+heatmap |
| Spec + `capability._public_symbols` + search hit shape depth | Native |
| Lowest host tokens so far | **Map+heatmap (~347k)** |

## Token takeaway

| vs | Map+heatmap (~347k) |
|---|---|
| vs map-only (~470k) | **~26% fewer** (~123k saved) |
| vs native (~506.7k) | **~31% fewer** (~160k saved) |

Map-only (~470k) still beat native (~506.7k) slightly. Heatmap pack was the clear winner on this prompt with matching context quality.
