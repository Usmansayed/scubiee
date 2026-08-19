"""pip install must drain stdout or Windows deadlocks."""

from __future__ import annotations

import os
import sys

from pipeline.accel import (
    AccelProfile,
    _align_profile_to_ort,
    _requirement_satisfied,
    _run_pip_captured,
)


def test_align_profile_falls_back_when_dml_missing(monkeypatch):
    monkeypatch.setattr(
        "pipeline.accel.ort_available_providers",
        lambda: ["CPUExecutionProvider", "AzureExecutionProvider"],
    )
    prof = AccelProfile(profile="dml", provider="DmlExecutionProvider")
    _align_profile_to_ort(prof)
    assert prof.profile == "cpu"
    assert prof.provider == "CPUExecutionProvider"


def test_requirement_satisfied_for_installed_pip():
    assert _requirement_satisfied("pip>=1")
    assert not _requirement_satisfied("definitely-not-a-real-pkg-xyz>=1")


def test_run_pip_captured_drains_large_stdout():
    rc, out = _run_pip_captured(
        [sys.executable, "-c", "print('x' * 80000, end='')"],
        os.environ.copy(),
    )
    assert rc == 0
    assert len(out) >= 80000
