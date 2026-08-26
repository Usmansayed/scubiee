"""Saved install profile and process-local runtime profile state."""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from typing import Any, Mapping

from pipeline.accel import ACCEL_PATH, AccelProfile, load_accel


@dataclass(frozen=True)
class EnvelopeConfig:
    """Persisted resource envelope values, without runtime derivation policy."""

    tier: str = "standard"
    batch_ceiling: int = 16
    embed_workers: int = 1
    index_workers: int = 1
    aggressive_unload: bool = False
    queue_limit: int = 2

    @classmethod
    def from_saved(
        cls,
        saved: Mapping[str, Any],
        *,
        fallback_batch: int,
    ) -> EnvelopeConfig:
        return cls(
            tier=str(saved.get("tier", "standard")),
            batch_ceiling=int(saved.get("batch_ceiling", fallback_batch)),
            embed_workers=int(saved.get("embed_workers", 1)),
            index_workers=int(saved.get("index_workers", 1)),
            aggressive_unload=bool(saved.get("aggressive_unload", False)),
            queue_limit=int(saved.get("queue_limit", 2)),
        )


@dataclass(frozen=True)
class InstalledProfile:
    """Install-time choices loaded unchanged for runtime use."""

    preferred: AccelProfile
    envelope: EnvelopeConfig
    hardware_fingerprint: str


@dataclass(frozen=True)
class RuntimeProfileState:
    """Process-local active profile, including temporary CPU backup state."""

    preferred_profile: str
    active_profile: str
    backup_reason: str | None = None


_STATE: RuntimeProfileState | None = None
_STATE_LOCK = threading.RLock()


def load_installed_profile() -> InstalledProfile | None:
    """Load persisted install data without selecting or calibrating a profile."""

    preferred = load_accel(ACCEL_PATH)
    if preferred is None:
        return None
    return InstalledProfile(
        preferred=preferred,
        envelope=EnvelopeConfig.from_saved(
            preferred.envelope,
            fallback_batch=preferred.batch_size,
        ),
        hardware_fingerprint=preferred.hardware_fingerprint,
    )


def activate_cpu_backup(
    state: RuntimeProfileState,
    reason: str,
) -> RuntimeProfileState:
    """Return temporary CPU-active state while preserving the preference."""

    return replace(state, active_profile="cpu", backup_reason=reason)


def get_runtime_profile_state() -> RuntimeProfileState:
    """Return process-local state, initialized from the saved preference."""

    global _STATE
    with _STATE_LOCK:
        if _STATE is None:
            installed = load_installed_profile()
            preferred = installed.preferred.profile if installed else "cpu"
            _STATE = RuntimeProfileState(preferred, preferred)
        return _STATE


def set_runtime_profile_state(state: RuntimeProfileState) -> RuntimeProfileState:
    """Publish process-local state without changing the installed profile."""

    global _STATE
    with _STATE_LOCK:
        _STATE = state
        return _STATE
