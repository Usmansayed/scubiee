"""MLX is a selectable extra backend; CPU/CoreML stay in place."""

from __future__ import annotations

import numpy as np
import pytest

from pipeline.accel import AccelProfile
from pipeline.embedder import _choose_backend
from pipeline.preflight import validate_provider


def test_choose_backend_mlx_from_env(monkeypatch):
    monkeypatch.setenv("CTX_EMBED_BACKEND", "mlx")
    pytest.importorskip("mlx")
    assert _choose_backend("nomic-ai/CodeRankEmbed", None) == "mlx"


def test_choose_backend_still_defaults_to_fastembed(monkeypatch):
    monkeypatch.delenv("CTX_EMBED_BACKEND", raising=False)
    monkeypatch.setenv("CTX_MLX", "0")
    # Saved accel is CPU/CoreML FastEmbed — MLX must not steal when disabled.
    from pipeline import accel
    from pipeline.accel import AccelProfile

    monkeypatch.setattr(
        accel,
        "resolve_runtime",
        lambda: AccelProfile(profile="cpu", provider="CPUExecutionProvider", backend="fastembed"),
    )
    assert _choose_backend("nomic-ai/CodeRankEmbed", None) in {"fastembed", "coderank"}


def test_require_mlx_gpu_refuses_cpu_env(monkeypatch):
    monkeypatch.setenv("CTX_MLX_DEVICE", "cpu")
    from pipeline.mlx_mac import require_mlx_gpu

    with pytest.raises(RuntimeError, match="Apple GPU"):
        require_mlx_gpu()


def test_validate_provider_mlx_does_not_require_ort():
    profile = AccelProfile(profile="mlx", provider="MLX", backend="mlx")
    validation = validate_provider(
        profile,
        finder=lambda name: object() if name == "mlx" else None,
        provider_getter=lambda: (_ for _ in ()).throw(RuntimeError("ort should not be queried")),
        warmup=lambda _p: (_ for _ in ()).throw(RuntimeError("ort warmup should not run")),
    )
    assert validation.ok is True
    assert validation.provider_available is True


def test_resolve_runtime_mlx_overlay_does_not_rewrite_accel(tmp_path, monkeypatch):
    from pipeline import accel

    saved = AccelProfile(
        profile="cpu",
        provider="CPUExecutionProvider",
        backend="fastembed",
        batch_size=16,
        reason="production cpu",
    )
    path = tmp_path / "accel.json"
    monkeypatch.setattr(accel, "ACCEL_PATH", path)
    accel.save_accel(saved, path)
    before = path.read_text(encoding="utf-8")
    monkeypatch.setenv("CTX_EMBED_BACKEND", "mlx")
    monkeypatch.setenv("CTX_EMBED_BATCH", "48")
    overlay = accel.resolve_runtime()
    assert overlay.profile == "mlx"
    assert overlay.backend == "mlx"
    assert overlay.provider == "MLX"
    assert overlay.batch_size == 48
    assert path.read_text(encoding="utf-8") == before
    on_disk = accel.load_accel(path)
    assert on_disk is not None
    assert on_disk.profile == "cpu"
    assert on_disk.backend == "fastembed"


def test_tokenize_pads_to_batch_max_not_512():
    pytest.importorskip("tokenizers")
    from pipeline.mlx_mac import tokenize_batch

    try:
        ids, mask = tokenize_batch(["hi", "def foo():\n    return 1\n"])
    except FileNotFoundError:
        pytest.skip("CodeRank tokenizer is not cached")
    assert ids.shape == mask.shape
    assert 2 <= ids.shape[1] < 512
    assert np.all((mask == 0) | (mask == 1))
    pad_positions = mask == 0
    if pad_positions.any():
        assert np.all(ids[pad_positions] == 0)
    lengths = mask.sum(axis=1)
    assert int(ids.shape[1]) == int(lengths.max())


def test_tokenize_truncates_to_512():
    pytest.importorskip("tokenizers")
    from pipeline.mlx_mac import CODERANK_MAX_SEQ, tokenize_batch

    try:
        ids, mask = tokenize_batch(["token " * 4000])
    except FileNotFoundError:
        pytest.skip("CodeRank tokenizer is not cached")
    assert ids.shape[1] <= CODERANK_MAX_SEQ
    assert mask.shape == ids.shape
    assert int(mask.sum()) <= CODERANK_MAX_SEQ
