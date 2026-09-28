# Composite semantic Phase 0 bakeoff

Board: `verify_prod.json` (10 cases)

## Summary

| Arm | Acc | F1 | Must-rec | Prec |
|-----|-----|----|----------|------|
| `composite_v1` | 0.9 | 0.8732 | 0.9667 | 0.8351 |
| `composite_semantic_add` | 0.9 | 0.8732 | 0.9667 | 0.8351 |
| `composite_semantic_gate` | 0.9 | 0.8732 | 0.9667 | 0.8351 |

## Keep / kill

```json
{
  "composite_semantic_add": {
    "keep": false,
    "hard_up": false,
    "must_up": false,
    "f1_drop": 0.0,
    "prec_drop": 0.0
  },
  "composite_semantic_gate": {
    "keep": false,
    "hard_up": false,
    "must_up": false,
    "f1_drop": 0.0,
    "prec_drop": 0.0
  }
}
```

## Recommendation

Kill Phase 0 sensor for default use; neither add nor gate met keep/kill gate vs composite_v1. Keep code as experimental opt-in scaffolding for Phase 1.

### Notes

- Hot-set metrics (acc / F1 / must-rec / prec) are **identical** to `composite_v1` on this board — soft add (`α=0.15`) and gate did not move the hot threshold decisions.
- `composite_semantic_add` slightly lowered `must_at_5` (0.682 → 0.665); gate matched baseline ranking@5.
- Same failure case `p19` across all three arms.
- Next research bet: **Phase 1 teleport** (FN recovery), not stronger rank-only weights on this board.
