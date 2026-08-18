"""macOS CoreML / Metal GPU path for CodeRank FastEmbed.

CoreML EP requires fixed input shapes and a stable ORT batch size. Variable
``batch_size=len(batch)`` causes dynamic tensors and runtime failures such as
``runtime shape ({1,6,12,0}) has zero elements``.

We patch the cached CodeRank ONNX graph once at setup and always pad embed
batches to the calibrated static batch size on Darwin + coreml profile.
"""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path
from typing import Any

# Largest install-time calibration candidate — static ONNX is compiled for this.
COREML_STATIC_BATCH = int(os.environ.get("CTX_COREML_STATIC_BATCH", "20"))
COREML_STATIC_SEQ = int(os.environ.get("CTX_COREML_STATIC_SEQ", "512"))
COREML_STATIC_ONNX_NAME = (
    f"model.coreml_b{COREML_STATIC_BATCH}_s{COREML_STATIC_SEQ}.onnx"
)


def is_mac_apple_silicon() -> bool:
    return platform.system() == "Darwin" and platform.machine().lower() in {
        "arm64",
        "aarch64",
    }


def mac_gpu_only() -> bool:
    """When true, CoreML sessions exclude CPUExecutionProvider."""
    raw = (os.environ.get("CTX_MAC_GPU_ONLY") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def coreml_provider_options(*, compute_units: str | None = None) -> dict[str, str]:
    """ORT CoreML EP options tuned for transformer ONNX on Apple Silicon."""
    units = compute_units or os.environ.get("CTX_COREML_UNITS") or "CPUAndGPU"
    # ORT string provider options only — do NOT pass C-API flags such as
    # UseCPUAndGPU or CreateMLProgram (ModelFormat=MLProgram covers the latter).
    return {
        "ModelFormat": "MLProgram",
        "MLComputeUnits": str(units),
        # Static shapes compile reliably; dynamic axes crash on rotary/attention.
        "RequireStaticInputShapes": "1",
        "EnableOnSubgraphs": "0",
    }


def coreml_providers(
    profile: Any,
    *,
    gpu_only: bool | None = None,
) -> list:
    detected = getattr(profile, "detected", None) or {}
    units = None
    if isinstance(detected, dict):
        units = detected.get("coreml_compute_units")
    opts = coreml_provider_options(compute_units=str(units) if units else None)
    coreml = ("CoreMLExecutionProvider", opts)
    if gpu_only if gpu_only is not None else mac_gpu_only():
        return [coreml]
    return [coreml, "CPUExecutionProvider"]


def static_embed_batch_size(profile: Any, requested: int) -> int:
    """Return the fixed ORT batch size for CoreML (may exceed len(texts))."""
    if getattr(profile, "profile", None) != "coreml":
        return max(1, int(requested))
    static = int(
        (getattr(profile, "batch_calibration", None) or {}).get("coreml_static_batch")
        or COREML_STATIC_BATCH
    )
    return max(1, static)


def pad_embed_batch(texts: list[str], batch_size: int) -> list[str]:
    """Pad with duplicates so ORT always sees exactly ``batch_size`` rows."""
    n = len(texts)
    if n == 0:
        return []
    bs = max(1, int(batch_size))
    if n >= bs:
        return texts[:bs]
    filler = texts[-1]
    return texts + [filler] * (bs - n)


def find_coderank_onnx(root: Path) -> Path | None:
    """Locate FastEmbed's cached CodeRank ONNX under a HF-style tree."""
    if not root.is_dir():
        return None
    direct = root / "onnx" / "model.onnx"
    if direct.is_file():
        return direct
    for path in root.rglob("model.onnx"):
        if path.is_file():
            return path
    return None


def prepare_coderank_onnx_for_coreml(
    model_dir: Path,
    *,
    batch: int = COREML_STATIC_BATCH,
    seq: int = COREML_STATIC_SEQ,
) -> Path | None:
    """Rewrite dynamic axes to fixed [batch, seq] for CoreML compilation."""
    src = find_coderank_onnx(model_dir)
    if src is None:
        return None
    dst = src.parent / COREML_STATIC_ONNX_NAME
    if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
        return dst

    try:
        import onnx
        from onnxruntime.tools.onnx_model_utils import fix_output_shapes, make_input_shape_fixed
    except ImportError:
        return None

    work = src.parent / "_coreml_patch_src.onnx"
    shutil.copy2(src, work)
    model = onnx.load(str(work))
    fixed_names = ("input_ids", "attention_mask", "token_type_ids")
    shape = [batch, seq]
    patched_any = False
    for input_name in fixed_names:
        try:
            make_input_shape_fixed(model.graph, input_name, shape)
            patched_any = True
        except Exception:  # noqa: BLE001
            continue
    if not patched_any:
        return None
    fix_output_shapes(model)
    onnx.save(model, str(dst))
    work.unlink(missing_ok=True)
    return dst if dst.is_file() else None


def register_coreml_coderank_model(
    batch: int = COREML_STATIC_BATCH,
    seq: int = COREML_STATIC_SEQ,
) -> Path | None:
    """Download/warm model, patch ONNX, register static variant with FastEmbed."""
    from pipeline.accel import CODERANK_HF_ONNX, CODERANK_MODEL, register_coderank

    register_coderank()
    from fastembed import TextEmbedding
    from huggingface_hub import snapshot_download

    cache = snapshot_download(CODERANK_HF_ONNX)
    patched = prepare_coderank_onnx_for_coreml(Path(cache), batch=batch, seq=seq)
    if patched is None:
        return None

    rel = patched.name
    if patched.parent.name == "onnx":
        rel = f"onnx/{patched.name}"

    from fastembed.common.model_description import ModelSource, PoolingType

    try:
        TextEmbedding.add_custom_model(
            model=f"{CODERANK_MODEL}-coreml-static",
            pooling=PoolingType.MEAN,
            normalization=True,
            sources=ModelSource(hf=CODERANK_HF_ONNX),
            dim=768,
            model_file=rel,
            description="CodeRankEmbed CoreML-static ONNX",
            license="mit",
            size_in_gb=0.5,
        )
    except ValueError as exc:
        if "already registered" not in str(exc).lower():
            raise
    marker = Path.home() / ".context-engine" / "coderank_coreml_static.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        f'{{"model":"{CODERANK_MODEL}-coreml-static","batch":{batch},"seq":{seq}}}\n',
        encoding="utf-8",
    )
    return patched


def coreml_model_name(default: str) -> str:
    marker = Path.home() / ".context-engine" / "coderank_coreml_static.json"
    if not marker.is_file():
        return default
    try:
        import json

        data = json.loads(marker.read_text(encoding="utf-8"))
        return str(data.get("model") or default)
    except Exception:  # noqa: BLE001
        return default
