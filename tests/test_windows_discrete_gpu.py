"""Windows DirectML must require discrete AMD/NVIDIA GPUs."""

from __future__ import annotations

import pytest

from pipeline.accel import (
    _is_windows_discrete_amd_or_nvidia,
    recommend_profile,
)


@pytest.mark.parametrize(
    "name",
    [
        "NVIDIA GeForce RTX 4070",
        "NVIDIA GeForce GTX 1660 Ti",
        "NVIDIA Quadro T1000",
        "AMD Radeon RX 7800 XT",
        "AMD Radeon RX 580",
        "Radeon Pro W6800",
    ],
)
def test_discrete_amd_nvidia_names_match(name: str) -> None:
    assert _is_windows_discrete_amd_or_nvidia({"name": name}) is True


@pytest.mark.parametrize(
    "name",
    [
        "Intel(R) UHD Graphics",
        "Intel(R) Iris(R) Xe Graphics",
        "AMD Radeon(TM) Graphics",
        "AMD Radeon Graphics",
        "Microsoft Basic Display Adapter",
        "Microsoft Basic Render Driver",
        "Intel Arc A770",  # discrete but not AMD/NVIDIA — CPU path by policy
    ],
)
def test_igpu_and_non_target_gpus_do_not_match(name: str) -> None:
    assert _is_windows_discrete_amd_or_nvidia({"name": name}) is False


def test_windows_intel_uhd_recommends_cpu() -> None:
    profile = recommend_profile(
        {
            "os": "Windows",
            "nvidia": False,
            "gpus": [{"name": "Intel(R) UHD Graphics", "adapter_ram": 1_000_000_000}],
            "suggested_dml_device_id": 0,
        }
    )
    assert profile.profile == "cpu"
    assert "discrete" in profile.reason.lower() or "cpu" in profile.reason.lower()


def test_windows_amd_apu_graphics_recommends_cpu() -> None:
    profile = recommend_profile(
        {
            "os": "Windows",
            "nvidia": False,
            "gpus": [{"name": "AMD Radeon(TM) Graphics", "adapter_ram": 512_000_000}],
            "suggested_dml_device_id": 0,
        }
    )
    assert profile.profile == "cpu"


def test_windows_nvidia_discrete_recommends_dml() -> None:
    profile = recommend_profile(
        {
            "os": "Windows",
            "nvidia": True,
            "gpus": [
                {"name": "Intel(R) UHD Graphics", "adapter_ram": 128_000_000},
                {"name": "NVIDIA GeForce RTX 3060", "adapter_ram": 12_000_000_000},
            ],
            "suggested_dml_device_id": 1,
        }
    )
    assert profile.profile == "dml"
    assert profile.device_id == 1
    assert "NVIDIA" in profile.reason


def test_windows_amd_rx_recommends_dml() -> None:
    profile = recommend_profile(
        {
            "os": "Windows",
            "nvidia": False,
            "gpus": [{"name": "AMD Radeon RX 6700 XT", "adapter_ram": 12_000_000_000}],
            "suggested_dml_device_id": 0,
        }
    )
    assert profile.profile == "dml"
    assert "AMD" in profile.reason
