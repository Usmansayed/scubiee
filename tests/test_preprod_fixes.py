"""Tests for pre-production hardening (stop reliability, sync-now, install identity)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline.env_guard import install_identity_report
from pipeline.pause_resume import is_paused, pause
from pipeline.repo_lifecycle import initialize_repo, pause_repo, sync_now_repo


@pytest.fixture
def ce_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    return home


def test_pause_persists_state_before_process_release(ce_home: Path) -> None:
    saved: list[dict] = []

    def _capture(state: dict) -> None:
        saved.append(dict(state))

    with patch("pipeline.pause_resume._save_state", side_effect=_capture):
        with patch(
            "pipeline.process_control.release_scubiee_process_locks",
            return_value={"ok": True},
        ):
            with patch("pipeline.pause_resume._teardown_all_tool_surfaces", return_value=[]):
                with patch("pipeline.pause_resume._strip_agents_md_all_repos", return_value=0):
                    with patch("pipeline.pause_resume._hide_repo_scubiee_dirs", return_value=[]):
                        pause()

    assert saved, "pause should persist state at least once"
    first = saved[0]
    assert first.get("paused") is True
    assert first.get("pause_in_progress") is True
    assert is_paused() is False  # mocked _save_state does not write disk


def test_sync_now_while_repo_paused(ce_home: Path, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    initialize_repo(repo, index=False)
    pause_repo(repo, reason="maintenance")
    result = sync_now_repo(repo)
    assert result["ok"] is False
    assert result["error"] == "paused"
    assert "activate" in str(result.get("hint", "")).lower()


def test_install_identity_report_includes_active_binary() -> None:
    report = install_identity_report()
    assert "active_binary" in report
    assert "expected_binary" in report
    assert "version" in report
    assert isinstance(report.get("extra_on_path"), list)


def test_turbo_quant_single_vector_no_warning() -> None:
    import warnings

    import numpy as np

    from pipeline.turbo_quant import TurboQuantCodec

    codec = TurboQuantCodec(dim=8, bits=4, seed=1)
    vec = np.random.randn(1, 8).astype(np.float32)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        blob = codec.quantize(vec)
    assert not any(
        "invalid value" in str(item.message).lower()
        or "divide" in str(item.message).lower()
        for item in caught
    )
    assert blob["n"] == 1
    recon = codec.dequantize(blob)
    assert recon.shape == (1, 8)
