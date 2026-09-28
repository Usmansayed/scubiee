# Compare: map-only vs map+heatmap (seed-pick collect)

**Work prompt:** Improve map→pack seed selection.

| | [Map-only](e7589f89-7b9b-43b4-b1a1-80997285b5d7) | [Map+heatmap](77b947a9-d901-4dbf-a8ba-dc4a85504028) |
|---|---|---|
| MCP | gate + map | gate + map + pack + expand |
| chars ingested | ~28k | **~22k** |
| map / pack payload | ~2.8k / — | ~2.3k / **~1.7k** |
| pack_calls | 0 | 1 |
| Same diagnosis? | yes | yes |

## What heatmap uniquely added

- Real locs for `cli_map` + `pick_suggested_seed`
- Live evidence: empty-symbol path → hot **`_root`** as neighbor (#2) — map-only could only infer this from code
- Expand delta empty; still needed Grep for `resolve_seed_node`

## Shared gaps

- MCP `suggested_seed` null (`role=other`)
- Need enrich cards + harden pick/resolve + tests

## Host tokens (user-reported)

| Arm | Tokens (k) | Agent |
|---|---|---|
| Map-only | ~470 | [Map-only](e7589f89-7b9b-43b4-b1a1-80997285b5d7) |
| Map+heatmap | **~347** | [Map+heatmap](77b947a9-d901-4dbf-a8ba-dc4a85504028) |
| Native (no Scubiee) | **~506.7** | [Native](379afd9b-bb22-4ea4-9a77-0463b0f8c22c) |

Full 3-way: `2026-09-06-three-way-seed-pick-compare.md`
