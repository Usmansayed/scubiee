"""Doctor / certify CLI contract tests."""

from __future__ import annotations

from pathlib import Path


def test_doctor_reports_capability_gaps(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    from pipeline.doctor import doctor_repo
    from pipeline.preflight import inspect_capabilities

    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "a.py").write_text("a=1\n", encoding="utf-8")
    report = doctor_repo(repo)
    caps = inspect_capabilities(require_semantic=True)
    assert "capabilities" in report
    assert "repairs" in report
    # If deps missing, doctor must not claim ok
    if not caps["ok"]:
        assert report["ok"] is False
        assert report["repairs"]
