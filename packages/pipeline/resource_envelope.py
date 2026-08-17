"""Portable, deterministic resource envelopes derived from available memory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EnvelopeTier = Literal["low", "standard", "high"]


@dataclass(frozen=True)
class EnvelopeConfig:
    tier: EnvelopeTier
    batch_ceiling: int
    embed_workers: int
    index_workers: int
    aggressive_unload: bool
    queue_limit: int


def derive_envelope(
    total_mb: float,
    available_mb: float,
    calibrated_batch: int,
    cpu_count: int,
) -> EnvelopeConfig:
    """Derive the same runtime envelope on Windows, Linux, and macOS."""

    batch = max(1, int(calibrated_batch))
    cpus = max(1, int(cpu_count))
    if total_mb <= 8_192 or available_mb < 3_072:
        return EnvelopeConfig("low", min(4, batch), 1, 1, True, 1)
    if total_mb >= 32_768 and available_mb >= 8_192:
        return EnvelopeConfig("high", batch, 1, min(4, max(1, cpus // 4)), False, 4)
    return EnvelopeConfig("standard", min(16, batch), 1, min(2, max(1, cpus // 4)), False, 2)
