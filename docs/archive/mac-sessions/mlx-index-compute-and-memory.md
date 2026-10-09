# Full traditional index: time, model compute, memory budgets

**Date:** 2026-08-19  
**Machine:** Apple M5 MacBook Air, 16 GB  
**Backend:** MLX FP16 CodeRankEmbed (`CTX_EMBED_BACKEND=mlx`, fused attn/LN)  
**Corpus:** this repo, 358 files → **2,946 chunks**

## Full first-style index (bootstrap budget, 800 MB cap)

Traditional path: scan → parse/graphify → chunk/enrich → embed → turboquant/FAISS.

| Phase | Time | Notes |
|-------|------|--------|
| Parse + IR | **3.5 s** | 358 files |
| Chunk + enrich | **4.2 s** | 2,946 chunks |
| **Embed (model)** | **35.2 s** | 83.6 chunks/s |
| Vector write | **0.20 s** | turboquant 8-bit |
| **Wall (end-to-end)** | **45.3 s** | 65.5 chunks/s |

Process RSS peak: **620 MB** (`/usr/bin/time` 650,412,032 bytes) — under the **800 MB** first-index cap.

## Model compute (the embedding GPU work)

This is what the **model** actually burned, not parse/chunk/IO:

| Compute | Value |
|---------|-------|
| GPU inference (`mlx_inference`) | **34.67 s** |
| Tokenization | 0.15 s |
| Batch prep (host→Metal) | 0.07 s |
| **Tokens processed** | **466,968** |
| **Tokens / s** | **13,258 tok/s** |
| Embed throughput | **83.6 chunks/s** |
| CPU time (whole process) | 10.7 s user + 13.7 s sys |
| Instructions retired | 3.10×10¹¹ |
| Cycles elapsed | 9.39×10¹⁰ |

Embedding is **~78% of wall time**. Almost all of that is Metal inference; tokenizer and FAISS are noise.

## Memory policy (macOS and Windows)

Same caps on Apple Silicon MLX and Windows DirectML. The process RSS budget is for **all of Context Engine** (parse + graph + chunks + model + FAISS), not just weights.

| Mode | When | RSS cap | Embed batch | MLX cache |
|------|------|---------|-------------|-----------|
| **Bootstrap** | first complete `ctx index` / `--force` full rebuild | **800 MB** | 48 (MLX) / calibrated (DML/CPU) | 256 MB |
| **Background** | incremental sync, live reindex, daemon | **560 MB** | 16 | 64 MB |

Implemented in `packages/pipeline/memory_budget.py`:

- Full index applies **bootstrap** (800 MB).
- `incremental_sync` applies **background** (560 MB).
- Resource manager halves batch if process RSS is ≥90% of the cap.
- Explicit `CTX_EMBED_BATCH` / `CTX_MLX_CACHE_MB` still win.

Windows: DirectML already uses batch 16 as the safe default. Background mode keeps that ceiling so the daemon stays under 560 MB. First index may use the calibrated DML batch up to the envelope ceiling, still targeting ≤800 MB RSS.

## Reproduce

```bash
CTX_EMBED_BACKEND=mlx CTX_MLX_DTYPE=float16 \
CTX_MLX_FAST_ATTN=1 CTX_MLX_FAST_LN=1 CTX_MLX_EVAL=output \
  ctx index . --force
```
