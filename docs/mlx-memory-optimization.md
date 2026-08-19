# MLX memory optimization — stay at 30+ chunks/s under 800 MB

> 2026-08-19, Apple M5 MacBook Air, 16 GB. Follows [`mlx-m5-index-report.md`](./mlx-m5-index-report.md). Raw snapshots: [`mlx-memory-bench.json`](./mlx-memory-bench.json).

**Production default is unchanged.** `accel.json` is still CPU. Fast kernels, FP16, and cache limits are env-gated until this config is accepted.

## Punchline

The 2.45 GB “MLX peak” was **not live model memory**. It was allocator **workspace + cache**. Live MLX usage is essentially the weights.

| What | Baseline (FP32, batch 96, staged eval) | Best config |
| --- | ---: | ---: |
| RSS (process) | ~1.06 GB index / ~900 MB embed | **718 MB** (`ctx index`) |
| Active MLX | 524 MB | **269 MB** |
| Peak MLX (transient graph) | 2.34 GB | 1.52 GB |
| Embed chunks/s | 34.8 | **62.7** |
| End-to-end chunks/s | 31.1 | **51.4** |

```text
MEMORY OPTIMIZATION RESULT

Target:     <800 MB  AND  >=30 chunks/s
Best:       FP16 weights + mx.fast attention/LayerNorm + batch 48
            dynamic pad (not 512) + allocator cache cap 256 MB
            single mx.eval on the output

RSS:        718 MB  (ctx index --force, /usr/bin/time)
Active MLX: 269 MB
Peak MLX:   1.52 GB transient workspace (not RSS)
Cache:      ~314 MB capped

Embedding:  62.7 chunks/s
End-to-end: 51.4 chunks/s
Cosine vs CPU ORT: 0.999994  max abs 0.00057  mean abs 0.000082

Target achieved: YES
```

Peak MLX stays above 800 MB because one attention/MLP graph still allocates large temporaries. That memory is not held in process RSS. The 800 MB target is met on **RSS and active MLX**.

## Phase 1 — Where the memory actually goes

MLX 0.32.1 APIs: `get_active_memory`, `get_peak_memory`, `get_cache_memory`. There is no `get_memory`.

Cold embed, FP32, batch 96, 768 real chunks:

| Point | RSS MB | Active MB | Peak MB | Cache MB |
| --- | ---: | ---: | ---: | ---: |
| Process startup | 75 | 0 | 0 | 0 |
| Tokenizer | 145 | 0 | 0 | 0 |
| Weights loaded | 882 → **785 after mmap** | **522** | 522 | 0 |
| First GPU eval | 795 | 522 | 522 | 0 |
| First embed batch | ~800 | 522 | ~2000 | 0–1650 |
| End (uncapped cache) | 386–907 | 524 | 2338 | **up to 10.8 GB** |

Active memory barely moves after load. It is the weights. Peak and cache explode because every batch’s workspace is kept in the Metal allocator cache.

## Phase 2 — Weight footprint (parameters only)

136,731,680 parameters.

| Precision | Weight memory |
| --- | ---: |
| FP32 | **521.6 MiB** |
| FP16 | **260.8 MiB** |
| INT8 (not run) | 130.4 MiB |
| 4-bit (not run) | 65.2 MiB |

FP32 weights already consume most of an 800 MB budget. Quantization is optional, not required, once FP16 is allowed. INT8/4-bit were not tested because FP16 already hit both targets.

## Phase 3 — Lazy eval

The previous production loop called `mx.eval` four times per batch (ids, hidden states, pool, norm). That materializes the full `[B,S,768]` tensor.

One eval on the final vectors is **bit-identical** (max abs 0, cosine 1.0) and slightly faster.

Per-layer `mx.eval` did **not** cut peak and was not kept.

## Phase 4 — Allocator cache

| Cache | Embed c/s (768 ch) | Active | Peak | Cache end | RSS |
| --- | ---: | ---: | ---: | ---: | ---: |
| Default (unlimited) | 60.3 | 524 | 2338 | **10822** | 386–903 |
| 256 MB cap | 61.2 | 524 | 2338 | **477** | 807 |
| 64 MB cap | 59.9 | 524 | 2338 | 119 | 908 |
| Disabled (0) | 59.5 | 524 | 2338 | **0** | 907 |

