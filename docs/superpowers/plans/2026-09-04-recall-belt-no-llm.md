# Non-LLM recall belt — hard-50

**Goal:** hit ≥90% must-recall with BM25 / AST / LSP / Graphify / CodeRank only (no LLM).

## Results (`python -m trace_lab --verify-hard`)

| arm | hard | must-rec | prec | F1 | nDCG | @10 |
|-----|------|----------|------|----|------|-----|
| polytrace | 14/50 | 0.822 | **0.852** | **0.795** | 0.955 | 0.798 |
| poly_embed | 13/50 | 0.815 | 0.852 | 0.791 | 0.962 | 0.801 |
| semantic_trace | 8/50 | 0.696 | 0.642 | 0.644 | 0.857 | 0.829 |
| **recall_belt** | 0/50 | **1.000** | 0.101 | 0.181 | 0.735 | 0.568 |
| **recall_fuse** | 0/50 | **1.000** | 0.101 | 0.181 | **0.909** | **0.854** |
| embed_power_oracle | 5/50 | 0.682 | 0.858 | 0.726 | 0.942 | 0.731 |

## Verdict

- **≥90% must-rec is solved without an LLM** — wide bidirectional + Graphify island + hot floor → **100%** must-recall on all 50.
- Cost: precision collapses (~0.10) → hard-correct 0/50 (too much junk hot).
- `recall_fuse` keeps perfect recall and **better ranking** (nDCG 0.91, must@10 0.85) by merging polytrace scores.
- Next non-LLM lever for prec @ high rec: learned/listwise prune, hub fan-in prior, obligation paths — **not** another widen pass.

Code: `packages/trace_lab/recall_belt.py`  
Raw: `docs/superpowers/plans/verify-hard-recall-belt.json`
