# Map bakeoff + where embeddings still matter

## Experiment

28 vague prompts. Every arm: **map → pick seed(s) → PolyTrace** (structure only).

Dense = real CodeRankEmbed (FastEmbed/DML). Graph = BM25 reinforced by call-graph neighbors, or BM25-personalized PageRank.

Run: `python -m trace_lab --map-bakeoff`

## Results

```
arm                     F1  recall  seedOK
bm25                 0.714   0.738      22     ← WINNER
bm25_multiseed       0.679   1.000      22     (recall↑ precision↓)
graph_boost          0.679   0.702      21
hybrid (bm25+dense)  0.671   0.696      21
dense_multiseed      0.621   0.887      19
graph_ppr_multiseed  0.619   0.917      21
dense (CodeRank)     0.600   0.613      19
graph_ppr            0.589   0.619      21
```

### Verdict for *map / seed finding*

**Graph + BM25 does not beat plain BM25 here. Dense CodeRank does not beat BM25 either.**

On this fixture:

1. **BM25 alone is the best map** into PolyTrace.
2. Graph reinforcement / PPR slightly **hurts** (hubs get mass).
3. Multi-seed raises recall to ~1.0 but floods forbidden FPs — bad for “no more.”
4. Embeddings as the map channel **lose** to BM25 for landing a seed.

So for tracing: **BM25 map → PolyTrace** is enough. Whole-repo dense index is not buying the heatmap.

---

## Where embeddings *are* still needed (product Scubiee)

| Tool / surface | Needs dense? | Why |
|---|---|---|
| **PolyTrace / expand heatmap** | **No** | Structure (AST/LSP) after a seed |
| **map → seed for tracing** | **Usually no** | BM25 won this bakeoff |
| **`plate` (how-X-works)** | **Often yes** | Hubs can be semantically related with weak token overlap; product plate is BM25+dense+graph |
| **`pinpoint` soft edit** | **Sometimes** | “where should I change login expiry” vs exact symbol names |
| **Similar-code / “like this bug”** | **Yes** | Near-duplicate / analog retrieval is dense’s job |
| **Cross-language / comment-only concepts** | **Yes** | “rate limiting” with no `rate_limit` identifier |
| **Rerank when BM25 ties on `run`/`get`/`handle`** | **Useful** | Dense as top-k reranker, not full-corpus reason to embed |

### Rule of thumb

- **Tracing / context slice:** BM25 (optional) + **PolyTrace**. Skip dense.
- **Discovery / relatedness / soft locate:** keep dense in **`plate` / `pinpoint` / searcher`**, preferably as **rerank of BM25 candidates**, not as the only index of truth.

Dense indexing the whole repo is justified for Scubie’s *search/plate* product — **not** because tracing needs it on every file.
