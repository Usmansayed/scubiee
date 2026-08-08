"""Unit tests for TurboQuant + Merkle (no Graphify/Ollama required)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from pipeline.merkle import diff_hashes, root_hash, scan_file_hashes
from pipeline.turbo_quant import CompressedEmbeddingStore, TurboQuantCodec


def test_merkle_detects_change(tmp_path: Path):
    (tmp_path / "a.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y=2\n", encoding="utf-8")
    h1 = scan_file_hashes(tmp_path)
    (tmp_path / "a.py").write_text("x=2\n", encoding="utf-8")
    h2 = scan_file_hashes(tmp_path)
    d = diff_hashes(h1, h2)
    assert d.modified == ["a.py"]
    assert d.unchanged is False
    assert root_hash(h1) != root_hash(h2)


def test_turboquant_roundtrip_dim():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(32, 64)).astype(np.float32)
    codec = TurboQuantCodec(dim=64, bits=4, seed=7)
    blob = codec.quantize(x)
    y = codec.dequantize(blob)
    assert y.shape == x.shape
    # Cosine should stay reasonably aligned on average
    x_n = x / np.linalg.norm(x, axis=1, keepdims=True)
    y_n = y / np.linalg.norm(y, axis=1, keepdims=True)
    sims = (x_n * y_n).sum(axis=1)
    assert float(sims.mean()) > 0.7


def test_compressed_store_save_load(tmp_path: Path):
    rng = np.random.default_rng(1)
    x = rng.normal(size=(10, 32)).astype(np.float32)
    store = CompressedEmbeddingStore(dim=32, bits=4)
    store.add(x)
    path = tmp_path / "tq.npz"
    store.save(path)
    loaded = CompressedEmbeddingStore.load(path)
    assert loaded.ntotal == 10
    assert loaded.to_float32().shape == (10, 32)
