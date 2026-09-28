# Pack engines bakeoff: composite vs others

**Cases:** 8 (from blind20 triple-pack queries)
**Mode:** lean heatmap-only (`include_bodies=False`) — MCP default
**Same seed** per case from map → `pick_suggested_seed`

## Summary

| arm | engine | ok | mean ms | median ms | × vs composite | Jaccard vs composite |
|-----|--------|----|--------:|---------:|---------------:|---------------------:|
| `pack_context` | composite_v1 | 7/8 | 15068.1 | 14415.9 | 1.0 | 1.0 |
| `pack_context_broad` | polytrace | 7/8 | 14377.4 | 14266.3 | 0.95 | 0.929 |

## Verdict hints

- If Jaccard vs composite is high and other arms are slower → ship **pack_context + composite_v1** only.
- `pack_context_broad` is the polytrace escape hatch (policy=broad), not a second default.

Raw: `docs/superpowers/plans/2026-09-06-pack-vs-composite-bakeoff.json`
