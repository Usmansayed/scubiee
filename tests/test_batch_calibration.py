"""Install-time embed batch calibration prefers 16 unless 20 has clear ROI."""

from __future__ import annotations

from pipeline.accel import pick_batch_size


def test_pick_batch_keeps_16_when_20_is_marginal() -> None:
    winner, reason = pick_batch_size({8: 30.0, 16: 37.0, 20: 38.0})
    assert winner == 16
    assert "poor ROI" in reason


def test_pick_batch_promotes_20_when_roi_is_clear() -> None:
    winner, reason = pick_batch_size({8: 20.0, 16: 30.0, 20: 40.0})
    assert winner == 20
    assert "beats 16" in reason


def test_pick_batch_prefers_16_over_slightly_faster_8() -> None:
    winner, reason = pick_batch_size({8: 38.0, 16: 37.0, 20: 37.2})
    assert winner == 16
    assert "16" in reason


def test_pick_batch_downgrades_to_8_when_16_is_much_worse() -> None:
    winner, reason = pick_batch_size({8: 40.0, 16: 30.0})
    assert winner == 8
    assert "beats" in reason


def test_pick_batch_uses_20_when_16_missing() -> None:
    winner, reason = pick_batch_size({8: 22.0, 20: 28.0})
    assert winner == 20
    assert "16 unavailable" in reason


def test_pick_batch_defaults_when_empty() -> None:
    winner, reason = pick_batch_size({})
    assert winner == 16
    assert "default prefer" in reason
