# Locate calibration — Phase A complete

**Corpus:** `docs/superpowers/plans/locate-calibration-corpus-v1.json`
**Cases:** 65 · **with gold:** 65

## Taxonomy counts

| Class | n |
|-------|---:|
| `soft_understand` | 49 |
| `exact_edit` | 9 |
| `literal_needle` | 3 |
| `rematerialize` | 2 |
| `known_seed` | 1 |
| `name_path` | 1 |

## Sources

- blind_map_pack_20 (+ GT)
- blind_multipack_20 (+ GT)
- kiro_mcp_ab simple + complex (gold files/symbols)
- personal3 + cursor A/B path trials
- calibration anchors (needle / name / known_seed)

## Next (Phase B)

Run offline arms per framework §4 with metrics `rounds`, `result_tokens`,
`total_proxy`, `must_*`, `under_use`/`over_use` — start with M1/M2 and N1
(density + over-use bounds) before Prefer/Require text experiments.

Human: spot-check taxonomy on ~10 soft vs exact_edit labels.
