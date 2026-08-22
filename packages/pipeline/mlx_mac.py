"""CodeRankEmbed on Apple Silicon via MLX (Metal GPU).

Selectable embedding backend. Weights are converted from the existing CodeRank
ONNX initializers into ``~/.context-engine/mlx/`` — the FastEmbed / ONNX caches
are never modified. On Apple Silicon, ``ctx setup`` persists ``profile=mlx``
(FP16). ``CTX_EMBED_BACKEND=fastembed`` or ``CTX_MLX=0`` keeps the ORT path.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import numpy as np

# MLX ≥0.31 made GPU streams thread-local. Keeper / HTTP worker threads must
# create their own stream; weights loaded on the main thread still evaluate if
# we bind a per-thread stream and serialize embeds.
_MLX_EMBED_LOCK = threading.Lock()
_MLX_THREAD = threading.local()

# Matches jamie8johnson/CodeRankEmbed-onnx config.json (NomicBertModel).
CODERANK_HIDDEN = 768
CODERANK_LAYERS = 12
CODERANK_HEADS = 12
CODERANK_HEAD_DIM = 64  # hidden / heads; rotary_dim == head_dim
CODERANK_MLP = 3072
CODERANK_VOCAB = 30528
CODERANK_LN_EPS = 1e-12
CODERANK_ROPE_BASE = 1000.0
CODERANK_MAX_SEQ = 512


@contextmanager
def mlx_thread_stream() -> Iterator[Any]:
    """Bind a per-thread MLX stream for eval (safe for keeper / HTTP workers)."""
    import mlx.core as mx

    stream = getattr(_MLX_THREAD, "stream", None)
    if stream is None:
        device = mx.default_device()
        if hasattr(mx, "new_thread_local_stream"):
            stream = mx.new_thread_local_stream(device)
        else:
            stream = mx.new_stream(device)
        _MLX_THREAD.stream = stream
    with mx.stream(stream):
        yield stream


def mlx_cache_dir() -> Path:
    from pipeline.project_id import context_engine_home

    return context_engine_home() / "mlx" / "CodeRankEmbed"


def mlx_weights_path() -> Path:
    return mlx_cache_dir() / "weights.npz"


def mlx_fp16_weights_path() -> Path:
    return mlx_cache_dir() / "weights.fp16.npz"


def mlx_meta_path() -> Path:
    return mlx_cache_dir() / "meta.json"


def _require_mlx():
    try:
        import mlx.core as mx  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "MLX is not installed. pip install mlx  (Apple Silicon only)"
        ) from exc


def mlx_device_report(*, requested: str | None = None) -> dict[str, Any]:
    """Prove which device MLX is using (do not assume GPU)."""
    _require_mlx()
    import mlx.core as mx

    asked = (requested or os.environ.get("CTX_MLX_DEVICE") or "gpu").strip().lower()
    if asked in {"gpu", "metal"}:
        mx.set_default_device(mx.gpu)
    elif asked in {"cpu"}:
        mx.set_default_device(mx.cpu)
    else:
        raise RuntimeError(f"unknown CTX_MLX_DEVICE={asked!r}; use gpu or cpu")
    default = mx.default_device()
    metal_ok = False
    try:
        metal_ok = bool(mx.metal.is_available())
    except Exception:  # noqa: BLE001
        metal_ok = False
    info: dict[str, Any] = {}
    try:
        info = dict(mx.device_info() or {})
    except Exception as exc:  # noqa: BLE001
        info = {"error": str(exc)}
    probe = mx.ones((8, 8))
    mx.eval(probe)
    return {
        "requested": asked,
        "default_device": str(default),
        "array_device": str(default),
        "metal_available": metal_ok,
        "device_info": info,
        "gpu_compute": "gpu" in str(default).lower(),
    }


def require_mlx_gpu() -> dict[str, Any]:
    """Select the Apple GPU and fail closed if Metal/GPU is unavailable.

    The production MLX backend must never silently run on CPU.
    """
    if (os.environ.get("CTX_MLX_DEVICE") or "gpu").strip().lower() == "cpu":
        raise RuntimeError(
            "MLX embedding backend requires the Apple GPU; CTX_MLX_DEVICE=cpu is not allowed"
        )
    try:
        report = mlx_device_report(requested="gpu")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"MLX GPU initialization failed: {exc}. Refusing CPU fallback."
        ) from exc
    if not report.get("metal_available"):
        raise RuntimeError(
            "MLX Metal is not available. Refusing to run the MLX backend on CPU."
        )
    if not report.get("gpu_compute"):
        raise RuntimeError(
            f"MLX default device is {report.get('default_device')!r}, not GPU. "
            "Refusing CPU fallback."
        )
    return report


def _rss_bytes() -> dict[str, int]:
    import resource

    usage = resource.getrusage(resource.RUSAGE_SELF)
    peak = int(usage.ru_maxrss)
    if sys.platform != "darwin":
        peak *= 1024
    current = peak
    try:
        import psutil

        current = int(psutil.Process().memory_info().rss)
    except Exception:  # noqa: BLE001
        pass
    return {"rss": current, "rss_peak": peak}


def mlx_memory_snapshot(label: str = "") -> dict[str, Any]:
    """RSS + MLX allocator stats. ``get_memory`` does not exist in MLX 0.32."""
    _require_mlx()
    import mlx.core as mx

    rss = _rss_bytes()
    snap = {
        "label": label,
        "rss": rss["rss"],
        "rss_mb": round(rss["rss"] / (1024 * 1024), 1),
        "rss_peak": rss["rss_peak"],
        "rss_peak_mb": round(rss["rss_peak"] / (1024 * 1024), 1),
        "active": int(mx.get_active_memory()),
        "peak": int(mx.get_peak_memory()),
        "cache": int(mx.get_cache_memory()),
    }
    snap["active_mb"] = round(snap["active"] / (1024 * 1024), 1)
    snap["peak_mb"] = round(snap["peak"] / (1024 * 1024), 1)
    snap["cache_mb"] = round(snap["cache"] / (1024 * 1024), 1)
    return snap


def mlx_peak_memory_bytes() -> int | None:
    try:
        import mlx.core as mx

        return int(mx.get_peak_memory())
    except Exception:  # noqa: BLE001
        return None


def mlx_reset_peak_memory() -> None:
    try:
        import mlx.core as mx

        mx.reset_peak_memory()
    except Exception:  # noqa: BLE001
        pass


def apply_mlx_cache_limit(limit_bytes: int | None) -> int | None:
    """``limit_bytes=0`` disables the allocator cache. ``None`` leaves the default."""
    if limit_bytes is None:
        return None
    import mlx.core as mx

    return int(mx.set_cache_limit(int(limit_bytes)))


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def resolve_embed_dtype(_requested: str | None = None) -> str:
    """Production embedding precision is FP16 on every OS and hardware path."""
    raw = (os.environ.get("CTX_MLX_DTYPE") or _requested or "float16").strip().lower()
    if raw in {"float32", "fp32", "f32"}:
        # Once per process — avoid spam from multi-thread MLX loads.
        flag = "_ctx_warned_fp32_dtype"
        if not getattr(resolve_embed_dtype, flag, False):
            setattr(resolve_embed_dtype, flag, True)
            print(
                "[embed] CTX_MLX_DTYPE=float32 ignored; production weights are FP16 only",
                file=sys.stderr,
                flush=True,
            )
    return "float16"


def apply_mlx_production_defaults() -> None:
    """Fused kernels + output eval are on unless explicitly overridden."""
    os.environ["CTX_MLX_DTYPE"] = "float16"
    os.environ.setdefault("CTX_MLX_FAST_ATTN", "1")
    os.environ.setdefault("CTX_MLX_FAST_LN", "1")
    os.environ.setdefault("CTX_MLX_EVAL", "output")
    if "CTX_MLX_CACHE_MB" not in os.environ:
        from pipeline.memory_budget import bootstrap_budget

        os.environ["CTX_MLX_CACHE_MB"] = str(bootstrap_budget().mlx_cache_mb)


def _onnx_initializers(model: Any) -> dict[str, np.ndarray]:
    from onnx import numpy_helper

    out: dict[str, np.ndarray] = {}
    for tensor in model.graph.initializer:
        out[tensor.name] = np.asarray(numpy_helper.to_array(tensor))
    for node in model.graph.node:
        if node.op_type != "Constant":
            continue
        for attr in node.attribute:
            if attr.name == "value":
                out[node.output[0]] = np.asarray(numpy_helper.to_array(attr.t))
    return out


def _matmul_weight_name(model: Any, suffix: str) -> str:
    for node in model.graph.node:
        if node.op_type == "MatMul" and node.name.endswith(suffix):
            return str(node.input[1])
    raise KeyError(f"MatMul not found: {suffix}")


def convert_coderank_onnx_to_mlx(onnx_path: Path, dest_dir: Path | None = None) -> Path:
    """Extract CodeRank ONNX initializers into an isolated MLX npz cache."""
    import onnx

    dest = dest_dir or mlx_cache_dir()
    dest.mkdir(parents=True, exist_ok=True)
    model = onnx.load(str(onnx_path))
    inits = _onnx_initializers(model)
    packed: dict[str, np.ndarray] = {
        "word_embeddings": inits["0.auto_model.embeddings.word_embeddings.weight"],
        "token_type_embeddings": inits["0.auto_model.embeddings.token_type_embeddings.weight"],
        "emb_ln.weight": inits["0.auto_model.emb_ln.weight"],
        "emb_ln.bias": inits["0.auto_model.emb_ln.bias"],
    }
    inv = None
    for name, arr in inits.items():
        if name.endswith("rotary_emb/Constant_3_output_0") and arr.shape == (32,):
            inv = arr.astype(np.float32)
            break
    if inv is None:
        idx = np.arange(0, CODERANK_HEAD_DIM, 2, dtype=np.float32)
        inv = (CODERANK_ROPE_BASE ** (-idx / CODERANK_HEAD_DIM)).astype(np.float32)
    packed["rotary_inv_freq"] = inv

    for i in range(CODERANK_LAYERS):
        packed[f"layers.{i}.Wqkv"] = inits[
            _matmul_weight_name(model, f"layers.{i}/attn/Wqkv/MatMul")
        ]
        packed[f"layers.{i}.out_proj"] = inits[
            _matmul_weight_name(model, f"layers.{i}/attn/out_proj/MatMul")
        ]
        packed[f"layers.{i}.fc11"] = inits[
            _matmul_weight_name(model, f"layers.{i}/mlp/fc11/MatMul")
        ]
        packed[f"layers.{i}.fc12"] = inits[
            _matmul_weight_name(model, f"layers.{i}/mlp/fc12/MatMul")
        ]
        packed[f"layers.{i}.fc2"] = inits[
            _matmul_weight_name(model, f"layers.{i}/mlp/fc2/MatMul")
        ]
        packed[f"layers.{i}.norm1.weight"] = inits[
            f"0.auto_model.encoder.layers.{i}.norm1.weight"
        ]
        packed[f"layers.{i}.norm1.bias"] = inits[
            f"0.auto_model.encoder.layers.{i}.norm1.bias"
        ]
        packed[f"layers.{i}.norm2.weight"] = inits[
            f"0.auto_model.encoder.layers.{i}.norm2.weight"
        ]
        packed[f"layers.{i}.norm2.bias"] = inits[
            f"0.auto_model.encoder.layers.{i}.norm2.bias"
        ]

    np.savez(dest / "weights.npz", **packed)
    meta = {
        "source_onnx": str(onnx_path.resolve()),
        "hidden": CODERANK_HIDDEN,
        "layers": CODERANK_LAYERS,
        "heads": CODERANK_HEADS,
        "head_dim": CODERANK_HEAD_DIM,
        "rotary_dim": CODERANK_HEAD_DIM,
        "rotary_emb_fraction": 1.0,
        "rotary_emb_base": CODERANK_ROPE_BASE,
        "rotary_emb_interleaved": False,
        "mlp_inner": CODERANK_MLP,
        "vocab_size": CODERANK_VOCAB,
        "ln_eps": CODERANK_LN_EPS,
        "activation": "swiglu",
        "prenorm": False,
        "pooling": "mean",
        "normalization": True,
        "qkv_proj_bias": False,
        "mlp_bias": False,
    }
    (dest / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return dest / "weights.npz"


def ensure_mlx_weights(onnx_path: Path | None = None) -> Path:
    dest = mlx_weights_path()
    if dest.is_file():
        return dest
    if onnx_path is None:
        from pipeline.coreml_mac import _fastembed_cache_root, find_coderank_onnx

        found = find_coderank_onnx(_fastembed_cache_root())
        if found is None:
            raise FileNotFoundError(
                "CodeRank FP16 ONNX (onnx/model_fp16.onnx) not in FastEmbed cache. "
                "Run `ctx setup --repair` to download it."
            )
        onnx_path = found
    return convert_coderank_onnx_to_mlx(onnx_path)


def ensure_mlx_fp16_weights() -> Path:
    """Sidecar FP16 npz so FP16 inference never mmap-loads the FP32 master weights."""
    fp16 = mlx_fp16_weights_path()
    fp32 = ensure_mlx_weights()
    if fp16.is_file() and fp16.stat().st_mtime >= fp32.stat().st_mtime:
        return fp16
    raw = np.load(fp32, mmap_mode="r")
    packed: dict[str, np.ndarray] = {}
    for key in raw.files:
        arr = np.asarray(raw[key])
        packed[key] = arr.astype(np.float16) if arr.dtype.kind == "f" else arr
    del raw
    fp16.parent.mkdir(parents=True, exist_ok=True)
    np.savez(fp16, **packed)
    del packed
    return fp16


def _layer_norm(x: Any, weight: Any, bias: Any, eps: float = CODERANK_LN_EPS) -> Any:
    import mlx.core as mx

    mean = mx.mean(x, axis=-1, keepdims=True)
    var = mx.mean((x - mean) ** 2, axis=-1, keepdims=True)
    return (x - mean) * mx.rsqrt(var + eps) * weight + bias


def _rotate_half(x: Any) -> Any:
    """Nomic/flash-attn rotate-half (rotary_emb_interleaved=false)."""
    import mlx.core as mx

    x1 = x[..., : CODERANK_HEAD_DIM // 2]
    x2 = x[..., CODERANK_HEAD_DIM // 2 :]
    return mx.concatenate([-x2, x1], axis=-1)


def _apply_rope(q: Any, k: Any, inv_freq: Any) -> tuple[Any, Any]:
    """Full-head RoPE: rotary_dim == head_dim == 64, base 1000, rotate-half."""
    import mlx.core as mx

    seq = q.shape[1]
    t = mx.arange(seq, dtype=mx.float32)
    freqs = t[:, None] * inv_freq[None, :]
    cos = mx.cos(freqs)
    sin = mx.sin(freqs)
    cos = mx.concatenate([cos, cos], axis=-1)[None, :, None, :]
    sin = mx.concatenate([sin, sin], axis=-1)[None, :, None, :]
    q = q * cos + _rotate_half(q) * sin
    k = k * cos + _rotate_half(k) * sin
    return q, k


def _mean_pool(tokens: Any, mask: Any) -> Any:
    import mlx.core as mx

    m = mask.astype(tokens.dtype)[:, :, None]
    summed = mx.sum(tokens * m, axis=1)
    denom = mx.maximum(mx.sum(m, axis=1), 1e-9)
    return summed / denom


def _l2_normalize(x: Any, eps: float = 1e-12) -> Any:
    import mlx.core as mx

    norm = mx.maximum(mx.linalg.norm(x, axis=-1, keepdims=True), eps)
    return x / norm


class CodeRankMLX:
    """NomicBert CodeRankEmbed in MLX (post-norm, fused QKV, SwiGLU, full-head RoPE)."""

    def __init__(
        self,
        weights_path: Path | None = None,
        *,
        dtype: str = "float16",
        require_gpu: bool = True,
    ):
        _require_mlx()
        import mlx.core as mx

        report = require_mlx_gpu() if require_gpu else mlx_device_report()
        self.device_report = report
        apply_mlx_production_defaults()
        master = weights_path or ensure_mlx_weights()
        resolve_embed_dtype(dtype)
        mlx_dtype = mx.float16
        self.dtype = mlx_dtype
        cache_mb = os.environ.get("CTX_MLX_CACHE_MB")
        if cache_mb is not None and cache_mb.strip() != "":
            apply_mlx_cache_limit(int(cache_mb) * 1024 * 1024)
        load_path = ensure_mlx_fp16_weights() if weights_path is None else master
        self.w: dict[str, Any] = {}
        raw = np.load(load_path, mmap_mode="r")
        try:
            for key in raw.files:
                arr = raw[key]
                if arr.dtype.kind == "f":
                    self.w[key] = mx.array(arr, dtype=mlx_dtype)
                else:
                    self.w[key] = mx.array(arr)
        finally:
            del raw
        import gc

        gc.collect()
        with mlx_thread_stream():
            mx.eval(*self.w.values())
            try:
                mx.clear_cache()
            except Exception:  # noqa: BLE001
                pass
        self.inv_freq = self.w["rotary_inv_freq"].astype(mx.float32)
        self._compiled = None
        self.use_fast_attn = _flag("CTX_MLX_FAST_ATTN", True)
        self.use_fast_ln = _flag("CTX_MLX_FAST_LN", True)
        self.eval_per_layer = os.environ.get("CTX_MLX_EVAL_LAYER", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    def _encoder_layer(self, x: Any, attn_bias: Any, i: int) -> Any:
        import mlx.core as mx

        residual = x
        bsz, seq, _ = x.shape
        qkv = x @ self.w[f"layers.{i}.Wqkv"]
        qkv = qkv.reshape(bsz, seq, 3, CODERANK_HEADS, CODERANK_HEAD_DIM)
        q, k, v = qkv[:, :, 0], qkv[:, :, 1], qkv[:, :, 2]
        q, k = _apply_rope(q.astype(mx.float32), k.astype(mx.float32), self.inv_freq)
        q = q.astype(x.dtype)
        k = k.astype(x.dtype)
        qh = mx.transpose(q, (0, 2, 1, 3))
        vh = mx.transpose(v.astype(mx.float32), (0, 2, 1, 3))
        if self.use_fast_attn:
            kh = mx.transpose(k, (0, 2, 1, 3))
            ctx = mx.fast.scaled_dot_product_attention(
                qh.astype(mx.float32),
                kh.astype(mx.float32),
                vh,
                scale=1.0 / 8.0,
                mask=attn_bias.astype(mx.float32),
            )
        else:
            kh = mx.transpose(k, (0, 2, 3, 1))
            scores = (qh @ kh) / mx.array(8.0, dtype=mx.float32)
            scores = scores + attn_bias.astype(mx.float32)
            probs = mx.softmax(scores, axis=-1)
            ctx = probs @ vh
        ctx = mx.transpose(ctx, (0, 2, 1, 3)).reshape(bsz, seq, CODERANK_HIDDEN)
        ln = mx.fast.layer_norm if self.use_fast_ln else _layer_norm
        x = ln(
            residual + (ctx @ self.w[f"layers.{i}.out_proj"]),
            self.w[f"layers.{i}.norm1.weight"],
            self.w[f"layers.{i}.norm1.bias"],
            CODERANK_LN_EPS,
        )
        gate = x @ self.w[f"layers.{i}.fc12"]
        up = x @ self.w[f"layers.{i}.fc11"]
        hidden = up * (gate * mx.sigmoid(gate))
        mlp_out = hidden @ self.w[f"layers.{i}.fc2"]
        return ln(
            x + mlp_out,
            self.w[f"layers.{i}.norm2.weight"],
            self.w[f"layers.{i}.norm2.bias"],
            CODERANK_LN_EPS,
        )

    def forward_tokens(self, input_ids: Any, attention_mask: Any) -> Any:
        import mlx.core as mx

        ids = input_ids.astype(mx.int32)
        mask = attention_mask.astype(mx.float32)
        tok = self.w["word_embeddings"][ids]
        tok_type = self.w["token_type_embeddings"][mx.zeros_like(ids)]
        x = _layer_norm(tok + tok_type, self.w["emb_ln.weight"], self.w["emb_ln.bias"])
        x = x.astype(self.dtype)
        attn_bias = (1.0 - mask)[:, None, None, :] * mx.array(
            np.float32(-3.4028235e38)
        )
        for i in range(CODERANK_LAYERS):
            x = self._encoder_layer(x, attn_bias.astype(mx.float32), i)
            if self.eval_per_layer:
                mx.eval(x)
        return x.astype(mx.float32)

    def embed_ids(
        self,
        input_ids: np.ndarray,
        attention_mask: np.ndarray,
        *,
        timings: dict[str, float] | None = None,
        eval_mode: str | None = None,
    ) -> np.ndarray:
        """Embed token ids.

        ``eval_mode``:
          * ``output`` — one ``mx.eval`` on the final vectors (lazy graph).
          * ``staged`` — eval hidden states, pool, and norm separately (timing).
        Default is ``CTX_MLX_EVAL`` or ``output``.
        """
        import mlx.core as mx

        mode = (eval_mode or os.environ.get("CTX_MLX_EVAL") or "output").strip().lower()
        t0 = time.perf_counter()
        with _MLX_EMBED_LOCK:
            with mlx_thread_stream():
                ids = mx.array(np.asarray(input_ids, dtype=np.int32))
                mask = mx.array(np.asarray(attention_mask, dtype=np.float32))
                t_prep = time.perf_counter()
                if mode == "staged":
                    mx.eval(ids, mask)
                    tokens = self.forward_tokens(ids, mask)
                    mx.eval(tokens)
                    t_infer = time.perf_counter()
                    pooled = _mean_pool(tokens, mask)
                    mx.eval(pooled)
                    t_pool = time.perf_counter()
                    normed = _l2_normalize(pooled)
                    mx.eval(normed)
                    t_norm = time.perf_counter()
                    out = np.asarray(normed, dtype=np.float32)
                    del tokens, pooled, normed, ids, mask
                else:
                    normed = _l2_normalize(
                        _mean_pool(self.forward_tokens(ids, mask), mask)
                    )
                    mx.eval(normed)
                    t_infer = time.perf_counter()
                    t_pool = t_infer
                    t_norm = t_infer
                    out = np.asarray(normed, dtype=np.float32)
                    del normed, ids, mask
        if timings is not None:
            timings["batch_prep"] = timings.get("batch_prep", 0.0) + (t_prep - t0)
            timings["mlx_inference"] = timings.get("mlx_inference", 0.0) + (t_infer - t_prep)
            timings["pooling"] = timings.get("pooling", 0.0) + (t_pool - t_infer)
            timings["normalization"] = timings.get("normalization", 0.0) + (t_norm - t_pool)
        return out

    def embed_texts(
        self,
        texts: list[str],
        *,
        tokenizer=None,
        timings: dict[str, float] | None = None,
        max_seq: int = CODERANK_MAX_SEQ,
    ) -> np.ndarray:
        t0 = time.perf_counter()
        ids, mask = tokenize_batch(texts, tokenizer=tokenizer, max_seq=max_seq)
        if timings is not None:
            timings["tokenization"] = timings.get("tokenization", 0.0) + (
                time.perf_counter() - t0
            )
        return self.embed_ids(ids, mask, timings=timings)

    def compile(self) -> None:
        import mlx.core as mx

        def _fn(ids: Any, mask: Any) -> Any:
            tokens = self.forward_tokens(ids, mask)
            return _l2_normalize(_mean_pool(tokens, mask))

        self._compiled = mx.compile(_fn)

    def embed_ids_compiled(self, input_ids: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
        import mlx.core as mx

        if self._compiled is None:
            self.compile()
        with _MLX_EMBED_LOCK:
            with mlx_thread_stream():
                ids = mx.array(np.asarray(input_ids, dtype=np.int32))
                mask = mx.array(np.asarray(attention_mask, dtype=np.float32))
                out = self._compiled(ids, mask)
                mx.eval(out)
                return np.asarray(out, dtype=np.float32)


def load_coderank_tokenizer(onnx_dir: Path | None = None):
    from tokenizers import Tokenizer

    from pipeline.coreml_mac import _fastembed_cache_root, find_coderank_onnx

    if onnx_dir is None:
        found = find_coderank_onnx(_fastembed_cache_root())
        if found is None:
            raise FileNotFoundError(
                "CodeRank FP16 ONNX (onnx/model_fp16.onnx) not in FastEmbed cache. "
                "Run `ctx setup --repair` to download it."
            )
        onnx_dir = found.parent.parent
    tok_path = onnx_dir / "tokenizer.json"
    tok = Tokenizer.from_file(str(tok_path))
    return tok


def tokenize_batch(
    texts: list[str],
    *,
    seq: int | None = None,
    tokenizer=None,
    max_seq: int = CODERANK_MAX_SEQ,
) -> tuple[np.ndarray, np.ndarray]:
    """Truncate to ``max_seq`` and pad to the longest sequence in this batch.

    Production path: omit ``seq`` so a batch whose longest chunk is 241 tokens
    runs as ``batch × 241``, not ``batch × 512``. Never emit a sequence longer
    than the model maximum.
    """
    tok = tokenizer or load_coderank_tokenizer()
    pad_id = 0
    cap = max(1, min(int(max_seq), CODERANK_MAX_SEQ))
    if hasattr(tok, "no_padding"):
        tok.no_padding()
    if hasattr(tok, "no_truncation"):
        tok.no_truncation()
    tok.enable_truncation(max_length=cap)
    if seq is not None:
        tok.enable_padding(
            length=min(int(seq), cap),
            pad_id=pad_id,
            pad_token="[PAD]",
        )
    else:
        tok.enable_padding(pad_id=pad_id, pad_token="[PAD]")
    encoded = tok.encode_batch(list(texts))
    ids = np.asarray([e.ids for e in encoded], dtype=np.int64)
    mask = np.asarray([e.attention_mask for e in encoded], dtype=np.int64)
    if ids.ndim != 2 or mask.shape != ids.shape:
        raise RuntimeError(
            f"tokenizer produced misaligned ids/mask: ids={ids.shape} mask={mask.shape}"
        )
    if ids.shape[1] > cap:
        ids = ids[:, :cap]
        mask = mask[:, :cap]
    return ids, mask


def content_token_count(attention_mask: np.ndarray) -> int:
    return int(np.asarray(attention_mask, dtype=np.int64).sum())
