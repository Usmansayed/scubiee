# Seeded PolyTrace vs EmbedPower

Gold context collected from the fixture (not from tracer output), stored in
`fixtures/trace-lab/seeded_prompts.json`. Each case gives **the same seed + prompt**
to both arms.

Run: `python -m trace_lab --seeded`

## Result (8 prompts)

| Arm | Mean F1 | Recall | FN | FP! | Wins |
|---|---|---|---|---|---|
| **PolyTrace (no embed)** | **0.958** | **1.000** | 0 | 2 | 2 |
| EmbedPower (CodeRank) | 0.929 | 0.979 | 1 | 2 | 0 |

Ties: 6/8 · Mean heatmap Jaccard: **0.922**

| id | Winner | Poly F1 | Embed F1 | Jaccard | Prompt |
|---|---|---|---|---|---|
| s01 | poly | 1.000 | 0.909 | 0.625 | credential check from authenticate |
| s02 | tie | 0.667 | 0.667 | 1.000 | token lifetime only |
| s03 | tie | 1.000 | 1.000 | 1.000 | pay cents |
| s04 | poly | 1.000 | 0.857 | 0.750 | emit → welcome handle |
| s05 | tie | 1.000 | 1.000 | 1.000 | worker → digest |
| s06 | tie | 1.000 | 1.000 | 1.000 | ok log line |
| s07 | tie | 1.000 | 1.000 | 1.000 | who reads TOKEN_TTL |
| s08 | tie | 1.000 | 1.000 | 1.000 | MemoryStore.fetch override |

## Takeaway

With the **seed given**, structure-only **PolyTrace is as strong or stronger** than EmbedPower.
Embeddings help most when the seed is unknown; once the seed is known, AST/LSP tracing wins.
