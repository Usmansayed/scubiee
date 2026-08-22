"""Production embed weights are FP16-only on every OS/hardware path."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.accel import (
    CODERANK_HF_ONNX,
    CODERANK_MODEL,
    CODERANK_ONNX_FILE,
    AccelProfile,
    load_accel,
    register_coderank,
    save_accel,
)
from pipeline.coreml_mac import find_coderank_onnx, is_coderank_onnx_dir
from pipeline.mlx_mac import resolve_embed_dtype
from pipeline.memory_budget import apply_index_memory_budget, background_budget


def test_coderank_onnx_file_is_fp16() -> None:
    assert CODERANK_ONNX_FILE == "onnx/model_fp16.onnx"


def test_register_coderank_points_fastembed_at_fp16(monkeypatch) -> None:
    pytest.importorskip("fastembed")
    from fastembed import TextEmbedding

    captured: dict[str, object] = {}

    def _add_custom_model(**kwargs):
        captured.update(kwargs)
        raise ValueError("already registered")

    monkeypatch.setattr(TextEmbedding, "add_custom_model", _add_custom_model)
    # Empty custom registry so register attempts add_custom_model.
    from fastembed.text.custom_text_embedding import CustomTextEmbedding

    CustomTextEmbedding.SUPPORTED_MODELS[:] = [
        m
        for m in CustomTextEmbedding.SUPPORTED_MODELS
        if str(getattr(m, "model", "")).lower() != CODERANK_MODEL.lower()
    ]
    register_coderank()
    assert captured["model_file"] == "onnx/model_fp16.onnx"
    assert "FP16" in str(captured["description"])


def test_register_coderank_upgrades_stale_fp32_registry() -> None:
    pytest.importorskip("fastembed")
    from fastembed.common.model_description import DenseModelDescription, ModelSource, PoolingType
    from fastembed.text.custom_text_embedding import CustomTextEmbedding, PostprocessingConfig

    CustomTextEmbedding.SUPPORTED_MODELS[:] = [
        m
        for m in CustomTextEmbedding.SUPPORTED_MODELS
        if str(getattr(m, "model", "")).lower() != CODERANK_MODEL.lower()
    ]
    CustomTextEmbedding.SUPPORTED_MODELS.append(
        DenseModelDescription(
            model=CODERANK_MODEL,
            sources=ModelSource(hf=CODERANK_HF_ONNX),
            dim=768,
            model_file="onnx/model.onnx",
            description="stale FP32",
            license="mit",
            size_in_GB=0.5,
            additional_files=[],
        )
    )
    CustomTextEmbedding.POSTPROCESSING_MAPPING[CODERANK_MODEL] = PostprocessingConfig(
        pooling=PoolingType.MEAN,
        normalization=True,
    )
    register_coderank()
    hit = next(
        m
        for m in CustomTextEmbedding.SUPPORTED_MODELS
        if str(m.model).lower() == CODERANK_MODEL.lower()
    )
    assert hit.model_file == CODERANK_ONNX_FILE
    assert "FP16" in hit.description


def test_find_coderank_onnx_prefers_fp16_and_ignores_fp32(tmp_path: Path) -> None:
    onnx_dir = tmp_path / "onnx"
    onnx_dir.mkdir()
    (onnx_dir / "model.onnx").write_bytes(b"fp32")
    (onnx_dir / "model_fp16.onnx").write_bytes(b"fp16")
    found = find_coderank_onnx(tmp_path)
    assert found == onnx_dir / "model_fp16.onnx"
    assert is_coderank_onnx_dir(onnx_dir) is True


def test_find_coderank_onnx_skips_fp32_only_cache(tmp_path: Path) -> None:
    onnx_dir = tmp_path / "onnx"
    onnx_dir.mkdir()
    (onnx_dir / "model.onnx").write_bytes(b"fp32")
    assert find_coderank_onnx(tmp_path) is None
    assert is_coderank_onnx_dir(onnx_dir) is True  # still a CodeRank dir (legacy file present)


def test_resolve_embed_dtype_ignores_fp32_request(monkeypatch) -> None:
    monkeypatch.setenv("CTX_MLX_DTYPE", "float32")
    assert resolve_embed_dtype("float32") == "float16"


def test_memory_budget_forces_fp16_dtype(monkeypatch) -> None:
    monkeypatch.setenv("CTX_MLX_DTYPE", "float32")
    apply_index_memory_budget(background_budget())
    import os

    assert os.environ["CTX_MLX_DTYPE"] == "float16"


def test_load_accel_rewrites_stale_onnx_file(tmp_path: Path) -> None:
    path = tmp_path / "accel.json"
    profile = AccelProfile(
        profile="cpu",
        provider="CPUExecutionProvider",
        onnx_file="onnx/model.onnx",
    )
    save_accel(profile, path)
    loaded = load_accel(path)
    assert loaded is not None
    assert loaded.onnx_file == CODERANK_ONNX_FILE
    # Re-read disk: save_accel also forces FP16 into the written JSON.
    assert '"onnx/model_fp16.onnx"' in path.read_text(encoding="utf-8")


def test_install_patched_onnx_accepts_fp16_only_cache(monkeypatch, tmp_path: Path) -> None:
    from pipeline.coreml_mac import install_patched_onnx_into_fastembed_cache

    fe = tmp_path / "fastembed_cache" / "models--x" / "snapshots" / "abc" / "onnx"
    fe.mkdir(parents=True)
    (fe / "model_fp16.onnx").write_bytes(b"fp16")
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


def test_ensure_coderank_fp16_converts_from_fp32(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("onnx")
    from pipeline.accel import CODERANK_FP16_MIN_BYTES, ensure_coderank_fp16_onnx

    cache = tmp_path / "fastembed_cache"
    onnx_dir = (
        cache
        / "models--jamie8johnson--CodeRankEmbed-onnx"
        / "snapshots"
        / "abc"
        / "onnx"
    )
    onnx_dir.mkdir(parents=True)
    fp32 = onnx_dir / "model.onnx"
    fp32.write_bytes(b"x" * (CODERANK_FP16_MIN_BYTES + 1))

    def _fake_convert(src: Path, dest: Path) -> None:
        dest.write_bytes(b"y" * CODERANK_FP16_MIN_BYTES)

    monkeypatch.setattr("pipeline.accel.fastembed_cache_root", lambda: cache)
    monkeypatch.setattr("pipeline.accel._download_coderank_source_onnx", lambda _root: fp32)
    monkeypatch.setattr("pipeline.accel._convert_coderank_fp32_onnx_to_fp16", _fake_convert)
    out = ensure_coderank_fp16_onnx()
    assert out == onnx_dir / "model_fp16.onnx"
    assert out.stat().st_size >= CODERANK_FP16_MIN_BYTES


def test_saved_accel_needs_reconfigure_after_cpu_fallback(monkeypatch) -> None:
    from pipeline.accel import AccelProfile, saved_accel_needs_reconfigure

    monkeypatch.setattr("pipeline.accel.coderank_fp16_onnx_ready", lambda *_a, **_k: True)
    existing = AccelProfile(
        profile="cpu",
        provider="CPUExecutionProvider",
        detected={
            "os": "Windows",
            "gpus": [{"name": "AMD Radeon RX 6500M"}],
            "suggested_dml_device_id": 1,
        },
    )
    assert saved_accel_needs_reconfigure(existing) is True


def test_saved_accel_needs_reconfigure_when_fastembed_missing(monkeypatch) -> None:
    from pipeline.accel import AccelProfile, saved_accel_needs_reconfigure

    monkeypatch.setattr("pipeline.accel._requirement_satisfied", lambda spec: spec != "fastembed>=0.4")
    monkeypatch.setattr("pipeline.accel.coderank_fp16_onnx_ready", lambda *_a, **_k: True)
    existing = AccelProfile(profile="dml", provider="DmlExecutionProvider")
    assert saved_accel_needs_reconfigure(existing) is True


def test_coderank_fp16_ready_without_fastembed_import(monkeypatch, tmp_path: Path) -> None:
    from pipeline.accel import CODERANK_FP16_MIN_BYTES, coderank_fp16_onnx_ready, default_fastembed_cache_root

    def _boom() -> Path:
        raise ImportError("No module named 'fastembed'")

    monkeypatch.setattr("pipeline.accel.fastembed_cache_root", _boom)
    cache = tmp_path / "cache"
    snap = cache / "models--jamie8johnson--CodeRankEmbed-onnx" / "snapshots" / "abc"
    onnx_dir = snap / "onnx"
    onnx_dir.mkdir(parents=True)
    fp16 = onnx_dir / "model_fp16.onnx"
    fp16.write_bytes(b"x" * CODERANK_FP16_MIN_BYTES)
    assert coderank_fp16_onnx_ready(cache_root=cache) is True
    assert default_fastembed_cache_root().name == "fastembed"
