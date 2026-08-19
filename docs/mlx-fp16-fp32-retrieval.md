# MLX FP32 vs FP16 retrieval eval (M5, this repo)

**Date:** 2026-08-19  
**Corpus:** `hidden-context-engine-` — 2,927 chunks  
**Queries:** 50 (35 soft NL, 15 hard symbol/confusable/multihop)  
**Script:** `scripts/eval_mlx_fp16_fp32_retrieval.py`  
**Raw JSON:** `docs/mlx-fp16-fp32-retrieval.json`

## Index configs

| Run | Env | Index wall |
|-----|-----|------------|
| **FP32** | `CTX_MLX_DTYPE=float32`, batch 96, eval=output, cache 256 MB | 45.9 s |
| **FP16** | `CTX_MLX_DTYPE=float16`, batch 48, fast attn/LN, eval=output, cache 256 MB | 46.3 s |

Each run: full `ctx index . --force` with `CTX_EMBED_BACKEND=mlx`, then immediate retrieval eval with matching query embedder dtype.

Retrieval: `WarmSearchEngine.search()` → `D_channel_best`, `CTX_CAPABILITY=off` (pure dense+BM25+graph path, no capability promotion).

## Headline: FP16 = FP32 for retrieval

| Metric | FP32 | FP16 | Δ |
|--------|------|------|---|
| **hit@8 overall** | 74.0% (37/50) | 74.0% (37/50) | 0 |
| **hit@5** | 72.0% | 72.0% | 0 |
| **hit@1** | 52.0% | 52.0% | 0 |
| **MRR** | 0.590 | 0.591 | +0.001 |
| **Per-query agreement** | — | — | **100%** |
| **Same top-1 file** | — | — | **100%** |

FP16 introduced **zero** retrieval regressions and **zero** improvements vs FP32 on this suite.

## Breakdown by difficulty

| Split | n | hit@8 FP32 | hit@8 FP16 | MRR FP32 | MRR FP16 |
|-------|---|------------|------------|----------|----------|
| **Soft** | 35 | 65.7% (23/35) | 65.7% | 0.466 | 0.466 |
| **Hard** | 15 | 93.3% (14/15) | 93.3% | 0.880 | 0.880 |

Hard queries (symbols, paths, confusables) retrieve reliably at both precisions. Soft NL queries dominate misses for both runs.

## Misses (identical for FP32 and FP16)

### Soft (12 misses)

| ID | Query (abbrev) | Expected |
|----|----------------|----------|
| soft04 | changed files since last index content hashes | merkle / freshness |
| soft06 | adaptive batch under memory pressure | resources |
| soft08 | capability cards soft locate | capability |
| soft09 | MCP map focus expand | mcp_locate / locate |
| soft15 | soft vs hard query classification | query_router |
| soft23 | incremental re-embed changed chunks | incremental |
| soft24 | vectors in named collections home dir | vectordb / store |
| soft26 | inject metadata into enriched chunks | enrich / indexer |
| soft27 | files touched in working session | work_session |
| soft30 | live reindex on file changes | live_reindex |
| soft31 | graph navigation outline neighbors | context_nav |
| soft34 | storage policy for index files | storage_policy |

These are **ground-truth / phrasing** gaps (BM25+dense ranked related test/docs files instead), not precision artifacts.

### Hard (1 miss)

| ID | Query | Expected | Notes |
|----|-------|----------|-------|
| hard04 | `scaled_dot_product_attention CTX_MLX_FAST_ATTN` | mlx_mac.py | Ranked docs/tests mentioning fast attn; symbol string not in top-8 |

## Conclusion

On CodeRankEmbed over this codebase:

1. **FP16 is retrieval-equivalent to FP32** — 100% query-level agreement, identical hit rates at @1/@5/@8.
2. **Safe to ship FP16** for production MLX indexing (matches prior cosine-sim sanity ~0.999994 vs CPU ORT).
3. **Soft-query recall (~66%)** is the quality ceiling to improve next — unrelated to dtype.

## Reproduce

```bash
~/venv/bin/python scripts/eval_mlx_fp16_fp32_retrieval.py --repo . --index
```
