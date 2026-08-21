"""Doctor exit codes and repair classification."""

from __future__ import annotations

from pathlib import Path

from pipeline.doctor import doctor_repo


def test_doctor_ok_when_only_daemon_unbound(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "app"
    repo.mkdir()
    store_dir = tmp_path / "store"
    store_dir.mkdir()

    class FakeStore:
        base = store_dir

        def load_meta(self):
            return {"collection": "test", "chunks": 1}

    monkeypatch.setattr(
        "pipeline.preflight.inspect_capabilities",
        lambda **kwargs: {"ok": True, "accel": {}},
    )
    monkeypatch.setattr(
        "pipeline.doctor.resolve_project",
        lambda *_a, **_k: type(
            "Ref",
            (),
            {"project_id": "ce_test", "store_dir": store_dir},
        )(),
    )
    monkeypatch.setattr("pipeline.doctor.PipelineStore", lambda *_a, **_k: FakeStore())
    monkeypatch.setattr(
        "pipeline.doctor.index_is_usable",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        "pipeline.doctor.validate_manifest",
        lambda *_a, **_k: {"ok": True},
    )
    monkeypatch.setattr(
        "pipeline.daemon.validate_daemon_binding",
        lambda *_a, **_k: {
            "ok": False,
            "reason": "daemon_not_serving_repo",
            "repair": "scubiee engine ensure .",
        },
    )
    monkeypatch.setattr(
        "pipeline.dirty_journal.load_dirty_journal",
        lambda *_a, **_k: {"ok": True, "snapshot": {"paths": {}}},
    )
    monkeypatch.setattr(
        "pipeline.project_id.detect_git_family_duplicates",
        lambda: {"needs_reconcile": False},
    )
    monkeypatch.setattr(
        "pipeline.doctor.doctor_report",
        lambda: {"accel": {"preferred_profile": "cpu"}},
    )

    report = doctor_repo(repo)
    assert report["ok"] is True
    assert any(item.get("id") == "bind_daemon" for item in report["repair_plan"])
