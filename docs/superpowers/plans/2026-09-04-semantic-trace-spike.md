# SemanticTrace spike — hard-50 scoreboard

**Goal:** structure + CodeRank semantics (no faction / keyword-intent tables).

## Pipeline (`packages/trace_lab/semantic_trace.py`)

1. Bidirectional AST+LSP expansion (calls / called_by / used_by / dispatch)
2. CodeRank query affinity + seed centroid
3. Contrastive goal score vs low-affinity distractor mass
4. Lexical+dense joint rerank (cross-encoder stand-in)
5. Keep bridges to semantic anchors; demote goal-opposing nodes below hot

## Hard-50 results (`python -m trace_lab --verify-hard`)

| arm | hard | acc | must-rec | prec | F1 | nDCG | must@10 |
|-----|------|-----|----------|------|-----|------|---------|
| polytrace | 14/50 | 0.28 | 0.82 | 0.85 | 0.80 | 0.96 | 0.80 |
| poly_embed | 13/50 | 0.26 | 0.82 | 0.85 | 0.79 | 0.96 | 0.79 |
| semantic_trace | 8/50 | 0.16 | 0.70 | 0.64 | 0.64 | 0.86 | 0.83 |
| embed_power_oracle | 5/50 | 0.10 | 0.68 | 0.86 | 0.73 | 0.94 | 0.73 |

Pre-prune spike (loose keep): semantic must-recall ~**0.94** / prec ~0.40 — proves embeds+bidirectional structure find related code; precision needs a trained reranker.

### Takeaways

- **Semantic expansion finds related code** — first spike hit ~0.94 must-recall before precision tightening.
- **Precision is the bottleneck** for hard-correct (narrow prompts like “pricing only”).
- Off-the-shelf CodeRank + lexical joint score is **not yet 95%**; next step is a
  **trained listwise/cross-encoder prune** on (prompt, must, must_not) pairs.

Scoreboard now prints: hard-correct, recall, precision, F1, nDCG, must@5/@10, inversions.

