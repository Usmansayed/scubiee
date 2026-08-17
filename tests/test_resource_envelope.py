from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import pytest

from pipeline import accel
from pipeline.accel import AccelProfile
from pipeline.resource_envelope import derive_envelope
from pipeline.resources import ResourceManager, SystemSample


def test_low_memory_envelope_caps_batch_and_workers() -> None:
    env = derive_envelope(16_000, 2_500, calibrated_batch=16, cpu_count=8)

    assert env.tier == "low"
    assert env.batch_ceiling <= 4
    assert env.embed_workers == 1
    assert env.index_workers == 1
    assert env.aggressive_unload is True
    assert env.queue_limit == 1


def test_standard_memory_envelope_caps_batch_at_16() -> None:
    env = derive_envelope(16_000, 6_000, calibrated_batch=20, cpu_count=8)

    assert env.tier == "standard"
    assert env.batch_ceiling == 16
    assert env.embed_workers == 1
    assert env.index_workers == 2
    assert env.aggressive_unload is False
    assert env.queue_limit == 2


def test_high_memory_envelope_keeps_calibrated_16() -> None:
    env = derive_envelope(32_768, 20_000, calibrated_batch=16, cpu_count=16)

    assert env.tier == "high"
    assert env.batch_ceiling == 16
    assert env.embed_workers == 1
    assert env.index_workers > 1
    assert env.aggressive_unload is False
    assert env.queue_limit == 4


@pytest.mark.parametrize("total_mb", [32_000, 32_767])
def test_high_memory_envelope_requires_32_768_mib(total_mb: float) -> None:
    env = derive_envelope(total_mb, 20_000, calibrated_batch=16, cpu_count=16)

    assert env.tier == "standard"


def test_resource_manager_uses_saved_calibration_as_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved = AccelProfile(
        profile="dml",
        provider="DmlExecutionProvider",
        batch_size=16,
        batch_calibration={"winner": 20},
    )
    monkeypatch.setattr(accel, "load_accel", lambda: saved)
    monkeypatch.setattr(
        accel,
        "recommend_profile",
        lambda *args, **kwargs: pytest.fail("runtime must not recommend acceleration"),
    )
    monkeypatch.setattr(
        accel,
        "configure",
        lambda *args, **kwargs: pytest.fail("runtime must not configure acceleration"),
    )
    monkeypatch.setattr(
        accel,
        "calibrate_batch",
        lambda *args, **kwargs: pytest.fail("runtime must not calibrate acceleration"),
    )
    monkeypatch.setenv("CTX_EMBED_BATCH", "64")
    rm = ResourceManager()
    healthy = SystemSample(
        cpu_percent=10.0,
        ram_available_mb=20_000,
        ram_total_mb=32_768,
        ram_percent=37.5,
    )

    with patch.object(rm, "sample", side_effect=[healthy, replace(healthy)]):
        rm.budget("embed")
        promoted = rm.budget("embed")

    assert promoted.batch_size == 20


def test_resource_manager_requires_two_samples_each_way_for_hysteresis() -> None:
    rm = ResourceManager()
    rm._base_batch = 16
    low = SystemSample(
        cpu_percent=40.0,
        ram_available_mb=2_500,
        ram_total_mb=16_000,
        ram_percent=84.4,
    )
    standard = SystemSample(
        cpu_percent=40.0,
        ram_available_mb=6_000,
        ram_total_mb=16_000,
        ram_percent=62.5,
    )

    with patch.object(
        rm,
        "sample",
        side_effect=[low, replace(low), standard, replace(standard)],
    ):
        first_low = rm.budget("embed")
        second_low = rm.budget("embed")
        first_healthy = rm.budget("embed")
        second_healthy = rm.budget("embed")

    assert first_low.batch_size == 16
    assert second_low.batch_size == 4
    assert first_healthy.batch_size == 4
    assert second_healthy.batch_size == 16


def test_cached_sample_does_not_count_twice_for_demotion() -> None:
    rm = ResourceManager()
    rm._base_batch = 16
    low = SystemSample(
        cpu_percent=40.0,
        ram_available_mb=2_500,
        ram_total_mb=16_000,
        ram_percent=84.4,
    )

    with patch.object(rm, "sample", side_effect=[low, low, replace(low)]):
        first = rm.budget("embed")
        repeated = rm.budget("embed")
        fresh = rm.budget("embed")

    assert first.batch_size == 16
    assert repeated.batch_size == 16
    assert fresh.batch_size == 4


def test_cached_sample_does_not_count_twice_for_promotion() -> None:
    rm = ResourceManager()
    rm._base_batch = 16
    low = SystemSample(
        cpu_percent=40.0,
        ram_available_mb=2_500,
        ram_total_mb=16_000,
        ram_percent=84.4,
    )
    standard = SystemSample(
        cpu_percent=40.0,
        ram_available_mb=6_000,
        ram_total_mb=16_000,
        ram_percent=62.5,
    )

    with patch.object(
        rm,
        "sample",
        side_effect=[low, replace(low), standard, standard, replace(standard)],
    ):
        rm.budget("embed")
        demoted = rm.budget("embed")
        first_healthy = rm.budget("embed")
        repeated = rm.budget("embed")
        fresh = rm.budget("embed")

    assert demoted.batch_size == 4
    assert first_healthy.batch_size == 4
    assert repeated.batch_size == 4
    assert fresh.batch_size == 16
