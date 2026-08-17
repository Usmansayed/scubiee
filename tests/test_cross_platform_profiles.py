from __future__ import annotations

from dataclasses import replace

import pytest

from pipeline.accel import AccelProfile, recommend_profile


@pytest.mark.parametrize(
    ("os_name", "nvidia", "gpus", "providers", "expected"),
    [
        (
            "Windows",
            False,
            [{"name": "AMD Radeon", "adapter_ram": 8_000_000_000}],
            ["DmlExecutionProvider", "CPUExecutionProvider"],
            "dml",
        ),
        (
            "Linux",
            True,
            [{"name": "NVIDIA RTX", "adapter_ram": 12_000_000_000}],
            ["CUDAExecutionProvider", "CPUExecutionProvider"],
            "cuda",
        ),
        (
            "Linux",
            False,
            [{"name": "AMD Radeon", "adapter_ram": 8_000_000_000}],
            ["CPUExecutionProvider"],
            "cpu",
        ),
        (
            "Darwin",
            False,
            [{"name": "Apple M3", "adapter_ram": 8_000_000_000}],
            ["CPUExecutionProvider"],
            "cpu",
        ),
    ],
)
def test_simulated_platform_profile_is_provider_validated_and_warmed(
    os_name: str,
    nvidia: bool,
    gpus: list[dict[str, object]],
    providers: list[str],
    expected: str,
) -> None:
    from pipeline.preflight import validate_provider

    profile = recommend_profile(
        {
            "os": os_name,
            "nvidia": nvidia,
            "gpus": gpus,
            "suggested_dml_device_id": 0,
        }
    )
    warmed: list[str] = []

    validation = validate_provider(
        profile,
        finder=lambda name: object() if name in {"fastembed", "onnxruntime"} else None,
        provider_getter=lambda: providers,
        warmup=lambda saved: warmed.append(saved.provider) or True,
    )

    assert profile.profile == expected
    assert validation.ok is True
    assert validation.provider_available is True
    assert validation.model_warm is True
    assert warmed == [profile.provider]


@pytest.mark.parametrize(
    ("os_name", "gpu_name"),
    [("Linux", "AMD Radeon 7900"), ("Darwin", "Apple M3 Max")],
)
def test_os_or_unsupported_gpu_name_alone_never_claims_gpu_support(
    os_name: str,
    gpu_name: str,
) -> None:
    profile = recommend_profile(
        {
            "os": os_name,
            "nvidia": False,
            "gpus": [{"name": gpu_name, "adapter_ram": 16_000_000_000}],
        }
    )

    assert profile.profile == "cpu"
    assert profile.provider == "CPUExecutionProvider"


def test_provider_presence_without_model_warmup_fails_validation() -> None:
    from pipeline.preflight import validate_provider

    profile = AccelProfile(
        profile="cuda",
        provider="CUDAExecutionProvider",
        batch_size=16,
    )

    validation = validate_provider(
        profile,
        finder=lambda _name: object(),
        provider_getter=lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"],
        warmup=lambda _profile: (_ for _ in ()).throw(RuntimeError("model failed")),
    )

    assert validation.ok is False
    assert validation.provider_available is True
    assert validation.model_warm is False
    assert "model failed" in validation.detail


def test_validation_and_recommendation_do_not_reconfigure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pipeline import accel
    from pipeline.preflight import recommended_server_command, validate_provider

    profile = AccelProfile(
        profile="cpu",
        provider="CPUExecutionProvider",
        batch_size=8,
    )
    for name in ("configure", "recommend_profile", "calibrate_batch"):
        monkeypatch.setattr(
            accel,
            name,
            lambda *args, _name=name, **kwargs: pytest.fail(
                f"diagnostics must not call {_name}"
            ),
        )

    validation = validate_provider(
        profile,
        finder=lambda _name: object(),
        provider_getter=lambda: ["CPUExecutionProvider"],
        warmup=lambda _profile: True,
    )

    assert validation.ok is True
    assert recommended_server_command(profile) == "python -m pipeline serve"
    assert recommended_server_command(None) == "python -m pipeline init"


def test_missing_hardware_lane_is_skipped_not_passed() -> None:
    from pipeline.certify import certify_platform_lane

    check = certify_platform_lane(
        "linux_cuda",
        AccelProfile(profile="cuda", provider="CUDAExecutionProvider"),
        hardware_available=False,
        providers=[],
        warmup=lambda _profile: True,
    )

    assert check["status"] == "skipped"
    assert check["ok"] is False
    assert check["required"] is False


def test_available_hardware_lane_requires_successful_warmup() -> None:
    from pipeline.certify import certify_platform_lane

    profile = AccelProfile(profile="dml", provider="DmlExecutionProvider")
    failed = certify_platform_lane(
        "windows_dml",
        profile,
        hardware_available=True,
        providers=["DmlExecutionProvider", "CPUExecutionProvider"],
        warmup=lambda _profile: False,
    )
    passed = certify_platform_lane(
        "windows_dml",
        replace(profile),
        hardware_available=True,
        providers=["DmlExecutionProvider", "CPUExecutionProvider"],
        warmup=lambda _profile: True,
    )

    assert failed["status"] == "failed"
    assert failed["ok"] is False
    assert passed["status"] == "passed"
    assert passed["ok"] is True