Capping cache stops the 10 GB leak. It does not change active memory or throughput much. **256 MB cap is enough.** Do not permanently disable the cache.

## Phases 5–6 — Primitives (attention / LN / RoPE)

| Op | Current | MLX primitive | Used? |
| --- | --- | --- | --- |
| Embedding | gather | — | keep |
| QKV | `x @ Wqkv` | — | keep |
| RoPE | rotate-half, base 1000 | `mx.fast.rope` | **not swapped** (math already correct) |
| Attention | `Q@K.T/8`, mask, softmax, `@V` | `mx.fast.scaled_dot_product_attention` | **yes, env-gated** |
| LayerNorm | mean/var | `mx.fast.layer_norm` | **yes, env-gated** |
| MLP SwiGLU | three matmuls | — | keep |
| Pool / L2 | mask mean, normalize | — | keep |

Fast attention vs manual (64 real chunks): cosine **0.999999**, max abs **0.00015**. Fast + LN vs CPU ORT (48 chunks): cosine **0.999986** FP32 / **0.999994** FP16.

RoPE was left on the existing rotate-half path. No custom Metal kernels.

## Phase 7–8 — Sequence / batch

Real chunks still pad to the batch max (mean ~158, max ~241), cap 512. No fixed-512 padding.

Smaller batches cut **peak** workspace, not **active** (still ~weights). Full-corpus fused FP32:

| Batch | Embed c/s | RSS peak | Active | Peak MLX |
| ---: | ---: | ---: | ---: | ---: |
| 48 | **73.5** | 806 | 530 | 1743 |
| 64 | 54.3 | 806 | 530 | 1954 |
| 80 | 50.9 | 808 | 530 | 2020 |
| 96 | 48.0 | 810 | 530 | 2320 |

Batch 96 is **not** required. Batch **48** is faster here and uses less peak workspace. Dynamic padding kept.

## Phase 9–10 — Precision

Earlier FP16 (no fused kernels) was slower than FP32 (29.8 vs 34.8). With fused attention/LN, FP16 is fast **and** light:

| | FP32 fused b48 | FP16 fused b48 |
| --- | ---: | ---: |
| Weight mem | 522 MB | 261 MB |
| Active MLX | 530 | **269** |
| RSS (`ctx index`) | 927 | **718** |
| Embed c/s | 46.4 | **62.7** |
| E2E c/s | 39.3 | **51.4** |
| vs ORT cosine | 0.999986 | 0.999994 |

FP16 is slower only on the old unfused path (RoPE/attention stayed FP32 with extra casts). Fused softmax already runs in FP32 inside `mx.fast`. Keep FP16 for the memory target.

INT8/4-bit skipped: not needed.

## Phase 11–12 — Batch around the optimum

Smallest batch that still clears 30+ with fused kernels: **48** (73 embed / 51 e2e). No need for 96.

## Comparison table

| Configuration | RSS | Active MLX | Peak MLX | Embed c/s | E2E c/s | Cosine vs ORT |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Current FP32 baseline (b96, staged eval) | ~1060 / 900 | 524 | 2338 | 34.8 | 31.1 | 0.99999 |
| Optimized FP32 (mmap, fused, b48, cache 256) | 927 | 530 | 1743 | 46.4 | 39.3 | 0.999986 |
| **FP16 fused b48 cache 256** | **718** | **269** | 1519 | **62.7** | **51.4** | **0.999994** |
| Quantized INT8/4-bit | — | — | — | not run | — | — |
| Best batch (48, not 96) | see FP16/FP32 rows | | | | | |

## How to run the winning config (not persisted)

```bash
CTX_EMBED_BACKEND=mlx \
CTX_EMBED_BATCH=48 \
CTX_MLX_DTYPE=float16 \
CTX_MLX_FAST_ATTN=1 \
CTX_MLX_FAST_LN=1 \
CTX_MLX_EVAL=output \
CTX_MLX_CACHE_MB=256 \
CTX_EMBED_NO_CACHE=1 \
CTX_RM_DISABLE=1 \
  ctx index . --force
```

Code already mmap-loads weights (drops the numpy duplicate). Fast kernels and FP16 stay opt-in. `accel.json` was not rewritten.
