#!/usr/bin/env python3
"""MLX memory / throughput experiments. Does not rewrite accel.json.

Examples:
  python scripts/bench_mlx_memory.py profile --eval staged --batch 96 --limit 768
  python scripts/bench_mlx_memory.py compare-eval --batch 96 --limit 768
  python scripts/bench_mlx_memory.py cache --batch 96 --limit 768
  python scripts/bench_mlx_memory.py grid --limit 384
  python scripts/bench_mlx_memory.py batches --eval output --cache-mb 256
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

OUT = ROOT / "docs" / "mlx-memory-bench.json"


def _load_texts(limit: int | None) -> list[str]:
    from pipeline.store import PipelineStore

    recs = PipelineStore(ROOT).load_chunks()
    texts = [r.enriched for r in recs]
    if not texts:
        raise SystemExit("no chunks; run ctx index first")
    if limit:
        texts = texts[: int(limit)]
    return texts


def _correctness(a: np.ndarray, b: np.ndarray) -> dict:
    diff = np.abs(a - b)
    cos = np.sum(a * b, axis=1)
    return {
        "n": int(a.shape[0]),
        "cosine_min": float(cos.min()),
        "cosine_mean": float(cos.mean()),
        "max_abs": float(diff.max()),
        "mean_abs": float(diff.mean()),
    }


def cmd_profile(args: argparse.Namespace) -> dict:
    from pipeline.mlx_mac import (
        CodeRankMLX,
        apply_mlx_cache_limit,
        load_coderank_tokenizer,
        mlx_memory_snapshot,
        mlx_reset_peak_memory,
        require_mlx_gpu,
        tokenize_batch,
    )

    os.environ["CTX_MLX_EVAL"] = args.eval
    snaps = []
    snaps.append(mlx_memory_snapshot("1_startup"))
    require_mlx_gpu()
    tok = load_coderank_tokenizer()
    snaps.append(mlx_memory_snapshot("2_tokenizer"))
    mlx_reset_peak_memory()
    if args.cache_mb is not None:
        apply_mlx_cache_limit(int(args.cache_mb) * 1024 * 1024)
    model = CodeRankMLX(dtype=args.dtype, require_gpu=True)
    snaps.append(mlx_memory_snapshot("3_weights_loaded"))
    texts = _load_texts(args.limit)
    bs = int(args.batch)
    first = texts[: min(bs, len(texts))]
    ids, mask = tokenize_batch(first, tokenizer=tok)
    import mlx.core as mx

    probe = mx.ones((8, 8))
    mx.eval(probe)
    snaps.append(mlx_memory_snapshot("4_first_gpu_eval"))
    mlx_reset_peak_memory()
    t0 = time.perf_counter()
    vec0 = model.embed_ids(ids, mask, eval_mode=args.eval)
    snaps.append(mlx_memory_snapshot("5_first_embed_batch"))
    n_batches = 0
    vecs = [vec0]
    start = min(bs, len(texts))
    while start < len(texts):
        batch = texts[start : start + bs]
        ids, mask = tokenize_batch(batch, tokenizer=tok)
        vecs.append(model.embed_ids(ids, mask, eval_mode=args.eval))
        n_batches += 1
        start += len(batch)
        done = start
        # first batch counted separately
        total_batches = 1 + n_batches
        if total_batches in {2, 5} or total_batches == 50 or total_batches == 100:
            snaps.append(mlx_memory_snapshot(f"batch_{total_batches}"))
        elif n_batches in {1, 4}:
            snaps.append(mlx_memory_snapshot(f"6_after_{total_batches}_batches"))
    wall = time.perf_counter() - t0
    snaps.append(mlx_memory_snapshot("9_end"))
    n = sum(v.shape[0] for v in vecs)
    peak = max(s["peak_mb"] for s in snaps)
    active_end = snaps[-1]["active_mb"]
    return {
        "mode": "profile",
        "eval": args.eval,
        "dtype": args.dtype,
        "batch": bs,
        "chunks": n,
        "wall_s": round(wall, 3),
        "chunk_per_s": round(n / max(wall, 1e-6), 3),
        "snapshots": snaps,
        "peak_mb": peak,
        "active_end_mb": active_end,
        "cache_end_mb": snaps[-1]["cache_mb"],
        "rss_end_mb": snaps[-1]["rss_mb"],
        "rss_peak_mb": snaps[-1]["rss_peak_mb"],
    }


def _run_embed(texts, *, batch, eval_mode, dtype, cache_mb) -> tuple[np.ndarray, dict, float]:
    from pipeline.mlx_mac import (
        CodeRankMLX,
        apply_mlx_cache_limit,
        load_coderank_tokenizer,
        mlx_memory_snapshot,
        mlx_reset_peak_memory,
        tokenize_batch,
    )

    if cache_mb is not None:
        apply_mlx_cache_limit(int(cache_mb) * 1024 * 1024)
    tok = load_coderank_tokenizer()
    model = CodeRankMLX(dtype=dtype, require_gpu=True)
    mlx_reset_peak_memory()
    t0 = time.perf_counter()
    parts = []
    for i in range(0, len(texts), batch):
        ids, mask = tokenize_batch(texts[i : i + batch], tokenizer=tok)
        parts.append(model.embed_ids(ids, mask, eval_mode=eval_mode))
    wall = time.perf_counter() - t0
    snap = mlx_memory_snapshot("end")
    return np.concatenate(parts, axis=0), snap, wall


def cmd_compare_eval(args: argparse.Namespace) -> dict:
    texts = _load_texts(args.limit)
    a, sa, wa = _run_embed(
        texts, batch=args.batch, eval_mode="staged", dtype="float32", cache_mb=args.cache_mb
    )
    # second run in same process is warmer; still useful for correctness
    b, sb, wb = _run_embed(
        texts, batch=args.batch, eval_mode="output", dtype="float32", cache_mb=args.cache_mb
    )
    return {
        "mode": "compare_eval",
        "chunks": len(texts),
        "batch": args.batch,
        "staged": {
            "wall_s": round(wa, 3),
            "chunk_per_s": round(len(texts) / max(wa, 1e-6), 3),
            "snap": sa,
        },
        "output": {
            "wall_s": round(wb, 3),
            "chunk_per_s": round(len(texts) / max(wb, 1e-6), 3),
            "snap": sb,
        },
        "correctness": _correctness(a, b),
    }


def cmd_cache(args: argparse.Namespace) -> dict:
    texts = _load_texts(args.limit)
    rows = []
    ref = None
    for cache_mb, name in ((None, "default"), (256, "cache_256mb"), (0, "cache_disabled")):
        vec, snap, wall = _run_embed(
            texts,
            batch=args.batch,
            eval_mode=args.eval,
            dtype="float32",
            cache_mb=cache_mb,
        )
        if ref is None:
            ref = vec
            corr = None
        else:
            corr = _correctness(ref, vec)
        rows.append(
            {
                "cache": name,
                "cache_mb_set": cache_mb,
                "wall_s": round(wall, 3),
                "chunk_per_s": round(len(texts) / max(wall, 1e-6), 3),
                "snap": snap,
                "correctness": corr,
            }
        )
        print(
            f"[cache] {name} {rows[-1]['chunk_per_s']:.2f} c/s "
            f"active={snap['active_mb']} peak={snap['peak_mb']} "
            f"cache={snap['cache_mb']} rss={snap['rss_mb']}",
            flush=True,
        )
    return {"mode": "cache", "batch": args.batch, "eval": args.eval, "rows": rows}


def cmd_grid(args: argparse.Namespace) -> dict:
    from pipeline.mlx_mac import (
        CodeRankMLX,
        apply_mlx_cache_limit,
        load_coderank_tokenizer,
        mlx_memory_snapshot,
        mlx_reset_peak_memory,
        tokenize_batch,
    )

    texts = _load_texts(None)
    tok = load_coderank_tokenizer()
    if args.cache_mb is not None:
        apply_mlx_cache_limit(int(args.cache_mb) * 1024 * 1024)
    model = CodeRankMLX(dtype="float32", require_gpu=True)
    seqs = (128, 256, 384, 512)
    batches = (32, 48, 64, 80, 96, 112, 128)
    rows = []
    for seq in seqs:
        # representative real texts, truncated/padded to fixed seq for this grid only
        for bs in batches:
            sample = texts[:bs]
            ids, mask = tokenize_batch(sample, tokenizer=tok, seq=seq)
            mlx_reset_peak_memory()
            t0 = time.perf_counter()
            model.embed_ids(ids, mask, eval_mode=args.eval)
            wall = time.perf_counter() - t0
            snap = mlx_memory_snapshot(f"b{bs}_s{seq}")
            row = {
                "batch": bs,
                "seq": seq,
                "chunk_per_s": round(bs / max(wall, 1e-6), 2),
                "active_mb": snap["active_mb"],
                "peak_mb": snap["peak_mb"],
                "cache_mb": snap["cache_mb"],
                "rss_mb": snap["rss_mb"],
            }
            rows.append(row)
            print(row, flush=True)
    return {"mode": "grid", "eval": args.eval, "rows": rows}


def cmd_batches(args: argparse.Namespace) -> dict:
    texts = _load_texts(args.limit)
    rows = []
    ref = None
    for bs in args.sizes:
        vec, snap, wall = _run_embed(
            texts,
            batch=int(bs),
            eval_mode=args.eval,
            dtype=args.dtype,
            cache_mb=args.cache_mb,
        )
        if ref is None:
            ref = vec
            corr = None
        else:
            n = min(len(ref), len(vec))
            corr = _correctness(ref[:n], vec[:n])
        row = {
            "batch": int(bs),
            "chunks": len(texts),
            "wall_s": round(wall, 3),
            "chunk_per_s": round(len(texts) / max(wall, 1e-6), 3),
            "tok_estimate": None,
            "snap": snap,
            "correctness": corr,
        }
        rows.append(row)
        print(
            f"[batch] {bs} {row['chunk_per_s']:.2f} c/s "
            f"active={snap['active_mb']} peak={snap['peak_mb']} "
            f"cache={snap['cache_mb']} rss={snap['rss_mb']}",
            flush=True,
        )
    return {
        "mode": "batches",
        "eval": args.eval,
        "dtype": args.dtype,
        "cache_mb": args.cache_mb,
        "rows": rows,
    }


def cmd_weights(_: argparse.Namespace) -> dict:
    from pipeline.mlx_mac import mlx_weights_path

    raw = np.load(mlx_weights_path())
    n = sum(np.asarray(raw[k]).size for k in raw.files)
    return {
        "params": int(n),
        "fp32_mb": round(n * 4 / (1024 * 1024), 2),
        "fp16_mb": round(n * 2 / (1024 * 1024), 2),
        "int8_mb": round(n * 1 / (1024 * 1024), 2),
        "int4_mb": round(n * 0.5 / (1024 * 1024), 2),
        "note": "parameter storage only; excludes activations, cache, Python, RSS",
    }


def main() -> None:
    os.environ.setdefault("CTX_RM_DISABLE", "1")
    os.environ.setdefault("CTX_EMBED_NO_CACHE", "1")
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp):
        sp.add_argument("--batch", type=int, default=96)
        sp.add_argument("--limit", type=int, default=768)
        sp.add_argument("--eval", default="staged")
        sp.add_argument("--dtype", default="float32")
        sp.add_argument("--cache-mb", type=int, default=None)
        sp.add_argument("--tag", default="")

    sp = sub.add_parser("profile")
    add_common(sp)
    sp = sub.add_parser("compare-eval")
    add_common(sp)
    sp = sub.add_parser("cache")
    add_common(sp)
    sp = sub.add_parser("grid")
    add_common(sp)
    sp = sub.add_parser("batches")
    add_common(sp)
    sp.add_argument("--sizes", nargs="+", type=int, default=[72, 80, 88, 96, 104, 112, 120, 128])
    sub.add_parser("weights")

    args = p.parse_args()
    fn = {
        "profile": cmd_profile,
        "compare-eval": cmd_compare_eval,
        "cache": cmd_cache,
        "grid": cmd_grid,
        "batches": cmd_batches,
        "weights": cmd_weights,
    }[args.cmd]
    result = fn(args)
    prev = {}
    if OUT.exists():
        try:
            prev = json.loads(OUT.read_text())
        except json.JSONDecodeError:
            prev = {}
    key = args.cmd.replace("-", "_")
    tag = getattr(args, "tag", "") or ""
    if tag:
        key = f"{key}_{tag}"
    prev[key] = result
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(prev, indent=2) + "\n")
    print(json.dumps(result, indent=2, default=str)[:4000], flush=True)
    print(f"wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
