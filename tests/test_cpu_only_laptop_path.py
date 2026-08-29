"""End-to-end CPU-only laptop path — every branch a weak Windows box hits.

Simulates Intel UHD / AMD APU / no-GPU Windows machines without that hardware.
Also locks Mac M-series out of the CPU-only path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline import accel, hardware
from pipeline.accel import (
    AccelProfile,
    BATCH_PREFER,
    CPU_BATCH_CALIBRATE_N,
    calibrate_batch,
    configure,
    conflicting_ort_packages,
    ort_packages_for,
    recommend_profile,
    resolve_runtime,
)


def _windows_cpu_only(
    *gpu_names: str,
    nvidia: bool = False,
) -> dict:
    gpus = [
        {"name": name, "adapter_ram": 512_000_000 if i == 0 else 128_000_000}
        for i, name in enumerate(gpu_names or ("Intel(R) UHD Graphics",))
    ]
    return {
        "os": "Windows",
        "machine": "AMD64",
        "python": "3.13.0",
        "nvidia": nvidia,
        "gpus": gpus,
        "cpu_count": 8,
        "suggested_dml_device_id": 0,
        "windows_discrete_amd_nvidia": False,
    }


CPU_ONLY_CASES = [
    ("intel_uhd", ("Intel(R) UHD Graphics",)),
    ("iris_xe", ("Intel(R) Iris(R) Xe Graphics",)),
    ("amd_apu", ("AMD Radeon(TM) Graphics",)),
    ("amd_radeon_graphics", ("AMD Radeon Graphics",)),
    ("basic_display", ("Microsoft Basic Display Adapter",)),
    ("no_gpus", ()),
    ("intel_plus_basic", ("Intel(R) UHD Graphics", "Microsoft Basic Render Driver")),
    ("intel_arc_policy", ("Intel Arc A770",)),  # discrete but not AMD/NVIDIA → CPU by policy
]


@pytest.mark.parametrize("label,names", CPU_ONLY_CASES, ids=[c[0] for c in CPU_ONLY_CASES])
def test_recommend_selects_cpu_for_every_cpu_only_windows_shape(
    label: str, names: tuple[str, ...]
) -> None:
    profile = recommend_profile(_windows_cpu_only(*names))
    assert profile.profile == "cpu", f"{label}: got {profile.profile} ({profile.reason})"
    assert profile.provider == "CPUExecutionProvider"
    assert "discrete" in profile.reason.lower() or "cpu" in profile.reason.lower()


def test_recommend_still_picks_dml_for_discrete_nvidia() -> None:
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


def test_ort_packages_for_cpu_are_plain_onnxruntime() -> None:
    pkgs = ort_packages_for("cpu")
    assert any(p.startswith("onnxruntime>") or p.startswith("onnxruntime=") for p in pkgs)
    assert not any("directml" in p or "gpu" in p for p in pkgs)
    conflict = conflicting_ort_packages("cpu")
    assert "onnxruntime-directml" in conflict
    assert "onnxruntime-gpu" in conflict


def test_configure_cpu_only_laptop_persists_and_calibrates_light(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Full configure() as if install saw only Intel UHD — light CPU calibrate + save."""
    accel_path = tmp_path / "accel.json"
    detected = _windows_cpu_only("Intel(R) UHD Graphics")
    mib = 1024 * 1024
    snapshot = {
        **detected,
        "cpu_model": "Fake CPU-only laptop",
        "cpu_count_logical": 8,
        "ram_total_bytes": 16_384 * mib,
        "ram_available_bytes": 8_000 * mib,
    }

    class FakeEmbed:
        def __init__(self, *a, **k):
            pass

        def embed(self, texts, batch_size=1, parallel=None):
            return [None] * len(texts)

    monkeypatch.setattr(accel, "ACCEL_PATH", accel_path)
    monkeypatch.setattr(accel, "detect_hardware", lambda: detected)
    monkeypatch.setattr(hardware, "ensure_hardware_snapshot", lambda **kwargs: snapshot)
    monkeypatch.setattr(accel, "register_coderank", lambda: None)
    monkeypatch.setattr(accel, "TextEmbedding", FakeEmbed, raising=False)

    import sys
    import types

    fake_fe = types.ModuleType("fastembed")
    fake_fe.TextEmbedding = FakeEmbed
    monkeypatch.setitem(sys.modules, "fastembed", fake_fe)

    profile = configure(
        install_pkgs=False,
        download_model=False,
        bench=True,
    )
    persisted = accel.load_accel(accel_path)

    assert profile.profile == "cpu"
    assert profile.provider == "CPUExecutionProvider"
    assert profile.batch_calibration.get("ok") is True
    assert profile.batch_calibration.get("light_cpu") is True
    assert profile.batch_calibration.get("n") == CPU_BATCH_CALIBRATE_N
    assert profile.batch_calibration.get("winner") == 16
    assert persisted is not None
    assert persisted.profile == "cpu"
    assert persisted.batch_calibration == profile.batch_calibration
    assert persisted.envelope is not None
    assert persisted.envelope.get("batch_ceiling") == 16


