"""CoreML Mac GPU static-shape helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.accel import AccelProfile
from pipeline.coreml_mac import (
    COREML_STATIC_BATCH,
    coreml_provider_options,
    coreml_providers,
    pad_embed_batch,
    static_embed_batch_size,
)


def test_coreml_provider_options_require_static_shapes():
    opts = coreml_provider_options(compute_units="CPUAndGPU")
    assert opts["RequireStaticInputShapes"] == "1"
    assert opts["MLComputeUnits"] == "CPUAndGPU"
    assert opts["ModelFormat"] == "MLProgram"
    # Invalid ORT string options cause EP init failure + silent CPU fallback on Mac.
    assert "UseCPUAndGPU" not in opts
    assert "CreateMLProgram" not in opts


def test_coreml_gpu_only_excludes_cpu_provider(monkeypatch):
    monkeypatch.setenv("CTX_MAC_GPU_ONLY", "1")
    prof = AccelProfile(profile="coreml", provider="CoreMLExecutionProvider")
    providers = coreml_providers(prof)
    assert len(providers) == 1
    assert providers[0][0] == "CoreMLExecutionProvider"


def test_pad_embed_batch_pads_to_static_size():
    out = pad_embed_batch(["a", "b"], 4)
    assert len(out) == 4
    assert out[:2] == ["a", "b"]
    assert out[2:] == ["b", "b"]


def test_static_embed_batch_size_for_coreml():
    prof = AccelProfile(
        profile="coreml",
        provider="CoreMLExecutionProvider",
        batch_calibration={"coreml_static_batch": COREML_STATIC_BATCH},
    )
    assert static_embed_batch_size(prof, 16) == COREML_STATIC_BATCH


def _nomic_rotary_toy(*, freq_len: int, head_dim: int):
    """Minimal CodeRank/Nomic-BERT remainder pattern: Concat(rotated, Slice(x[rotary_dim:]))."""
    import numpy as np
    from onnx import TensorProto, helper, numpy_helper

    def cnode(out_name: str, arr):
        tensor = numpy_helper.from_array(np.asarray(arr), name=out_name + "_t")
        return helper.make_node("Constant", [], [out_name], name=out_name + "_n", value=tensor)

    nodes = [
        cnode("inv_freq", np.arange(freq_len, dtype=np.float32) + 1.0),
        cnode("pos", np.arange(2, dtype=np.float32)),
        helper.make_node(
            "Einsum",
            ["pos", "inv_freq"],
            ["ang"],
            name="l0/attn/rotary_emb/Einsum",
            equation="i,j->ij",
        ),
        helper.make_node("Cos", ["ang"], ["cos"], name="l0/attn/rotary_emb/Cos"),
        helper.make_node(
            "Cast",
            ["cos"],
            ["cos_f"],
            name="l0/attn/rotary_emb/Cast_1",
            to=TensorProto.FLOAT,
        ),
        helper.make_node("Shape", ["cos_f"], ["cshape"], name="l0/attn/rotary_emb/Shape_1"),
        cnode("gidx", np.int64(1)),
        helper.make_node(
            "Gather", ["cshape", "gidx"], ["d1"], name="l0/attn/rotary_emb/Gather_2"
        ),
        cnode("two", np.int64(2)),
        helper.make_node("Mul", ["d1", "two"], ["rd"], name="l0/attn/rotary_emb/Mul"),
        cnode("uax", np.array([0], dtype=np.int64)),
        helper.make_node(
            "Unsqueeze", ["rd", "uax"], ["starts"], name="l0/attn/rotary_emb/Unsqueeze_9"
        ),
        cnode("ends", np.array([9223372036854775807], dtype=np.int64)),
        cnode("axes", np.array([3], dtype=np.int64)),
        cnode("steps", np.array([1], dtype=np.int64)),
        cnode("qshape", np.array([1, 2, 12, head_dim], dtype=np.int64)),
        helper.make_node("Reshape", ["x", "qshape"], ["q"], name="l0/attn/Reshape"),
        helper.make_node("Identity", ["q"], ["rotated"], name="l0/attn/rotary_emb/Add_1"),
        helper.make_node(
            "Slice",
            ["q", "starts", "ends", "axes", "steps"],
            ["rem"],
            name="l0/attn/rotary_emb/Slice_5",
        ),
        helper.make_node(
            "Concat",
            ["rotated", "rem"],
            ["cat"],
            name="l0/attn/rotary_emb/Concat_3",
            axis=-1,
        ),
        helper.make_node("Identity", ["cat"], ["y"], name="tail"),
    ]
    x = helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 2, 12, head_dim])
    y = helper.make_tensor_value_info("y", TensorProto.FLOAT, [1, 2, 12, head_dim])
    graph = helper.make_graph(nodes, "g", [x], [y])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 10
    return model


def _coderank_onnx_cache() -> Path | None:
    from pipeline.coreml_mac import find_coderank_onnx

    from fastembed.common.utils import define_cache_dir

    root = Path(define_cache_dir())
    found = find_coderank_onnx(root)
    if found is not None:
        return found
    hub = Path.home() / ".cache" / "huggingface" / "hub"
    if hub.is_dir():
        for snap in hub.glob("models--jamie8johnson--CodeRankEmbed-onnx/snapshots/*/onnx"):
            hit = find_coderank_onnx(snap.parent)
            if hit is not None:
                return hit
    return None


def test_bypass_empty_rotary_remainders_full_head_dim():
    import onnx

    from pipeline.coreml_mac import (
        bypass_empty_rotary_remainders,
        rotary_remainder_concat_nodes,
    )

    model = _nomic_rotary_toy(freq_len=32, head_dim=64)
    assert rotary_remainder_concat_nodes(model)
    n = bypass_empty_rotary_remainders(model)
    assert n == 1
    names = [node.name for node in model.graph.node]
    assert "l0/attn/rotary_emb/Concat_3" not in names
    assert "l0/attn/rotary_emb/Slice_5" not in names
    tail = next(node for node in model.graph.node if node.name == "tail")
    assert list(tail.input) == ["rotated"]
    assert rotary_remainder_concat_nodes(model) == []
    onnx.checker.check_model(model)


def test_bypass_empty_rotary_remainders_partial_rotary_kept():
    from pipeline.coreml_mac import (
        bypass_empty_rotary_remainders,
        rotary_remainder_concat_nodes,
    )

    model = _nomic_rotary_toy(freq_len=16, head_dim=64)
    before = {node.name for node in model.graph.node}
    n = bypass_empty_rotary_remainders(model)
    assert n == 0
    after = {node.name for node in model.graph.node}
    assert "l0/attn/rotary_emb/Concat_3" in after
    assert "l0/attn/rotary_emb/Slice_5" in after
    assert before == after
    # Remainder is non-empty, so the empty-remainder matcher must not fire.
    assert rotary_remainder_concat_nodes(model) == []


def test_bypass_empty_rotary_remainders_numerical_equivalence():
    import numpy as np
    import onnx
    import onnxruntime as ort

    from pipeline.coreml_mac import bypass_empty_rotary_remainders

    original = _nomic_rotary_toy(freq_len=32, head_dim=64)
    patched = _nomic_rotary_toy(freq_len=32, head_dim=64)
    assert bypass_empty_rotary_remainders(patched) == 1
    onnx.checker.check_model(patched)
    x = np.random.randn(1, 2, 12, 64).astype(np.float32)
    sess_a = ort.InferenceSession(original.SerializeToString(), providers=["CPUExecutionProvider"])
    sess_b = ort.InferenceSession(patched.SerializeToString(), providers=["CPUExecutionProvider"])
    out_a = sess_a.run(None, {"x": x})[0]
    out_b = sess_b.run(None, {"x": x})[0]
    np.testing.assert_allclose(out_a, out_b, rtol=1e-5, atol=1e-6)


def test_bypass_does_not_remove_non_rotary_concat():
    from onnx import TensorProto, helper

    from pipeline.coreml_mac import bypass_empty_rotary_remainders

    x = helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 4])
    y = helper.make_tensor_value_info("y", TensorProto.FLOAT, [1, 8])
    graph = helper.make_graph(
        [
            helper.make_node("Concat", ["x", "x"], ["y"], name="unrelated/Concat", axis=-1),
        ],
        "g",
        [x],
        [y],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    assert bypass_empty_rotary_remainders(model) == 0
    assert [node.name for node in model.graph.node] == ["unrelated/Concat"]


def test_patched_coderank_graph_has_no_empty_rotary_remainders():
    import sys

    if sys.platform != "darwin":
        pytest.skip("CodeRank CoreML graph patch verified on macOS — see docs/macos-deferred-verification.md")
    import onnx
    pytest.importorskip("onnxruntime")

    from pipeline.coreml_mac import (
        bypass_empty_rotary_remainders,
        rotary_remainder_concat_nodes,
    )

    src = _coderank_onnx_cache()
    if src is None:
        pytest.skip("CodeRank ONNX is not in the FastEmbed/HF cache")
    model = onnx.load(str(src))
    n = bypass_empty_rotary_remainders(model)
    assert n == 24  # 12 layers × Q Concat_3 + K Concat_7
    onnx.checker.check_model(model)
    leftover = rotary_remainder_concat_nodes(model)
    assert leftover == []
    names = [node.name for node in model.graph.node]
    assert not any(name.endswith("Slice_5") for name in names)
    assert not any(name.endswith("Slice_11") for name in names)


def test_patched_coderank_embeddings_match_original(tmp_path):
    import sys

    if sys.platform != "darwin":
        pytest.skip("CodeRank CoreML embed parity verified on macOS — see docs/macos-deferred-verification.md")
    import numpy as np
    import onnx
    import onnxruntime as ort

    from pipeline.coreml_mac import bypass_empty_rotary_remainders

    src = _coderank_onnx_cache()
    if src is None:
        pytest.skip("CodeRank ONNX is not in the FastEmbed/HF cache")
    patched = onnx.load(str(src))
    assert bypass_empty_rotary_remainders(patched) == 24
    patched_path = tmp_path / "coderank_norot0.onnx"
    onnx.save(patched, str(patched_path))
    feeds = {}
    rng = np.random.default_rng(0)
    model_in = onnx.load(str(src), load_external_data=False)
    for inp in model_in.graph.input:
        dims = []
        for dim in inp.type.tensor_type.shape.dim:
            dims.append(int(dim.dim_value) if dim.dim_value else (2 if dim.dim_param else 1))
        if not dims:
            dims = [1, 8]
        dims[0] = 1
        if len(dims) > 1:
            dims[1] = min(dims[1] if dims[1] > 0 else 8, 8)
        feeds[inp.name] = rng.integers(0, 100, size=dims, dtype=np.int64)
        if "mask" in inp.name:
            feeds[inp.name] = np.ones(dims, dtype=np.int64)
        if "token_type" in inp.name:
            feeds[inp.name] = np.zeros(dims, dtype=np.int64)
    sess_a = ort.InferenceSession(str(src), providers=["CPUExecutionProvider"])
    sess_b = ort.InferenceSession(str(patched_path), providers=["CPUExecutionProvider"])
    in_names = [i.name for i in sess_a.get_inputs()]
    payload = {name: feeds[name] for name in in_names if name in feeds}
    out_a = sess_a.run(None, payload)
    out_b = sess_b.run(None, payload)
    assert len(out_a) == len(out_b)
    for a, b in zip(out_a, out_b):
        np.testing.assert_allclose(a, b, rtol=1e-4, atol=1e-5)


def test_refuse_coreml_cpu_fallback_raises_when_ep_missing(monkeypatch):
    from pipeline.accel import _refuse_coreml_cpu_fallback

    monkeypatch.setenv("CTX_MAC_GPU_ONLY", "1")
    monkeypatch.setattr(
        "pipeline.accel.ort_available_providers",
        lambda: ["CPUExecutionProvider"],
    )
    prof = AccelProfile(profile="coreml", provider="CoreMLExecutionProvider")
    with pytest.raises(RuntimeError, match="Refusing CPU fallback"):
        _refuse_coreml_cpu_fallback(prof)


def test_bind_coreml_tokenizer_sets_fixed_length():
    from pipeline.coreml_mac import bind_coreml_tokenizer

    class _Tok:
        def __init__(self):
            self.padding = {"pad_id": 0, "pad_token": "[PAD]"}
            self.trunc = None
            self.pad = None

        def enable_truncation(self, **kwargs):
            self.trunc = kwargs

        def enable_padding(self, **kwargs):
            self.pad = kwargs

    class _Inner:
        tokenizer = _Tok()

    class _Fe:
        model = _Inner()

    fe = _Fe()
    bind_coreml_tokenizer(fe, seq=512)
    assert fe.model.tokenizer.trunc == {"max_length": 512}
    assert fe.model.tokenizer.pad["length"] == 512
    assert fe.model.tokenizer.pad["pad_id"] == 0


def test_install_patched_onnx_into_fastembed_cache(monkeypatch, tmp_path):
    from pipeline.coreml_mac import install_patched_onnx_into_fastembed_cache

    fe = tmp_path / "fastembed_cache" / "models--x" / "snapshots" / "abc" / "onnx"
    fe.mkdir(parents=True)
    (fe / "model_fp16.onnx").write_bytes(b"src")
    patched = tmp_path / "hub" / "model.coreml_b20_s512.onnx"
    patched.parent.mkdir(parents=True)
    patched.write_bytes(b"patched-onnx")
    monkeypatch.setattr(
        "pipeline.coreml_mac._fastembed_cache_root",
        lambda: tmp_path / "fastembed_cache",
    )

    dest = install_patched_onnx_into_fastembed_cache(patched)
    assert dest == fe / "model.coreml_b20_s512.onnx"
    assert dest.read_bytes() == b"patched-onnx"


def test_assert_coreml_ep_active_rejects_cpu_session(monkeypatch, tmp_path):
    import onnxruntime as ort

    from pipeline.coreml_mac import assert_coreml_ep_active

    class _Sess:
        def get_providers(self):
            return ["CPUExecutionProvider"]

    monkeypatch.setattr(ort, "InferenceSession", lambda *_a, **_k: _Sess())
    dummy = tmp_path / "model.onnx"
    dummy.write_bytes(b"not-a-real-onnx")
    with pytest.raises(RuntimeError, match="Refusing CPU fallback"):
        assert_coreml_ep_active(dummy, [("CoreMLExecutionProvider", {})])
