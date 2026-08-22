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
    f"model.coreml_b{COREML_STATIC_BATCH}_s{COREML_STATIC_SEQ}_norot0.onnx"
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


def requested_compute_units(explicit: str | None = None) -> str:
    """Metal GPU units. Default CPUAndGPU — ALL can prefer ANE and fail transformers."""
    units = (explicit or os.environ.get("CTX_COREML_UNITS") or "CPUAndGPU").strip()
    return units or "CPUAndGPU"


def coreml_provider_options(*, compute_units: str | None = None) -> dict[str, str]:
    """ORT CoreML EP options tuned for transformer ONNX on Apple Silicon."""
    units = requested_compute_units(compute_units)
    # ORT string provider options only — do NOT pass C-API flags such as
    # UseCPUAndGPU or CreateMLProgram (ModelFormat=MLProgram covers the latter).
    return {
        "ModelFormat": "MLProgram",
        "MLComputeUnits": str(units),
        # Static shapes compile reliably; dynamic axes crash on rotary/attention.
        "RequireStaticInputShapes": "1",
        "EnableOnSubgraphs": "0",
    }


def assert_coreml_ep_active(onnx_path: Path, providers: list) -> list[str]:
    """Create an ORT session and refuse silent CPU fallback."""
    import onnxruntime as ort

    sess = ort.InferenceSession(str(onnx_path), providers=providers)
    used = [str(p) for p in sess.get_providers()]
    if not used or used[0] != "CoreMLExecutionProvider":
        raise RuntimeError(
            "CoreML GPU path failed; ONNX Runtime did not activate "
            f"CoreMLExecutionProvider (active={used}). Refusing CPU fallback. "
            "Invalid EP options or a dynamic ONNX graph usually cause this."
        )
    return used


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


def is_coderank_onnx_dir(onnx_dir: Path) -> bool:
    """True when this cache folder holds production CodeRank weights (FP16 preferred)."""
    return (onnx_dir / "model_fp16.onnx").is_file() or (onnx_dir / "model.onnx").is_file()


def find_coderank_onnx(root: Path) -> Path | None:
    """Locate FastEmbed's cached CodeRank FP16 ONNX under a HF-style tree."""
    if not root.is_dir():
        return None
    for rel in ("onnx/model_fp16.onnx", "model_fp16.onnx"):
        direct = root / rel
        if direct.is_file():
            return direct
    for path in root.rglob("model_fp16.onnx"):
        if path.is_file():
            return path
    return None


def _onnx_attr_i(node: Any, name: str, default: int | None = None) -> int | None:
    for attr in node.attribute:
        if attr.name == name:
            return int(attr.i)
    return default


def _const_tensors(model: Any) -> dict[str, Any]:
    import numpy as np
    from onnx import numpy_helper

    out: dict[str, Any] = {}
    for tensor in model.graph.initializer:
        out[tensor.name] = numpy_helper.to_array(tensor)
    for node in model.graph.node:
        if node.op_type != "Constant":
            continue
        for attr in node.attribute:
            if attr.name == "value":
                out[node.output[0]] = numpy_helper.to_array(attr.t)
    return {k: np.asarray(v) for k, v in out.items()}


def _nodes_by_output(model: Any) -> dict[str, Any]:
    return {out: node for node in model.graph.node for out in node.output}


def _as_int(value: Any) -> int | None:
    import numpy as np

    if value is None:
        return None
    arr = np.asarray(value)
    if arr.dtype == object or arr.size != 1:
        return None
    return int(arr.reshape(()))


def _eval_const(name: str, consts: dict[str, Any], by_out: dict[str, Any], *, depth: int = 0) -> Any | None:
    """Fold a tiny constant subgraph (Constant / Unsqueeze / Gather / Mul / Shape)."""
    import numpy as np

    if name in consts:
        return consts[name]
    if depth > 12:
        return None
    node = by_out.get(name)
    if node is None:
        return None
    if node.op_type == "Unsqueeze":
        data = _eval_const(node.input[0], consts, by_out, depth=depth + 1)
        if data is None:
            return None
        axes = None
        if len(node.input) > 1:
            axes = _eval_const(node.input[1], consts, by_out, depth=depth + 1)
        if axes is None:
            axes = _onnx_attr_i(node, "axes")
        if axes is None:
            return np.asarray(data).reshape((1,))
        return np.expand_dims(np.asarray(data), axis=int(np.asarray(axes).reshape(())))
    if node.op_type == "Mul" and len(node.input) == 2:
        a = _eval_const(node.input[0], consts, by_out, depth=depth + 1)
        b = _eval_const(node.input[1], consts, by_out, depth=depth + 1)
        if a is None or b is None:
            return None
        return np.asarray(a) * np.asarray(b)
    if node.op_type == "Gather" and len(node.input) == 2:
        data = _eval_const(node.input[0], consts, by_out, depth=depth + 1)
        index = _eval_const(node.input[1], consts, by_out, depth=depth + 1)
        if data is None or index is None:
            return None
        axis = int(_onnx_attr_i(node, "axis", 0) or 0)
        return np.take(np.asarray(data), int(np.asarray(index).reshape(())), axis=axis)
    if node.op_type == "Shape":
        last = _static_last_dim(node.input[0], consts, by_out, depth=depth + 1)
        # Shape vector is not fully known; last-dim-only callers use other paths.
        _ = last
        return None
    return None


