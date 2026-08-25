"""Windows DirectML must require discrete AMD/NVIDIA GPUs (multi-signal)."""

from __future__ import annotations

import pytest

from pipeline.accel import (
    _is_windows_amd_discrete,
    _is_windows_discrete_amd_or_nvidia,
    _is_windows_nvidia_discrete,
    _windows_pci_device_id,
    _windows_pci_vendor,
    recommend_profile,
)


DISCRETE_YES = [
    # NVIDIA — common OEM strings
    "NVIDIA GeForce RTX 4070",
    "NVIDIA GeForce RTX 4060 Laptop GPU",
    "NVIDIA GeForce GTX 1660 Ti",
    "NVIDIA GeForce GTX 1050",
    "NVIDIA Quadro T1000",
    "NVIDIA RTX A2000",
    "NVIDIA Tesla T4",
    "NVIDIA Titan Xp",
    # AMD discrete
    "AMD Radeon RX 7800 XT",
    "AMD Radeon RX 6500M",
    "AMD Radeon RX 580",
    "Radeon Pro W6800",
    "AMD Radeon HD 7700M Series",
    "AMD Radeon R9 M290X",
    "AMD Radeon RX Vega 56",
    "AMD FirePro W5100",
    "AMD Radeon Instinct MI25",
]


CPU_ONLY_NO = [
    "Intel(R) UHD Graphics",
    "Intel(R) UHD Graphics 770",
    "Intel(R) HD Graphics 4600",
    "Intel(R) Iris(R) Xe Graphics",
    "Intel Arc A770",
    "AMD Radeon(TM) Graphics",
    "AMD Radeon Graphics",
    "AMD Radeon(TM) Vega 8 Graphics",
    "AMD Radeon(TM) RX Vega 11 Graphics",
    "AMD Radeon 780M",
    "AMD Radeon 760M Graphics",
    "AMD Radeon 680M",
    "AMD Radeon 890M",
    "Microsoft Basic Display Adapter",
    "Microsoft Basic Render Driver",
    "Microsoft Remote Display Adapter",
    "VMware SVGA 3D",
    "",  # empty name
]


@pytest.mark.parametrize("name", DISCRETE_YES)
def test_discrete_amd_nvidia_names_match(name: str) -> None:
    assert _is_windows_discrete_amd_or_nvidia({"name": name}) is True


@pytest.mark.parametrize("name", CPU_ONLY_NO)
def test_igpu_and_non_target_gpus_do_not_match(name: str) -> None:
    assert _is_windows_discrete_amd_or_nvidia({"name": name}) is False


def test_pci_vendor_nvidia_without_marketing_name() -> None:
    gpu = {
        "name": "Display adapter",
        "pnp_device_id": r"PCI\VEN_10DE&DEV_2206&SUBSYS_1234&REV_A1",
        "adapter_compatibility": "NVIDIA",
    }
    assert _windows_pci_vendor(gpu) == "nvidia"
    assert _is_windows_nvidia_discrete(gpu) is True
    assert _is_windows_discrete_amd_or_nvidia(gpu) is True


def test_pci_vendor_amd_without_allowlisted_name_is_cpu_safe() -> None:
    """Ambiguous AMD name + VEN_1002 → CPU (no false DML)."""
    gpu = {
        "name": "AMD Graphics Device",
        "pnp_device_id": r"PCI\VEN_1002&DEV_15E7&SUBSYS_0000&REV_C2",
        "adapter_compatibility": "Advanced Micro Devices, Inc.",
    }
    assert _windows_pci_vendor(gpu) == "amd"
    assert _is_windows_amd_discrete(gpu) is False
    assert _is_windows_discrete_amd_or_nvidia(gpu) is False


def test_pci_vendor_amd_rx_still_dml() -> None:
    gpu = {
        "name": "AMD Radeon RX 6700 XT",
        "pnp_device_id": r"PCI\VEN_1002&DEV_73DF&SUBSYS_0000&REV_C1",
        "adapter_compatibility": "Advanced Micro Devices, Inc.",
    }
    assert _is_windows_discrete_amd_or_nvidia(gpu) is True


def test_pci_device_id_apu_denied_even_with_weird_name() -> None:
    """Structural: Rembrandt APU DEV_1638 never DML even if OEM renames it."""
    gpu = {
        "name": "OEM Mystery Graphics Adapter",
        "pnp_device_id": r"PCI\VEN_1002&DEV_1638&SUBSYS_13AB1462&REV_C2",
        "adapter_compatibility": "Advanced Micro Devices, Inc.",
    }
    assert _windows_pci_device_id(gpu) == "1638"
    assert _is_windows_discrete_amd_or_nvidia(gpu) is False


def test_pci_device_id_known_discrete_even_with_weird_name() -> None:
    """Structural: Navi24 DEV_743F (RX 6500M) is discrete even with empty marketing name."""
    gpu = {
        "name": "AMD Display Adapter",
        "pnp_device_id": r"PCI\VEN_1002&DEV_743F&SUBSYS_13AB1462&REV_C1",
        "adapter_compatibility": "Advanced Micro Devices, Inc.",
    }
    assert _windows_pci_device_id(gpu) == "743f"
    assert _is_windows_discrete_amd_or_nvidia(gpu) is True


def test_bare_nvidia_flag_without_discrete_adapter_is_cpu() -> None:
    """nvidia-smi alone must not pick DML when WMI only shows Intel iGPU."""
    profile = recommend_profile(
        {
            "os": "Windows",
            "nvidia": True,
            "windows_discrete_amd_nvidia": True,  # stale/liar flag
            "gpus": [{"name": "Intel(R) UHD Graphics", "adapter_ram": 1_000_000_000}],
            "suggested_dml_device_id": 0,
        }
    )
    assert profile.profile == "cpu"


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


def test_windows_amd_780m_igpu_recommends_cpu() -> None:
    profile = recommend_profile(
        {
            "os": "Windows",
            "nvidia": False,
            "gpus": [{"name": "AMD Radeon 780M", "adapter_ram": 512_000_000}],
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


def test_windows_hd_7700m_discrete_recommends_dml() -> None:
    profile = recommend_profile(
        {
            "os": "Windows",
            "nvidia": False,
            "gpus": [
                {"name": "Intel(R) HD Graphics 4000", "adapter_ram": 64_000_000},
                {"name": "AMD Radeon HD 7700M Series", "adapter_ram": 2_000_000_000},
            ],
            "suggested_dml_device_id": 1,
        }
    )
    assert profile.profile == "dml"
    assert profile.device_id == 1
