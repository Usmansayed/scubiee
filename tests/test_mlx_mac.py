"""Numerical checks for the isolated CodeRank MLX path (skipped without MLX/weights)."""

from __future__ import annotations

import numpy as np
import pytest

mlx = pytest.importorskip("mlx")


def test_mlx_device_is_gpu():
    from pipeline.mlx_mac import mlx_device_report

    report = mlx_device_report()
    assert report["metal_available"] is True
    assert report["gpu_compute"] is True
    assert "gpu" in report["default_device"].lower()


def test_mlx_embeddings_match_cpu_ort():
    from pathlib import Path

    import onnxruntime as ort
    from fastembed.common.utils import mean_pooling, normalize

    from pipeline.coreml_mac import _fastembed_cache_root, find_coderank_onnx
    from pipeline.mlx_mac import CodeRankMLX, ensure_mlx_weights, tokenize_batch

    src = find_coderank_onnx(Path(_fastembed_cache_root()))
    if src is None:
        pytest.skip("CodeRank ONNX is not cached")
    ensure_mlx_weights(src)
    texts = [
        "hi",
        "def foo():\n    return 1\n",
        "class Repo:\n    def index(self, path: str) -> None:\n        print(path)\n",
        "x" * 400,
        "for i in range(32):\n    print(i * i)\n",
    ]
    ids, mask = tokenize_batch(texts, seq=96)
    sess = ort.InferenceSession(str(src), providers=["CPUExecutionProvider"])
    feeds = {"input_ids": ids, "attention_mask": mask}
    names = [i.name for i in sess.get_inputs()]
    payload = {k: v for k, v in feeds.items() if k in names}
    token_emb = sess.run(None, payload)[0]
    ref = normalize(mean_pooling(token_emb, mask))
    pred = CodeRankMLX().embed_ids(ids, mask)
    diff = np.abs(ref - pred)
    cos = np.sum(ref * pred, axis=1)
    assert float(diff.max()) < 2e-3
    assert float(diff.mean()) < 5e-4
    assert float(cos.min()) > 0.9999


def test_mlx_dynamic_padding_matches_cpu_ort():
    from pathlib import Path

    import onnxruntime as ort
    from fastembed.common.utils import mean_pooling, normalize

    from pipeline.coreml_mac import _fastembed_cache_root, find_coderank_onnx
    from pipeline.mlx_mac import CodeRankMLX, ensure_mlx_weights, tokenize_batch

    src = find_coderank_onnx(Path(_fastembed_cache_root()))
    if src is None:
        pytest.skip("CodeRank ONNX is not cached")
    ensure_mlx_weights(src)
    texts = [
        "hi",
        "def foo():\n    return 1\n",
        "class Repo:\n    def index(self, path: str) -> None:\n        print(path)\n",
        "x" * 400,
        "for i in range(32):\n    print(i * i)\n",
    ]
    ids, mask = tokenize_batch(texts)
    assert ids.shape[1] < 512
    assert int(ids.shape[1]) == int(mask.sum(axis=1).max())
    sess = ort.InferenceSession(str(src), providers=["CPUExecutionProvider"])
    feeds = {"input_ids": ids, "attention_mask": mask}
    names = [i.name for i in sess.get_inputs()]
    payload = {k: v for k, v in feeds.items() if k in names}
    token_emb = sess.run(None, payload)[0]
    ref = normalize(mean_pooling(token_emb, mask))
    pred = CodeRankMLX().embed_ids(ids, mask)
    diff = np.abs(ref - pred)
    cos = np.sum(ref * pred, axis=1)
    assert float(diff.max()) < 2e-3
    assert float(diff.mean()) < 5e-4
    assert float(cos.min()) > 0.9999
