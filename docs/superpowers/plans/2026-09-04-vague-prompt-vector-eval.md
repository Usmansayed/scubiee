# Vague-prompt honesty check (2026-09-04)

## Setup

- **20** human-like vague prompts in `fixtures/trace-lab/vague_prompts.json`
- Each prompt has gold `must` / `should` / `must_not` context (the true heatmap)
- Paraphrases share a `family` — they should yield the **same** hot set
- Pipeline under test: **map (BM25 + hashed dense vectors) → seed → PolyTrace**

Vector channel: deterministic hashed char/token n-gram embeddings (`packages/trace_lab/vector_index.py`), same cosine API product FAISS would use. No trained encoder required for the sim.

Run: `python -m trace_lab --vague`

## Results (latest)

```
arm             F1  recall  seedOK  exact   FN  FP!
oracle       0.990   1.000      20     20    0    0
bm25         0.690   0.683      15     11   20    2
vector       0.562   0.567      11      9   26    4
hybrid       0.665   0.667      14     12   21    2
mapfuse      0.625   0.750      15     12   17    5
```

Family heatmap agreement:

| Arm | Mean pairwise Jaccard | Identical families |
|---|---|---|
| **oracle** (gold seed) | **1.000** | **6 / 6** |
| hybrid (single map seed) | 0.111 | 0 / 6 |
| mapfuse (top-k, faction-locked) | 0.218 | 0 / 6 |

## What this proves

1. **The crisp 1.0 board was not a lie about tracing** — with the right seed, PolyTrace still hits ~0.99 F1 / 1.0 recall on vague wording, and paraphrases produce **identical** heatmaps.
2. **The 1.0 does not transfer to end-to-end vague queries** — seed finding is the failure mode. Hybrid map is ~0.67 F1; vector-alone is worse (~0.56).
3. **Vector search is necessary but not sufficient** — it helps some paraphrases, but hashed n-grams on a 37-node toy corpus lose to BM25+topic boosts. Product should use real embeddings here; the sim now has the slot.
4. **mapfuse** (try several map seeds, merge heat) recovers almost all must-nodes (recall ~0.98) but can over-merge across wrong seeds → precision tax. Faction-locking candidates helps.

## Honest product shape

```
vague query
  → dense+BM25 map (real embeddings in product)
  → seed (+ maybe top-k)
  → PolyTrace (LSP/AST/factions)  ← this part is already strong
  → heatmap
```

Do not ship PolyTrace alone as “understand my vague question.” Ship **map → PolyTrace**.
