# MLX CodeRank on the M5 — production index report

> 2026-08-19. Apple M5 MacBook Air, 16 GB. Companion notes: [`macbook-embed-speed.md`](./macbook-embed-speed.md). Raw numbers: [`mlx-pipeline-bench.json`](./mlx-pipeline-bench.json).

## Punchline

The real Context Engine indexing pipeline, with real chunks, can sustain **30+ chunks/s** on the M5 GPU through MLX.

| Path | Embed chunks/s | End-to-end chunks/s | Wall (`ctx index --force`) |
| --- | ---: | ---: | ---: |
| CPU FastEmbed (saved production) | 12.9 | 12.3 | 236 s |
| **MLX FP32, batch 96** | **34.8** | **31.1** | **93 s** |
| MLX FP16, batch 96 | 29.8 | 26.2 | 111 s |

MLX FP32 is about **2.7×** the CPU embed rate. `accel.json` was **not** switched; MLX is still an explicit overlay.

## What was measured

Not a synthetic 512-token bench. The workload was:

```text
this repo
  → existing file discovery
  → existing parser / chunker
  → existing embedding pipeline
  → MLX CodeRankEmbed on Metal
  → existing FAISS / TurboQuant write
```

Command:

```bash
CTX_EMBED_BACKEND=mlx CTX_EMBED_BATCH=96 CTX_EMBED_NO_CACHE=1 CTX_RM_DISABLE=1 \
  ctx index . --force
```

CPU comparison used the same command without `CTX_EMBED_BACKEND=mlx`, same chunking, same vector DB, cache disabled.

CodeRankEmbed was unchanged: same weights, tokenizer, RoPE, mean-pool, L2 normalize, dim 768. Max sequence length stayed 512. Each batch was padded only to `min(max(token lengths in batch), 512)`, not forced to 512.

## Hardware

```text
Apple Silicon:  Apple M5 (MacBook Air)
CPU:            10 cores (4 performance + 6 efficiency)
Memory:         16 GB unified
GPU:            Apple M5, Metal 4
MLX device:     Device(gpu, 0)
Metal:          true
```

The backend refuses CPU fallback. Startup logs:

```text
[embed] backend=mlx
[embed] device=gpu
[embed] metal=true
[embed] mlx_device=Device(gpu, 0)
```

## Real chunk lengths

The production chunks are much shorter than 512 tokens. On the 2,821-chunk corpus used for the length histogram:

```text
min  49
mean 158
p50  159
p75  174
p90  189
p95  196
p99  212
max  241
```

| Tokens | Chunks |
| --- | ---: |
| ≤128 | 334 |
| 129–256 | 2,487 |
| 257–384 | 0 |
| 385–512 | 0 |
| >512 after truncation | 0 |

Observed MLX batch widths were ~166–241 tokens. Padding every batch to 512 would have been wasted GPU work.

The later `ctx index` runs saw **2,904** chunks / **459,864** tokens (mean **158**) because MLX integration files were added to the repo. CPU and MLX were compared on that same 2,904-chunk snapshot.

## Batch-size sweep

Same real chunks, dynamic padding, MLX FP32. Sequential hot passes, so early sizes are pessimistic. Fastest stable size: **96**.

| Batch | Chunks/s | Content tok/s | Peak MLX memory |
| ---: | ---: | ---: | ---: |
| 8 | 19.5 | 3,084 | 1.96 GB |
| 16 | 15.6 | 2,461 | 2.22 GB |
| 20 | 18.6 | 2,930 | 2.16 GB |
| 32 | 20.2 | 3,192 | 2.00 GB |
| 48 | 27.2 | 4,300 | 1.98 GB |
| 64 | 23.1 | 3,649 | 2.07 GB |
| 96 | **28.4** | **4,476** | 2.45 GB |

A cold single `ctx index` at batch 96 then reached **34.8** embed chunks/s. No length bucketing was needed.

## Where the time went (MLX FP32 index)

Embed was 83.4 s of 93.5 s wall clock.

| Stage | Seconds | Share |
| --- | ---: | ---: |
| Tokenization | 0.45 | 0.5% of embed |
| Batch prep (host → MLX) | 0.01 | ~0% |
| **MLX inference** | **82.3** | **99% of embed, 88% of wall** |
| Pooling | 0.17 | 0.2% |
| Normalization | 0.04 | ~0% |
| Parse + IR | 3.3 | 3.5% of wall |
| Chunking | 3.9 | 4.2% of wall |
| Vector DB write | 0.46 | 0.5% of wall |
| Other (load / setup) | ~2.4 | 2.6% of wall |

The GPU is the embedding bottleneck. Tokenizer, pooling, FAISS, and the chunker are not. If the isolated model bench (~29.5 chunks/s on 256 chunks) and the full index disagree, believe the cold `ctx index`: it was faster, not slower.

## FP16

On 64 real chunks vs FP32:

```text
cosine min   0.999995
max abs err  0.00045
mean abs err 0.000079
```

That is inside the existing numerical tolerance. On the full index, FP16 used less RSS (~738 MB vs ~1.06 GB) but was **slower** (29.8 vs 34.8 embed chunks/s) because RoPE and attention still run in FP32. Do not switch production precision yet.

## Decision

```text
MLX production backend: YES
precision:              FP32
batch:                  96
persist accel.json:     no (not in this change)
```

Use MLX on this M5. It is the only path that clears 30+ chunks/s on the real indexer while keeping CodeRankEmbed and running on Metal.

CPU FastEmbed and CoreML were left in place. Enable MLX per process:

```bash
CTX_EMBED_BACKEND=mlx CTX_EMBED_BATCH=96 ctx index . --force
```
