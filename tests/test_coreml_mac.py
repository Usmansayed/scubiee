"""CoreML Mac GPU static-shape helpers."""

from __future__ import annotations

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