def _reshape_const_last_dim(node: Any, consts: dict[str, Any], by_out: dict[str, Any]) -> int | None:
    if node.op_type != "Reshape" or len(node.input) < 2:
        return None
    shape = _eval_const(node.input[1], consts, by_out)
    if shape is not None and len(shape) > 0:
        last = int(shape[-1])
        return last if last > 0 else None
    shape_node = by_out.get(node.input[1])
    if shape_node is None or shape_node.op_type != "Concat" or not shape_node.input:
        return None
    last = _eval_const(shape_node.input[-1], consts, by_out)
    return _as_int(last)


def _static_last_dim(name: str, consts: dict[str, Any], by_out: dict[str, Any], *, depth: int = 0) -> int | None:
    if depth > 16:
        return None
    if name in consts:
        arr = consts[name]
        return int(arr.shape[-1]) if arr.ndim else None
    node = by_out.get(name)
    if node is None:
        return None
    if node.op_type == "Reshape":
        return _reshape_const_last_dim(node, consts, by_out)
    if node.op_type in {"Gather", "Identity", "Cast", "Slice"}:
        return _static_last_dim(node.input[0], consts, by_out, depth=depth + 1)
    return None


def _cos_inv_freq_len(name: str, consts: dict[str, Any], by_out: dict[str, Any], *, depth: int = 0) -> int | None:
    """If ``name`` is Cos(Einsum('i,j->ij', Range, inv_freq)), return len(inv_freq)."""
    if depth > 8:
        return None
    node = by_out.get(name)
    if node is None:
        return None
    if node.op_type in {"Cast", "Identity"}:
        return _cos_inv_freq_len(node.input[0], consts, by_out, depth=depth + 1)
    if node.op_type == "Cos":
        return _cos_inv_freq_len(node.input[0], consts, by_out, depth=depth + 1)
    if node.op_type != "Einsum" or len(node.input) != 2:
        return None
    eq = ""
    for attr in node.attribute:
        if attr.name == "equation":
            eq = attr.s.decode("utf-8") if isinstance(attr.s, bytes) else str(attr.s)
    if eq.replace(" ", "") != "i,j->ij":
        return None
    freq = consts.get(node.input[1])
    if freq is None:
        return None
    return int(freq.shape[0]) if freq.ndim >= 1 else int(freq.size)


def _rotary_dim_from_remainder_start(
    starts_name: str, consts: dict[str, Any], by_out: dict[str, Any]
) -> int | None:
    """Nomic RoPE remainder starts at ``2 * cos.shape[1]`` = ``2 * len(inv_freq)``."""
    folded = _as_int(_eval_const(starts_name, consts, by_out))
    if folded is not None:
        return folded
    node = by_out.get(starts_name)
    if node is None:
        return None
    # Unsqueeze(Mul(Gather(Shape(Cos), 1), 2))
    if node.op_type == "Unsqueeze":
        return _rotary_dim_from_remainder_start(node.input[0], consts, by_out)
    if node.op_type != "Mul" or len(node.input) != 2:
        return None
    scale = _as_int(_eval_const(node.input[1], consts, by_out))
    gather = by_out.get(node.input[0])
    if scale != 2 or gather is None or gather.op_type != "Gather":
        return None
    index = _as_int(_eval_const(gather.input[1], consts, by_out))
    shape_node = by_out.get(gather.input[0])
    if index != 1 or shape_node is None or shape_node.op_type != "Shape":
        return None
    freq_len = _cos_inv_freq_len(shape_node.input[0], consts, by_out)
    if freq_len is None:
        return None
    return int(scale) * int(freq_len)


def _slice_spec(node: Any, consts: dict[str, Any], by_out: dict[str, Any]) -> dict[str, Any] | None:
    if node.op_type != "Slice" or len(node.input) < 1:
        return None
    starts = ends = axes = steps = None
    if len(node.input) >= 4:
        starts = _eval_const(node.input[1], consts, by_out)
        ends = _eval_const(node.input[2], consts, by_out)
        axes = _eval_const(node.input[3], consts, by_out)
        if len(node.input) >= 5:
            steps = _eval_const(node.input[4], consts, by_out)
    return {
        "data": node.input[0],
        "starts": starts,
        "ends": ends,
        "axes": axes,
        "steps": steps,
        "starts_name": node.input[1] if len(node.input) > 1 else "",
    }


