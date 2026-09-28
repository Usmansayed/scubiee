# EmbedPower — embeddings inside the tracer (2026-09-04)

## What "oracle" meant (and why it felt like cheating)

**oracle** = gold seed handed to PolyTrace. It only proves expansion works *after* you already know the start node. Product path never gets that gift.

## EmbedPower (new)

Embeddings are not a pre-step. They decide:

1. **Soft seeds** — relative peak `cos(query, node)` (CodeRank via FastEmbed/DML)
2. **Edge capacity** — `struct_w × (floor + (1-floor)·σ(affinity)) × coherence`
3. **Trusted frontier** — once accepted, callees keep a high floor so generic `decode`/`resolve` survive
4. **Hub contrast** — mean embedding of high-degree nodes; residual `aff − λ·hub` kills logger/http seeds
5. **LSP channels** — registry/inheritance still exist, capacity-gated

No path-faction tables and no synonym expand lists inside EmbedPower.

Cache: `fixtures/trace-lab/.embed_cache/coderank.jsonl`

## Wide board

**28** vague / adversarial prompts across **16+** families (auth, expiry, log-site, charge, events, jobs, isolation, refs, store, resolve, payment-with-auth-words, negation, underspec timeout, cors-by-behavior, mid-chain execute, inherit-by-description).

## Latest scores (`python -m trace_lab --vague`)

```
arm                    F1  recall  seedOK   FN  FP!
oracle (poly+gold)  0.964   1.000      28    0    2
embed_power_oracle  0.917   0.946      28    5    3   ← gold seed + embed gates
embed_power         0.759   0.780      28   22    2   ← NO gold seed (product-shaped)
bm25 map+poly       0.714   0.738      22   22    6
hybrid map+poly     0.696   0.726      21   23    6
hash-vector map     0.621   0.655      17   28    8
```

Family heatmap agreement (paraphrases):

| Arm | Jaccard |
|---|---|
| poly oracle | 1.00 |
| **embed_power** | **0.58** |
| hybrid map | 0.11 |

## Takeaway

- Real CodeRank embeddings **inside** the cut beat hashed-vector map and beat BM25 map on this 28-prompt board.
- End-to-end EmbedPower (~0.76 F1) is the honest number. Oracle PolyTrace (~0.96) is the expansion upper bound.
- Remaining gap is soft-seed ranking on underspecified prompts — next lever is FAISS over the whole repo index + multi-seed fusion with residual voting, not more path heuristics.
