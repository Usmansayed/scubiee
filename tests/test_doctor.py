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
        "pipeline.doctor.inspect_capabilities",
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


def test_published_journal_entries_are_not_pending(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    from pipeline.dirty_journal import save_dirty_journal
    from pipeline.doctor import _journal_pending

    save_dirty_journal(
        "ce_doctor_journal",
        {"paths": {
            "done.md": {"path": "done.md", "state": "published"},
            "todo.py": {"path": "todo.py", "state": "queued"},
        }},
    )
    pending = _journal_pending("ce_doctor_journal")
    assert pending["pending"] is True and pending["paths"] == ["todo.py"]
    assert 0 <= pending["age_s"] < 60

    save_dirty_journal("ce_doctor_journal", {"paths": {"done.md": {"path": "done.md", "state": "published"}}})
    cleared = _journal_pending("ce_doctor_journal")
    assert cleared["pending"] is False and cleared["paths"] == []


def test_pending_journal_is_only_a_repair_when_a_bound_engine_is_stuck() -> None:
    from pipeline.doctor import JOURNAL_STUCK_AFTER_S, _journal_status, plan_repairs

    bound, unbound = {"ok": True}, {"ok": False}
    assert _journal_status({"pending": False}, bound) == "clear"
    assert _journal_status({"pending": True, "age_s": 2.0}, bound) == "syncing"
    assert _journal_status({"pending": True, "age_s": 2.0}, unbound) == "replays_on_engine_start"
    assert _journal_status({"pending": True, "age_s": JOURNAL_STUCK_AFTER_S + 1}, bound) == "stuck"

    def ids(status: str) -> list[str]:
        report = {"readiness": {"index_usable": True}, "journal": {"pending": True, "status": status}}
        return [item["id"] for item in plan_repairs(report=report)]

    assert "replay_dirty_journal" not in ids("syncing")
    assert "replay_dirty_journal" not in ids("replays_on_engine_start")
    assert "replay_dirty_journal" in ids("stuck")
