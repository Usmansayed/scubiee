from __future__ import annotations

import pytest

from pipeline import accel, runtime_profile
from pipeline.accel import AccelProfile, save_accel
from pipeline.runtime_profile import (
    RuntimeProfileState,
    activate_cpu_backup,
    load_installed_profile,
)


def test_runtime_loads_saved_profile_without_recommendation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    saved = AccelProfile(profile="dml", provider="DmlExecutionProvider", batch_size=16)
    save_accel(saved, tmp_path / "accel.json")
    monkeypatch.setattr(runtime_profile, "ACCEL_PATH", tmp_path / "accel.json")
    monkeypatch.setattr(
        accel,
        "recommend_profile",
        lambda: pytest.fail("runtime must not choose a profile"),
    )

    installed = load_installed_profile()

    assert installed is not None
    assert installed.preferred.profile == "dml"


def test_cpu_backup_changes_active_only_and_preserves_preferred() -> None:
    state = RuntimeProfileState(preferred_profile="dml", active_profile="dml")

    backed_up = activate_cpu_backup(state, "provider session failed")

    assert backed_up.preferred_profile == "dml"
    assert backed_up.active_profile == "cpu"
    assert backed_up.backup_reason == "provider session failed"
    assert state.active_profile == "dml"
    assert state.backup_reason is None


def test_missing_saved_profile_reports_absence_without_recommendation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(runtime_profile, "ACCEL_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(
        accel,
        "recommend_profile",
        lambda: pytest.fail("runtime must not choose a profile"),
    )

    assert load_installed_profile() is None
