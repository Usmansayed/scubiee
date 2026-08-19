#!/usr/bin/env python3
"""Side-by-side CPU ORT / CoreML ORT / MLX benchmark for CodeRankEmbed.

Does not change production accelerator selection.
"""

from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

BATCH = 20
SEQS = (128, 256, 384, 512)
RUNS = 3
BUCKETS = (128, 256, 384, 512)


def _median(times: list[float]) -> float:
    times = sorted(times)
    return times[len(times) // 2]


def _feeds(ids: np.ndarray, mask: np.ndarray, input_names: list[str]) -> dict[str, np.ndarray]:
    out = {}
    for name in input_names:
        if name == "input_ids":
            out[name] = ids
        elif "mask" in name:
            out[name] = mask
        else:
            out[name] = np.zeros_like(ids)
    return out


def _time_fn(fn, warmup: int = 1, runs: int = RUNS) -> float:
    for _ in range(warmup):
        fn()
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return _median(times)


def _metrics(ref: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    diff = np.abs(ref - pred)
    cos = np.sum(ref * pred, axis=-1)
    return {
        "max_abs": float(diff.max()),
        "mean_abs": float(diff.mean()),
        "cosine_min": float(cos.min()),
        "cosine_mean": float(cos.mean()),
    }


def _cpu_ref(onnx_path: Path, ids: np.ndarray, mask: np.ndarray) -> np.ndarray:
    import onnxruntime as ort
    from fastembed.common.utils import mean_pooling, normalize

    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    names = [i.name for i in sess.get_inputs()]
    token_emb = sess.run(None, _feeds(ids, mask, names))[0]
    return normalize(mean_pooling(token_emb, mask))


def _load_chunks(limit: int | None = 256) -> list[str]:
    store = Path.home() / ".context-engine" / "projects"
    paths = list(store.glob("*/chunks.jsonl")) if store.is_dir() else []
    texts: list[str] = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            texts.append(str(row.get("enriched") or row.get("text") or ""))
            if limit and len(texts) >= limit:
                return texts
    return texts


def _bucket(n: int) -> int:
    for seq in BUCKETS:
        if n <= seq:
            return seq
    return 512


def main() -> int:
    import onnxruntime as ort
    from fastembed.common.utils import mean_pooling, normalize

    from pipeline.accel import register_coderank, CODERANK_MODEL
    from pipeline.coreml_mac import (
        _fastembed_cache_root,
        coreml_provider_options,
        find_coderank_onnx,
        prepare_coderank_onnx_for_coreml,
    )
    from pipeline.mlx_mac import (
        CodeRankMLX,
        ensure_mlx_weights,
        mlx_device_report,
        tokenize_batch,
        load_coderank_tokenizer,
    )

    src = find_coderank_onnx(Path(_fastembed_cache_root()))
    if src is None:
        print("CodeRank ONNX missing", file=sys.stderr)
        return 1
    ensure_mlx_weights(src)
    device = mlx_device_report()
    print("MLX device:", json.dumps(device, indent=2), flush=True)
    if not device.get("gpu_compute"):
        print("WARNING: MLX is not on GPU", file=sys.stderr)

    tok = load_coderank_tokenizer()
    correctness_texts = [
        "hi",
        "def foo():\n    return 1\n",
        "class Repo:\n    def index(self, path: str) -> None:\n        print(path)\n",
        "x" * 400,
        "for i in range(32):\n    print(i * i)\n",
        "SELECT id FROM users WHERE active = 1;",
    ]
    ids, mask = tokenize_batch(correctness_texts, seq=128, tokenizer=tok)
    ref = _cpu_ref(src, ids, mask)
    mlx_f32 = CodeRankMLX(dtype="float32")
    mlx_pred = mlx_f32.embed_ids(ids, mask)
    mlx_f32.compile()
    mlx_compiled = mlx_f32.embed_ids_compiled(ids, mask)
    mlx_f16 = CodeRankMLX(dtype="float16")
    mlx_f16_pred = mlx_f16.embed_ids(ids, mask)
    correct = {
        "baseline": _metrics(ref, mlx_pred),
        "compiled": _metrics(ref, mlx_compiled),
        "float16": _metrics(ref, mlx_f16_pred),
    }
    print("\n=== Correctness vs CPU ORT (mean-pool + L2) ===", flush=True)
    print(json.dumps(correct, indent=2), flush=True)
    baseline_ok = (
        correct["baseline"]["cosine_min"] > 0.999
        and correct["baseline"]["max_abs"] < 5e-3
    )
    print("MLX baseline PASS" if baseline_ok else "MLX baseline FAIL", flush=True)

    opts = coreml_provider_options()
    rng = np.random.default_rng(0)
    print(
        f"\n=== Fixed-shape raw ORT vs MLX  batch={BATCH} ===",
        flush=True,
    )
    header = (
        f"{'seq':>5} {'cpu_c/s':>9} {'coreml_c/s':>11} {'mlx_c/s':>9} "
        f"{'mlx_opt_c/s':>12} {'cpu_t/s':>9} {'coreml_t/s':>11} {'mlx_t/s':>9}"
    )
    print(header, flush=True)
    fixed_rows = []
    cpu_sess = ort.InferenceSession(str(src), providers=["CPUExecutionProvider"])
    cpu_names = [i.name for i in cpu_sess.get_inputs()]
    mlx_opt = CodeRankMLX(dtype="float16")
    mlx_opt.compile()

    for seq in SEQS:
        ids = rng.integers(0, 100, size=(BATCH, seq), dtype=np.int64)
        mask = np.ones((BATCH, seq), dtype=np.int64)
        feeds = _feeds(ids, mask, cpu_names)
        cpu_s = _time_fn(lambda: cpu_sess.run(None, feeds))
        patched = prepare_coderank_onnx_for_coreml(src.parent, batch=BATCH, seq=seq)
        coreml = ort.InferenceSession(
            str(patched),
            providers=[("CoreMLExecutionProvider", opts)],
        )
        ml_s = _time_fn(lambda: coreml.run(None, feeds))
        mlx_s = _time_fn(lambda: mlx_f32.embed_ids(ids, mask))
        mlx_opt_s = _time_fn(lambda: mlx_opt.embed_ids_compiled(ids, mask))
        row = {
            "seq": seq,
            "cpu_s": cpu_s,
            "coreml_s": ml_s,
            "mlx_s": mlx_s,
            "mlx_opt_s": mlx_opt_s,
            "cpu_cs": BATCH / cpu_s,
            "coreml_cs": BATCH / ml_s,
            "mlx_cs": BATCH / mlx_s,
            "mlx_opt_cs": BATCH / mlx_opt_s,
            "cpu_ts": BATCH * seq / cpu_s,
            "coreml_ts": BATCH * seq / ml_s,
            "mlx_ts": BATCH * seq / mlx_s,
            "mlx_opt_ts": BATCH * seq / mlx_opt_s,
        }
        fixed_rows.append(row)
        print(
            f"{seq:5d} {row['cpu_cs']:9.2f} {row['coreml_cs']:11.2f} {row['mlx_cs']:9.2f} "
            f"{row['mlx_opt_cs']:12.2f} {row['cpu_ts']:9.0f} {row['coreml_ts']:11.0f} {row['mlx_ts']:9.0f}",
            flush=True,
        )

    texts = _load_chunks(limit=256)
    print(f"\n=== Production-like corpus: {len(texts)} chunks ===", flush=True)
    tok.enable_truncation(max_length=512)
    tok.no_padding()
    encoded = tok.encode_batch(texts)
    lengths = [int(sum(e.attention_mask)) for e in encoded]
    content_tokens = int(sum(lengths))
    print(
        f"content_tokens={content_tokens} mean_len={content_tokens/max(len(texts),1):.1f}",
        flush=True,
    )

    register_coderank()
    from fastembed import TextEmbedding

    # CPU FastEmbed — variable length, production path.
    cpu_fe = TextEmbedding(
        model_name=CODERANK_MODEL,
        threads=1,
        providers=["CPUExecutionProvider"],
        lazy_load=True,
    )
    list(cpu_fe.embed(texts[: min(16, len(texts))], batch_size=16, parallel=None))
    t0 = time.perf_counter()
    n = 0
    for _ in cpu_fe.embed(texts, batch_size=16, parallel=None):
        n += 1
    cpu_fe_s = time.perf_counter() - t0

    def _run_bucketed(embed_batch) -> float:
        groups: dict[int, list[tuple[int, object]]] = defaultdict(list)
        for i, enc in enumerate(encoded):
            groups[_bucket(int(sum(enc.attention_mask)))].append((i, enc))
        t0 = time.perf_counter()
        for seq, items in groups.items():
            for start in range(0, len(items), BATCH):
                chunk = items[start : start + BATCH]
                ids = np.zeros((len(chunk), seq), dtype=np.int64)
                mask = np.zeros((len(chunk), seq), dtype=np.int64)
                for row, (_, enc) in enumerate(chunk):
                    ntok = min(len(enc.ids), seq)
                    ids[row, :ntok] = np.asarray(enc.ids[:ntok], dtype=np.int64)
                    mask[row, :ntok] = 1
                if len(chunk) < BATCH:
                    pad = BATCH - len(chunk)
                    ids = np.concatenate([ids, np.repeat(ids[-1:], pad, axis=0)])
                    mask = np.concatenate([mask, np.repeat(mask[-1:], pad, axis=0)])
                embed_batch(ids, mask, seq)
        return time.perf_counter() - t0

    coreml_sessions = {}
    for seq in BUCKETS:
        patched = prepare_coderank_onnx_for_coreml(src.parent, batch=BATCH, seq=seq)
        coreml_sessions[seq] = ort.InferenceSession(
            str(patched),
            providers=[("CoreMLExecutionProvider", opts)],
        )

    def coreml_batch(ids, mask, seq):
        sess = coreml_sessions[seq]
        names = [i.name for i in sess.get_inputs()]
        sess.run(None, _feeds(ids, mask, names))

    # Warm buckets
    _run_bucketed(coreml_batch)
    coreml_bucket_s = _run_bucketed(coreml_batch)

    def mlx_batch(ids, mask, seq):
        mlx_opt.embed_ids_compiled(ids, mask)

    _run_bucketed(mlx_batch)
    mlx_bucket_s = _run_bucketed(mlx_batch)

    # Blind 512 CoreML pad (previous production CoreML strategy).
    sess512 = coreml_sessions[512]
    names512 = [i.name for i in sess512.get_inputs()]

    def run_pad512() -> float:
        t0 = time.perf_counter()
        for start in range(0, len(encoded), BATCH):
            chunk = encoded[start : start + BATCH]
            ids = np.zeros((BATCH, 512), dtype=np.int64)
            mask = np.zeros((BATCH, 512), dtype=np.int64)
            for row, enc in enumerate(chunk):
                ntok = min(len(enc.ids), 512)
                ids[row, :ntok] = np.asarray(enc.ids[:ntok], dtype=np.int64)
                mask[row, :ntok] = 1
            if chunk:
                ids[len(chunk) :] = ids[len(chunk) - 1]
                mask[len(chunk) :] = mask[len(chunk) - 1]
            sess512.run(None, _feeds(ids, mask, names512))
        return time.perf_counter() - t0

    coreml_512_s = run_pad512()

    n_chunks = len(texts)
    prod = {
        "chunks": n_chunks,
        "content_tokens": content_tokens,
        "cpu_fastembed_s": cpu_fe_s,
        "cpu_fastembed_cs": n_chunks / cpu_fe_s,
        "cpu_fastembed_ts": content_tokens / cpu_fe_s,
        "coreml_pad512_s": coreml_512_s,
        "coreml_pad512_cs": n_chunks / coreml_512_s,
        "coreml_pad512_ts": content_tokens / coreml_512_s,
        "coreml_bucket_s": coreml_bucket_s,
        "coreml_bucket_cs": n_chunks / coreml_bucket_s,
        "coreml_bucket_ts": content_tokens / coreml_bucket_s,
        "mlx_bucket_s": mlx_bucket_s,
        "mlx_bucket_cs": n_chunks / mlx_bucket_s,
        "mlx_bucket_ts": content_tokens / mlx_bucket_s,
    }
    print("\n=== Production-like ===", flush=True)
    print(json.dumps(prod, indent=2), flush=True)

    def ratio(a: float, b: float) -> float:
        return a / b if b else float("nan")

    print("\n=== Ratios (chunks/s, higher is better) ===", flush=True)
    print(
        json.dumps(
            {
                "fixed": {
                    r["seq"]: {
                        "mlx_vs_coreml": ratio(r["mlx_cs"], r["coreml_cs"]),
                        "mlx_opt_vs_coreml": ratio(r["mlx_opt_cs"], r["coreml_cs"]),
                        "mlx_vs_cpu": ratio(r["mlx_cs"], r["cpu_cs"]),
                        "coreml_vs_cpu": ratio(r["coreml_cs"], r["cpu_cs"]),
                    }
                    for r in fixed_rows
                },
                "production": {
                    "mlx_bucket_vs_coreml_bucket": ratio(
                        prod["mlx_bucket_cs"], prod["coreml_bucket_cs"]
                    ),
                    "mlx_bucket_vs_cpu_fastembed": ratio(
                        prod["mlx_bucket_cs"], prod["cpu_fastembed_cs"]
                    ),
                    "coreml_bucket_vs_cpu_fastembed": ratio(
                        prod["coreml_bucket_cs"], prod["cpu_fastembed_cs"]
                    ),
                    "coreml_bucket_vs_pad512": ratio(
                        prod["coreml_bucket_cs"], prod["coreml_pad512_cs"]
                    ),
                },
            },
            indent=2,
        ),
        flush=True,
    )
    out = {
        "device": device,
        "correctness": correct,
        "baseline_pass": baseline_ok,
        "fixed": fixed_rows,
        "production": prod,
    }
    dest = ROOT / "docs" / "apple-silicon-embed-bench.json"
    dest.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {dest}", flush=True)
    return 0 if baseline_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