def _is_last_axis(axes: Any, concat_axis: int) -> bool:
    import numpy as np

    if axes is None:
        return False
    arr = np.asarray(axes).reshape(-1)
    if arr.size != 1:
        return False
    axis = int(arr[0])
    if axis == concat_axis:
        return True
    # Rank-4 Q/K is [batch, seq, heads, dim]; export uses axis=-1 or 3.
    return concat_axis in {-1, 3} and axis in {-1, 3}


def _is_end_to_end(ends: Any) -> bool:
    import numpy as np

    if ends is None:
        return False
    val = int(np.asarray(ends).reshape(-1)[0])
    return val < 0 or val >= 2**62


def _in_rotary_emb(*nodes: Any) -> bool:
    return all("rotary_emb" in str(getattr(n, "name", "")) for n in nodes)


def _prune_unused_nodes(graph: Any) -> int:
    needed = {out.name for out in graph.output}
    changed = True
    while changed:
        changed = False
        for node in graph.node:
            if not any(out in needed for out in node.output):
                continue
            for inp in node.input:
                if inp and inp not in needed:
                    needed.add(inp)
                    changed = True
    keep = [node for node in graph.node if any(out in needed for out in node.output)]
    dropped = len(graph.node) - len(keep)
    if dropped:
        del graph.node[:]
        graph.node.extend(keep)
    return dropped


def _match_empty_rotary_remainder(
    concat: Any, consts: dict[str, Any], by_out: dict[str, Any]
) -> Any | None:
    """Return the remainder Slice node if Concat is a proven empty RoPE remainder."""
    import numpy as np

    if concat.op_type != "Concat" or len(concat.input) != 2:
        return None
    concat_axis = _onnx_attr_i(concat, "axis", 0)
    if concat_axis not in (-1, 3):
        return None
    slice_node = by_out.get(concat.input[1])
    if slice_node is None or slice_node.op_type != "Slice":
        return None
    if not _in_rotary_emb(concat, slice_node):
        return None
    spec = _slice_spec(slice_node, consts, by_out)
    if spec is None:
        return None
    if not _is_last_axis(spec["axes"], int(concat_axis)):
        return None
    if spec["steps"] is not None and int(np.asarray(spec["steps"]).reshape(-1)[0]) != 1:
        return None
    if not _is_end_to_end(spec["ends"]):
        return None
    head_dim = _static_last_dim(spec["data"], consts, by_out)
    rotary_dim = _rotary_dim_from_remainder_start(spec["starts_name"], consts, by_out)
    if head_dim is None or rotary_dim is None:
        return None
    if rotary_dim < head_dim:
        return None
    return slice_node


def rotary_remainder_concat_nodes(model: Any) -> list[Any]:
    """Concat nodes that still append a proven-empty rotary remainder Slice."""
    consts = _const_tensors(model)
    by_out = _nodes_by_output(model)
    found = []
    for node in model.graph.node:
        if _match_empty_rotary_remainder(node, consts, by_out) is not None:
            found.append(node)
    return found


def bypass_empty_rotary_remainders(model: Any) -> int:
    """Drop RoPE remainder Slice+Concat iff rotary_dim == head_dim (empty remainder).

    CodeRank/Nomic-BERT full-head rotary still exports
    ``Concat(rotated, Slice(x, start=rotary_dim))`` on the last axis. When
    ``rotary_emb_fraction=1``, that Slice has width 0. CPU/DML treat it as a
    no-op; CoreML rejects dim-0 tensors and partitions the graph (~49 pieces).

    Only rewires Concat(rotated, remainder) → rotated when the remainder is
    proven empty. Partial rotary (``rotary_dim < head_dim``) is left intact.
    """
    graph = model.graph
    consts = _const_tensors(model)
    by_out = _nodes_by_output(model)
    rewire: dict[str, str] = {}
    drop_names: set[str] = set()

    for node in graph.node:
        slice_node = _match_empty_rotary_remainder(node, consts, by_out)
        if slice_node is None:
            continue
        rewire[node.output[0]] = node.input[0]
        drop_names.add(node.name)
        drop_names.add(slice_node.name)

    if not rewire:
        return 0
    for node in graph.node:
        for i, tensor_name in enumerate(list(node.input)):
            if tensor_name in rewire:
                node.input[i] = rewire[tensor_name]
    keep = [n for n in graph.node if n.name not in drop_names]
    del graph.node[:]
    graph.node.extend(keep)
    _prune_unused_nodes(graph)
    return len(rewire)


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
    dst = src.parent / f"model.coreml_b{batch}_s{seq}_norot0.onnx"
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
    bypass_empty_rotary_remainders(model)
    fix_output_shapes(model)
    onnx.checker.check_model(model)
    onnx.save(model, str(dst))
    work.unlink(missing_ok=True)
    return dst if dst.is_file() else None


