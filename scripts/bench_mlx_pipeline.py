#!/usr/bin/env python3
"""Real-chunk MLX pipeline measurements: length distribution + batch sweep.

Uses existing Context Engine chunks (enriched text), not synthetic 512-token pads.
Does not rewrite accel.json.
"""

from __future__ import annotations

import json
import os
import resource
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

BATCHES = (8, 16, 20, 32, 48, 64, 96)
OUT = ROOT / "docs" / "mlx-pipeline-bench.json"


def _percentile(values: list[int], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    idx = (len(ordered) - 1) * (p / 100.0)
    lo = int(idx)
    hi = min(lo + 1, len(ordered) - 1)
    frac = idx - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def load_real_chunks(root: Path | None = None) -> list[str]:
    from pipeline.store import PipelineStore

    repo = (root or ROOT).resolve()
    store = PipelineStore(repo)
    records = store.load_chunks()
    if records:
        return [r.enriched for r in records]
    store_root = Path.home() / ".context-engine" / "projects"
    best: list[str] = []
    for path in store_root.glob("*/chunks.jsonl"):
        texts: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            texts.append(str(row.get("enriched") or row.get("text") or ""))
        if len(texts) > len(best):
            best = texts
    if not best:
        raise SystemExit("no Context Engine chunks.jsonl found; run ctx index first")
    return best


def token_lengths(texts: list[str]) -> list[int]:
    from pipeline.mlx_mac import load_coderank_tokenizer

    tok = load_coderank_tokenizer()
    tok.no_padding()
    tok.no_truncation()
    encoded = tok.encode_batch(list(texts))
    return [min(len(e.ids), 512) for e in encoded]


def distribution(lengths: list[int]) -> dict:
    buckets = {
        "le_128": sum(1 for n in lengths if n <= 128),
        "129_256": sum(1 for n in lengths if 129 <= n <= 256),
        "257_384": sum(1 for n in lengths if 257 <= n <= 384),
        "385_512": sum(1 for n in lengths if 385 <= n <= 512),
        "gt_512_after_trunc": sum(1 for n in lengths if n > 512),
    }
    return {
        "n": len(lengths),
        "min": min(lengths) if lengths else 0,
        "mean": float(statistics.fmean(lengths)) if lengths else 0.0,
        "p50": _percentile(lengths, 50),
        "p75": _percentile(lengths, 75),
        "p90": _percentile(lengths, 90),
        "p95": _percentile(lengths, 95),
        "p99": _percentile(lengths, 99),
        "max": max(lengths) if lengths else 0,
        "buckets": buckets,
        "total_content_tokens": int(sum(lengths)),
    }


def rss_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    # macOS ru_maxrss is bytes; Linux is kilobytes.
    if sys.platform == "darwin":
        return usage.ru_maxrss / (1024.0 * 1024.0)
    return usage.ru_maxrss / 1024.0


def sweep_batches(texts: list[str]) -> list[dict]:
    from pipeline.embedder import Embedder
    from pipeline.mlx_mac import mlx_peak_memory_bytes, mlx_reset_peak_memory, require_mlx_gpu

    report = require_mlx_gpu()
    os.environ["CTX_EMBED_BACKEND"] = "mlx"
    os.environ["CTX_EMBED_NO_CACHE"] = "1"
    os.environ["CTX_RM_DISABLE"] = "1"
    os.environ["CTX_MLX_DTYPE"] = "float32"
    embedder = Embedder(
        backend="mlx",
        batch_size=8,
        max_seq_length=512,
        cache_path=None,
        quiet=False,
    )
    embedder.embed_many(texts[:8])
    embedder.cache.clear()
    rows = []
    for bs in BATCHES:
        embedder.batch_size = int(bs)
        mlx_reset_peak_memory()
        t0 = time.perf_counter()
        vecs = embedder.embed_many(texts)
        wall = time.perf_counter() - t0
        stats = dict(embedder._last_stats)
        peak = mlx_peak_memory_bytes()
        row = {
            "batch": bs,
            "chunks": len(texts),
            "wall_s": round(wall, 3),
            "chunk_per_s": round(len(texts) / max(wall, 1e-6), 3),
            "tokens": stats.get("tokens"),
            "tok_per_s": stats.get("tok_per_s"),
            "timings_s": stats.get("timings_s"),
            "peak_mlx_bytes": peak,
            "rss_mb": round(rss_mb(), 1),
            "dim": int(vecs.shape[1]),
            "device": report.get("default_device"),
        }
        rows.append(row)
        print(
            f"[sweep] batch={bs} {row['chunk_per_s']:.2f} chunk/s "
            f"{row['tok_per_s']} tok/s wall={wall:.1f}s "
            f"peak_mlx={peak} rss_mb={row['rss_mb']}",
            flush=True,
        )
        del vecs
    return rows


def fp16_check(texts: list[str], batch: int) -> dict:
    from pipeline.embedder import Embedder

    sample = texts[: min(64, len(texts))]
    os.environ["CTX_EMBED_BACKEND"] = "mlx"
    os.environ["CTX_EMBED_NO_CACHE"] = "1"
    os.environ["CTX_RM_DISABLE"] = "1"
    os.environ["CTX_MLX_DTYPE"] = "float32"
    a = Embedder(backend="mlx", batch_size=batch, max_seq_length=512, cache_path=None, quiet=True)
    va = a.embed_many(sample)
    os.environ["CTX_MLX_DTYPE"] = "float16"
    b = Embedder(backend="mlx", batch_size=batch, max_seq_length=512, cache_path=None, quiet=True)
    vb = b.embed_many(sample)
    diff = np.abs(va - vb)
    cos = np.sum(va * vb, axis=1)
    return {
        "n": len(sample),
        "max_abs": float(diff.max()),
        "mean_abs": float(diff.mean()),
        "cosine_min": float(cos.min()),
        "cosine_mean": float(cos.mean()),
    }


def main() -> None:
    os.environ.setdefault("CTX_RM_DISABLE", "1")
    texts = load_real_chunks()
    print(f"[dist] loaded {len(texts)} real chunks", flush=True)
    lengths = token_lengths(texts)
    dist = distribution(lengths)
    print(json.dumps({"distribution": dist}, indent=2), flush=True)
    rows = sweep_batches(texts)
    winner = max(rows, key=lambda r: r["chunk_per_s"])
    print(f"[sweep] fastest batch={winner['batch']} at {winner['chunk_per_s']} chunk/s", flush=True)
    sim = fp16_check(texts, int(winner["batch"]))
    print(json.dumps({"fp16_vs_fp32": sim}, indent=2), flush=True)
    payload = {
        "distribution": dist,
        "batch_sweep": rows,
        "winner_batch": winner["batch"],
        "fp16_vs_fp32": sim,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
