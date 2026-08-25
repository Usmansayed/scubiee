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