@pytest.mark.parametrize(
    "gpu_name",
    [
        "Intel(R) UHD Graphics",
        "AMD Radeon(TM) Graphics",
        "Microsoft Basic Display Adapter",
    ],
)
def test_configure_every_igpu_name_ends_cpu_not_dml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, gpu_name: str
) -> None:
    accel_path = tmp_path / "accel.json"
    detected = _windows_cpu_only(gpu_name)
    monkeypatch.setattr(accel, "ACCEL_PATH", accel_path)
    monkeypatch.setattr(accel, "detect_hardware", lambda: detected)
    monkeypatch.setattr(
        hardware,
        "ensure_hardware_snapshot",
        lambda **kwargs: {**detected, "ram_total_bytes": 8e9, "ram_available_bytes": 4e9},
    )
    monkeypatch.setattr(
        accel,
        "calibrate_batch",
        lambda profile: {
            "ok": True,
            "winner": 16,
            "texts_per_sec": 10.0,
            "light_cpu": True,
            "n": 16,
            "candidates": {"16": 10.0},
            "reason": "light",
        },
    )
    profile = configure(install_pkgs=False, download_model=False, bench=True)
    assert profile.profile == "cpu"
    assert accel.load_accel(accel_path).profile == "cpu"


def test_stale_dml_accel_json_from_old_install_demotes_on_resolve(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Exact failure mode from the hung Windows laptop screenshot."""
    accel_path = tmp_path / "accel.json"
    monkeypatch.setattr(accel, "ACCEL_PATH", accel_path)
    monkeypatch.delenv("CTX_FORCE_DML", raising=False)
    accel.save_accel(
        AccelProfile(
            profile="dml",
            provider="DmlExecutionProvider",
            batch_size=16,
            reason="old install picked any DXGI adapter",
            detected=_windows_cpu_only("Intel(R) UHD Graphics"),
        )
    )
    got = resolve_runtime()
    assert got.profile == "cpu"
    on_disk = json.loads(accel_path.read_text(encoding="utf-8"))
    assert on_disk["profile"] == "cpu"


def test_calibration_timeout_on_fake_dml_falls_back_then_light_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = AccelProfile(
        profile="dml",
        provider="DmlExecutionProvider",
        detected=_windows_cpu_only("Intel(R) UHD Graphics"),
    )

    def hang(*_a, **_k):
        raise TimeoutError("probe exceeded 45s")

    monkeypatch.setattr(accel, "_probe_gpu_embed", hang)

    class FakeEmbed:
        def __init__(self, *a, **k):
            pass

        def embed(self, texts, batch_size=1, parallel=None):
            return [None] * len(texts)

    monkeypatch.setattr(accel, "register_coderank", lambda: None)
    monkeypatch.setattr(accel, "TextEmbedding", FakeEmbed, raising=False)
    import sys
    import types

    fake_fe = types.ModuleType("fastembed")
    fake_fe.TextEmbedding = FakeEmbed
    monkeypatch.setitem(sys.modules, "fastembed", fake_fe)

    accel._do_calibration(profile, progress=None)
    assert profile.profile == "cpu"
    assert profile.batch_calibration.get("ok") is True
    assert profile.batch_calibration.get("light_cpu") is True


def test_apple_m_series_never_selected_as_cpu_only() -> None:
    for chip in ("Apple M1", "Apple M2 Pro", "Apple M3 Max", "Apple M4"):
        profile = recommend_profile(
            {
                "os": "Darwin",
                "machine": "arm64",
                "apple_silicon": True,
                "nvidia": False,
                "gpus": [{"name": chip, "adapter_ram": 0}],
            }
        )
        assert profile.profile == "mlx", chip


def test_force_profile_cpu_overrides_even_if_discrete_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    accel_path = tmp_path / "accel.json"
    detected = {
        "os": "Windows",
        "nvidia": True,
        "gpus": [{"name": "NVIDIA GeForce RTX 4090", "adapter_ram": 24_000_000_000}],
        "suggested_dml_device_id": 0,
        "cpu_count": 16,
    }
    monkeypatch.setattr(accel, "ACCEL_PATH", accel_path)
    monkeypatch.setattr(accel, "detect_hardware", lambda: detected)
    monkeypatch.setattr(
        hardware,
        "ensure_hardware_snapshot",
        lambda **kwargs: {**detected, "ram_total_bytes": 32e9, "ram_available_bytes": 16e9},
    )
    monkeypatch.setattr(
        accel,
        "calibrate_batch",
        lambda profile: {
            "ok": True,
            "winner": BATCH_PREFER,
            "texts_per_sec": 9.0,
            "light_cpu": True,
            "candidates": {"16": 9.0},
            "reason": "forced",
        },
    )
    profile = configure(
        force_profile="cpu",
        install_pkgs=False,
        download_model=False,
        bench=True,
    )
    assert profile.profile == "cpu"
    assert "forced" in profile.reason


def test_real_light_cpu_calibrate_against_installed_fastembed() -> None:
    """Live smoke: real FastEmbed CPU calibrate must finish quickly with light corpus."""
    pytest.importorskip("fastembed")
    profile = AccelProfile(profile="cpu", provider="CPUExecutionProvider")
    try:
        out = calibrate_batch(profile)
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "no_suchfile" in msg or "cache" in msg or "local_files_only" in msg:
            pytest.skip(f"CodeRank model not cached locally: {exc}")
        raise
    assert out["ok"] is True
    assert out.get("light_cpu") is True
    assert out["winner"] == 16
    assert out["n"] == CPU_BATCH_CALIBRATE_N
    assert out["texts_per_sec"] is None or float(out["texts_per_sec"]) >= 0
