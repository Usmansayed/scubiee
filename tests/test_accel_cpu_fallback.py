"""CPU fallback safeguards — calibration must not hang setup forever."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from pipeline.accel import (
    AccelProfile,
    BATCH_PREFER,
    _demote_stale_dml_profile,
    _do_calibration,
    _fallback_to_cpu_profile,
    _run_with_timeout,
    _saved_dml_still_has_discrete_gpu,
    resolve_runtime,
)


def test_run_with_timeout_raises() -> None:
    import time

    with pytest.raises(TimeoutError):
        _run_with_timeout(lambda: time.sleep(2.0), 0.2, label="sleep")


def test_run_with_timeout_returns_value() -> None:
    assert _run_with_timeout(lambda: 42, 2.0, label="fast") == 42


def test_fallback_to_cpu_mutates_profile() -> None:
    profile = AccelProfile(
        profile="dml",
        provider="DmlExecutionProvider",
        reason="was dml",
    )
    _fallback_to_cpu_profile(profile, "probe timed out", progress=None)
    assert profile.profile == "cpu"
    assert profile.provider == "CPUExecutionProvider"
    assert "timed out" in profile.reason


def test_saved_dml_with_intel_only_is_not_discrete() -> None:
    profile = AccelProfile(
        profile="dml",
        provider="DmlExecutionProvider",
        detected={
            "os": "Windows",
            "nvidia": False,
            "gpus": [{"name": "Intel(R) UHD Graphics", "adapter_ram": 1_000_000_000}],
        },
    )
    assert _saved_dml_still_has_discrete_gpu(profile) is False


def test_saved_dml_with_rtx_is_discrete() -> None:
    profile = AccelProfile(
        profile="dml",
        provider="DmlExecutionProvider",
        detected={
            "os": "Windows",
            "nvidia": True,
            "gpus": [{"name": "NVIDIA GeForce RTX 3060", "adapter_ram": 12_000_000_000}],
        },
    )
    assert _saved_dml_still_has_discrete_gpu(profile) is True


def test_resolve_runtime_demotes_stale_dml(tmp_path: Path, monkeypatch) -> None:
    accel_path = tmp_path / "accel.json"
    monkeypatch.setattr("pipeline.accel.ACCEL_PATH", accel_path)
    stale = AccelProfile(
        profile="dml",
        provider="DmlExecutionProvider",
        batch_size=16,
        detected={
            "os": "Windows",
            "nvidia": False,
            "gpus": [{"name": "Intel(R) UHD Graphics", "adapter_ram": 128_000_000}],
        },
    )
    from pipeline.accel import save_accel

    save_accel(stale, accel_path)
    monkeypatch.delenv("CTX_FORCE_DML", raising=False)
    got = resolve_runtime()
    assert got.profile == "cpu"
    assert got.provider == "CPUExecutionProvider"
    reloaded = resolve_runtime()
    assert reloaded.profile == "cpu"


def test_do_calibration_falls_back_when_probe_times_out(monkeypatch) -> None:
    profile = AccelProfile(
        profile="dml",
        provider="DmlExecutionProvider",
        detected={"os": "Windows", "gpus": [{"name": "NVIDIA GeForce RTX 4090"}]},
    )

    def boom(*_a, **_k):
        raise TimeoutError("probe exceeded")

    monkeypatch.setattr("pipeline.accel._probe_gpu_embed", boom)

    def fake_cpu_calibrate(prof):
        assert prof.profile == "cpu"
        return {
            "ok": True,
            "winner": BATCH_PREFER,
            "texts_per_sec": 12.0,
            "reason": "cpu ok",
            "candidates": {},
            "errors": {},
        }

    monkeypatch.setattr("pipeline.accel.calibrate_batch", fake_cpu_calibrate)
    monkeypatch.setattr(
        "pipeline.accel._calibrate_with_timeout",
        lambda prof, timeout_s: fake_cpu_calibrate(prof),
    )
    _do_calibration(profile, progress=None)
    assert profile.profile == "cpu"
    assert profile.batch_calibration.get("ok") is True
    assert profile.texts_per_sec == 12.0
