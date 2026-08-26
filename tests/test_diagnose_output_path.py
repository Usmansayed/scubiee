"""Diagnose output path resolution for non-CS share workflows."""

from __future__ import annotations

import os
from pathlib import Path

from pipeline.diagnose import resolve_diagnose_output_path


def test_desktop_flag_writes_home_desktop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    out = resolve_diagnose_output_path(None, desktop=True)
    assert out == tmp_path / "Desktop" / "scubiee-diagnose.json"
    assert (tmp_path / "Desktop").is_dir()


def test_powershell_env_literal_is_expanded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    raw = r"$env:USERPROFILE\Desktop\scubiee-diagnose.json"
    out = resolve_diagnose_output_path(raw)
    assert out == tmp_path / "Desktop" / "scubiee-diagnose.json"


def test_cmd_percent_env_is_expanded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    raw = r"%USERPROFILE%\Desktop\scubiee-diagnose.json"
    out = resolve_diagnose_output_path(raw)
    assert out == Path(os.path.expandvars(raw))


def test_stale_accel_flagged_when_fastembed_missing() -> None:
    from pipeline.diagnose import _stale_accel_vs_packages

    warn = _stale_accel_vs_packages(
        {"profile": "cpu", "backend": "fastembed", "texts_per_sec": 2.6},
        {"fastembed": None, "onnxruntime": None},
    )
    assert warn is not None
    assert warn["stale_accel"] is True
    assert "fastembed" in warn["missing_packages"]
    assert "setup --repair" in warn["hint"]


def test_stale_accel_clear_when_packages_present() -> None:
    from pipeline.diagnose import _stale_accel_vs_packages

    assert (
        _stale_accel_vs_packages(
            {"profile": "cpu", "backend": "fastembed"},
            {"fastembed": "0.4", "onnxruntime": "1.20"},
        )
        is None
    )