def _fastembed_cache_root() -> Path:
    from fastembed.common.utils import define_cache_dir

    return Path(define_cache_dir())


def install_patched_onnx_into_fastembed_cache(patched: Path) -> Path:
    """FastEmbed uses its own HF-style cache, not huggingface_hub's default."""
    dest = patched
    root = _fastembed_cache_root()
    if not root.is_dir():
        return dest
    for onnx_dir in root.glob("**/onnx"):
        if not is_coderank_onnx_dir(onnx_dir):
            continue
        target = onnx_dir / patched.name
        if target.resolve() == patched.resolve():
            dest = target
            continue
        target.unlink(missing_ok=True)
        try:
            os.link(patched, target)
        except OSError:
            shutil.copy2(patched, target)
        dest = target
    return dest


def register_coreml_coderank_model(
    batch: int = COREML_STATIC_BATCH,
    seq: int = COREML_STATIC_SEQ,
) -> Path | None:
    """Download/warm model, patch ONNX, register static variant with FastEmbed."""
    from pipeline.accel import CODERANK_HF_ONNX, CODERANK_MODEL, register_coderank

    register_coderank()
    from fastembed import TextEmbedding
    from huggingface_hub import snapshot_download

    fe_cache = _fastembed_cache_root()
    cache = snapshot_download(CODERANK_HF_ONNX, cache_dir=str(fe_cache))
    patched = prepare_coderank_onnx_for_coreml(Path(cache), batch=batch, seq=seq)
    if patched is None:
        # Fall back to the default HF hub cache, then copy into FastEmbed.
        hub = snapshot_download(CODERANK_HF_ONNX)
        patched = prepare_coderank_onnx_for_coreml(Path(hub), batch=batch, seq=seq)
        if patched is None:
            return None
        patched = install_patched_onnx_into_fastembed_cache(patched)
    else:
        patched = install_patched_onnx_into_fastembed_cache(patched)

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
            size_in_gb=0.27,
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


def bind_coreml_tokenizer(fe_model: Any, seq: int = COREML_STATIC_SEQ) -> Any:
    """Force FastEmbed to pad/truncate every sequence to the static CoreML length.

    FastEmbed pads to the longest item in the batch, which is shorter than the
    patched ONNX ``[batch, seq]`` graph and crashes with INVALID_ARGUMENT.
    """
    inner = getattr(fe_model, "model", fe_model)
    tok = getattr(inner, "tokenizer", None)
    if tok is None:
        load = getattr(inner, "load_onnx_model", None)
        if load is None:
            raise RuntimeError("FastEmbed model has no tokenizer to bind for CoreML")
        load()
        tok = getattr(inner, "tokenizer", None)
    if tok is None:
        raise RuntimeError("FastEmbed tokenizer missing after load")
    pad_id = 0
    pad_token = "[PAD]"
    padding = getattr(tok, "padding", None)
    if isinstance(padding, dict):
        pad_id = int(padding.get("pad_id", pad_id) or 0)
        pad_token = str(padding.get("pad_token") or pad_token)
    tok.enable_truncation(max_length=int(seq))
    tok.enable_padding(length=int(seq), pad_id=pad_id, pad_token=pad_token)
    return fe_model


def _register_coreml_static_alias(model: str, batch: int, seq: int) -> None:
    """Custom FastEmbed models are in-process only — re-register each runtime."""
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType
    from pipeline.accel import CODERANK_HF_ONNX

    rel = f"onnx/model.coreml_b{batch}_s{seq}_norot0.onnx"
    try:
        TextEmbedding.add_custom_model(
            model=model,
            pooling=PoolingType.MEAN,
            normalization=True,
            sources=ModelSource(hf=CODERANK_HF_ONNX),
            dim=768,
            model_file=rel,
            description="CodeRankEmbed CoreML-static ONNX",
            license="mit",
            size_in_gb=0.27,
        )
    except ValueError as exc:
        if "already registered" not in str(exc).lower():
            raise


def coreml_model_name(default: str) -> str:
    marker = Path.home() / ".context-engine" / "coderank_coreml_static.json"
    if not marker.is_file():
        return default
    try:
        import json

        data = json.loads(marker.read_text(encoding="utf-8"))
        name = str(data.get("model") or default)
        _register_coreml_static_alias(
            name,
            int(data.get("batch") or COREML_STATIC_BATCH),
            int(data.get("seq") or COREML_STATIC_SEQ),
        )
        return name
    except Exception:  # noqa: BLE001
        return default
