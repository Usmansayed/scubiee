"""Auto-admission limits — explicit open bypasses large-repo pause."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from pipeline.ce_service import RuntimeManager


def _activated(project_id: str = "ce_big") -> dict:
    return {
        "ok": True,
        "status": "activated",
        "project_id": project_id,
        "root": "/tmp/big",
        "state": "active",
    }


def test_admit_request_pauses_passive_large_repo(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "big"
    repo.mkdir()
    mgr = RuntimeManager()
    monkeypatch.setattr(
        "pipeline.repo_lifecycle.activate_repo", lambda _root: _activated()
    )
    monkeypatch.setattr(mgr, "_repo_file_count", lambda *_a, **_k: 15_000)
    monkeypatch.setattr(mgr, "_auto_limits", lambda: (8, 10_000))

    out = mgr.admit_request(repo, explicit=False)

    assert out["status"] == "paused"
    assert out["pause_reason"] == "large_repo"
    assert out["file_count"] == 15_000


def test_admit_request_explicit_bypasses_large_repo(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "big"
    repo.mkdir()
    mgr = RuntimeManager()
    runtime = MagicMock()
    runtime.engine = object()
    runtime.warm_state = "ready"
    runtime.project_id = "ce_big"

    monkeypatch.setattr(
        "pipeline.repo_lifecycle.activate_repo", lambda _root: _activated()
    )
    monkeypatch.setattr(mgr, "_repo_file_count", lambda *_a, **_k: 15_000)
    monkeypatch.setattr(mgr, "_auto_limits", lambda: (8, 10_000))
    monkeypatch.setattr(mgr, "_activate_runtime", lambda *_a, **_k: runtime)
    monkeypatch.setattr(
        mgr,
        "_warm_registered",
        lambda _root: {"ok": True, "warm_state": "ready"},
    )

    out = mgr.admit_request(repo, explicit=True)

    assert out["status"] == "activated"
    assert out.get("pause_reason") is None
