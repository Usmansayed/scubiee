# Verify-board: embeddings used properly + hard correctness



**Definition of correct (not mean-F1):** for each case,

`must ⊆ hot` AND `hot ∩ must_not = ∅`. Failures list `missing_must` / `forbidden_hot`.



**Board:** 20 cases, ≥15 families (auth, config, site-log, pay, events, jobs,

refs, inherit, cors, health, session, resolve, cache, notify, limits,

job-notify, adversarial-pay, login-entry, mid-execute, cache-get).



## Results (oracle seed + prompt → heatmap)



| arm | correct | accuracy | mean F1 |

|-----|---------|----------|---------|

| **polytrace** (structure only) | 20/20 | 1.00 | 0.996 |

| **poly_embed** (structure proposes, CodeRank prune/rerank) | 20/20 | 1.00 | 0.996 |

| embed_power_oracle (embeds drive walk) | 16/20 | 0.80 | 0.930 |



Failed embed_power cases: d01 (miss lookup), d02 (forbidden resolve/lookup),

d03 (miss log), d14 (miss http.get).



## How embeddings are used (PolyEmbed)



Wrong: dense affinity as edge capacity / primary walk → drops generics

(`decode`, `get`, `lookup`) and invents soft bridges into must_not.



Right:



1. PolyTrace proposes the island (AST + LSP + factions).

2. CodeRank scores each candidate vs the query.

3. **Site/config:** prune low-affinity flow tails (narrow heat).

4. **Flow/entry:** rerank only; do not veto hop≤3 structural bridges.

5. Always keep `HeatCell.path` + LSP dispatch/override for kept nodes.

6. Rescore with struct/affinity blend; kept cells stay above hot floor.



Embeddings help the heatmap as a **precision filter + ranker on a

structural proposal**, not as a substitute for tracing.


